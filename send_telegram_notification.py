#!/usr/bin/env python3
"""
Helper script to send Telegram notifications from Claude Code hooks.
Called by notify_telegram.sh when Claude finishes responding.
"""

import os
import sys
import time
import logging
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError as ReqConnectionError
from dotenv import load_dotenv
from i18n import t

# 設置日誌
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 配置常數
MAX_MESSAGE_LENGTH = 4000
API_TIMEOUT = 10
MAX_RETRIES = 3
RETRY_DELAY = 1.0
RETRY_BACKOFF = 2.0


def send_telegram_message(session_name: str, message: str) -> bool:
    """
    Send a message to Telegram via Bot API

    Args:
        session_name: 會話名稱
        message: 要發送的訊息

    Returns:
        bool: 是否成功
    """
    # Load environment variables
    load_dotenv()

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    allowed_users = os.getenv('ALLOWED_USER_IDS', '')

    if not bot_token:
        logger.error(t('notification.token_not_found'))
        return False

    # Get the first allowed user ID as the default chat ID
    chat_ids = [uid.strip() for uid in allowed_users.split(',') if uid.strip()]

    if not chat_ids:
        logger.error(t('notification.no_user_ids'))
        return False

    # Truncate message if too long (Telegram limit is 4096)
    truncated_message = message
    if len(message) > MAX_MESSAGE_LENGTH:
        truncated_message = message[:MAX_MESSAGE_LENGTH] + "\n\n" + t('notification.message_truncated')

    # Send to all allowed users
    success = True
    for chat_id in chat_ids:
        if not send_to_chat(bot_token, chat_id, truncated_message):
            success = False

    return success


def send_to_chat(bot_token: str, chat_id: str, message: str) -> bool:
    """
    發送訊息到指定 chat

    Args:
        bot_token: Bot token
        chat_id: Chat ID
        message: 訊息內容

    Returns:
        bool: 是否成功
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        numeric_chat_id = int(chat_id)
    except ValueError:
        logger.error(t('notification.invalid_chat_id', chat_id=chat_id))
        return False

    payload = {
        'chat_id': numeric_chat_id,
        'text': message,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True
    }

    # 重試機制
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(url, json=payload, timeout=API_TIMEOUT)

            if response.ok:
                logger.info(f"Successfully sent message to chat {chat_id}")
                return True

            # API 返回錯誤
            error_data = response.json() if response.text else {}
            error_code = error_data.get('error_code', response.status_code)
            error_description = error_data.get('description', response.text)

            # 處理特定錯誤
            if error_code == 429:  # Too Many Requests
                retry_after = error_data.get('parameters', {}).get('retry_after', 5)
                logger.warning(f"Rate limited, waiting {retry_after}s before retry")
                time.sleep(retry_after)
                continue

            if error_code == 400 and 'parse entities' in error_description.lower():
                # Markdown 解析失敗，fallback 為純文字重發
                logger.warning(t('notification.markdown_fallback'))
                payload_plain = dict(payload)
                del payload_plain['parse_mode']
                try:
                    resp = requests.post(url, json=payload_plain, timeout=API_TIMEOUT)
                    if resp.ok:
                        logger.info(f"Successfully sent plain text message to chat {chat_id}")
                        return True
                    logger.error(f"Plain text fallback also failed: {resp.status_code}")
                except Exception as e:
                    logger.error(f"Plain text fallback error: {e}")
                return False

            if error_code in [400, 401, 403, 404]:
                # 不可重試的錯誤
                logger.error(f"Non-retryable error ({error_code}): {error_description}")
                return False

            # 其他錯誤，可重試
            last_error = f"API error ({error_code}): {error_description}"
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {last_error}")

        except Timeout:
            last_error = "Request timeout"
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES}: {last_error}")

        except ReqConnectionError as e:
            last_error = f"Connection error: {e}"
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES}: {last_error}")

        except RequestException as e:
            last_error = f"Request error: {e}"
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES}: {last_error}")

        except Exception as e:
            last_error = f"Unexpected error: {e}"
            logger.error(f"Attempt {attempt + 1}/{MAX_RETRIES}: {last_error}")

        # 計算退避延遲
        if attempt < MAX_RETRIES - 1:
            delay = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
            logger.info(f"Retrying in {delay:.1f}s...")
            time.sleep(delay)

    # 所有重試都失敗
    logger.error(f"All {MAX_RETRIES} attempts failed for chat {chat_id}. Last error: {last_error}")
    return False


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: send_telegram_notification.py <session_name> <message>", file=sys.stderr)
        sys.exit(1)

    session_name = sys.argv[1]
    message = sys.argv[2]

    success = send_telegram_message(session_name, message)
    sys.exit(0 if success else 1)
