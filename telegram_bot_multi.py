#!/usr/bin/env python3
"""
Telegram Bot - AI CLI 多會話並行橋接
支援同時管理多個 AI CLI 實例（Claude Code、Gemini CLI）
透過 Hook 機制即時接收 AI 回應
"""

import json
import os
import re
import subprocess
import sys
import signal
import logging
import queue
import time
import threading
from pathlib import Path
import yaml
from dataclasses import dataclass, field
from typing import Optional
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from collections import defaultdict
from datetime import datetime
from session_manager import SessionManager
from message_router import MessageRouter
import hashlib
from config import config as app_config, patterns
from i18n import t

# 載入環境變數
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 設置日誌
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 關閉 httpx 日誌
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)


@dataclass
class BotState:
    """Bot 狀態管理類"""
    session_manager: Optional[SessionManager] = None
    message_router: Optional[MessageRouter] = None
    telegram_app: Optional[Application] = None
    telegram_chat_id: Optional[int] = None

    # 訊息佇列（Telegram → Claude）
    message_queue: queue.Queue = field(
        default_factory=lambda: queue.Queue(maxsize=app_config.queue.MESSAGE_QUEUE_SIZE)
    )

    # 執行緒鎖，用於保護狀態更新
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def update_session_manager(self, manager: SessionManager) -> None:
        """執行緒安全地更新 session_manager"""
        with self._lock:
            self.session_manager = manager

    def update_message_router(self, router: MessageRouter) -> None:
        """執行緒安全地更新 message_router"""
        with self._lock:
            self.message_router = router

    def update_manager_and_router(self, manager: SessionManager, router: MessageRouter) -> None:
        """原子更新 session_manager 和 message_router"""
        with self._lock:
            self.session_manager = manager
            self.message_router = router


# 全域狀態實例
bot_state = BotState()

# 從環境變數讀取配置
TELEGRAM_BOT_TOKEN = app_config.bot_token
ALLOWED_USER_IDS = app_config.allowed_user_ids
SESSIONS_CONFIG_FILE = app_config.sessions_config_file


def check_user_permission(update: Update) -> bool:
    """檢查用戶是否有權限"""
    if not ALLOWED_USER_IDS:
        return True
    user_id = str(update.effective_user.id)
    return user_id in ALLOWED_USER_IDS


# 速率限制：每用戶每 5 秒最多 3 則訊息
RATE_LIMIT_WINDOW = 5
RATE_LIMIT_MAX = 3
_rate_limit_store: dict = defaultdict(list)
_rate_limit_lock = threading.Lock()


def check_rate_limit(user_id: int) -> bool:
    """檢查用戶是否超過速率限制"""
    now = time.time()
    with _rate_limit_lock:
        timestamps = _rate_limit_store[user_id]
        _rate_limit_store[user_id] = [ts for ts in timestamps if now - ts < RATE_LIMIT_WINDOW]
        if len(_rate_limit_store[user_id]) >= RATE_LIMIT_MAX:
            return False
        _rate_limit_store[user_id].append(now)
        return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /start 命令"""
    if not check_user_permission(update):
        await update.message.reply_text(t('bot.unauthorized'))
        return

    bot_state.telegram_chat_id = update.effective_chat.id

    sessions_list = bot_state.message_router.format_session_list() if bot_state.message_router else t('start_cmd.not_initialized')

    welcome_message = f"""{t('start_cmd.title')}

{sessions_list}

{t('start_cmd.commands_header')}
{t('start_cmd.cmd_start')}
{t('start_cmd.cmd_status')}
{t('start_cmd.cmd_sessions')}
{t('start_cmd.cmd_restart')}
{t('start_cmd.cmd_reload')}
{t('chain.cmd_chain')}
"""

    await update.message.reply_text(welcome_message)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看所有會話狀態"""
    if not check_user_permission(update):
        await update.message.reply_text(t('bot.unauthorized'))
        return

    status_info = bot_state.session_manager.get_status()

    lines = [t('status_cmd.title') + "\n"]
    for name, info in status_info.items():
        status_emoji = "✅" if info['exists'] else "❌"
        lines.append(f"{status_emoji} #{name}")
        lines.append(f"   {t('status_cmd.path')}: {info['path']}")
        lines.append(f"   tmux: {info['tmux_session']}")
        lines.append(f"   CLI: {info.get('cli_type', 'claude')}")
        if info.get('cli_args'):
            lines.append(f"   {t('status_cmd.args')}: {info['cli_args']}")
        lines.append(f"   {t('status_cmd.state')}: {t('status_cmd.running') if info['exists'] else t('status_cmd.stopped')}")
        busy_seconds = _get_session_busy_seconds(name)
        if busy_seconds >= 0:
            lines.append(f"   {t('status_cmd.busy', seconds=busy_seconds)}")
        else:
            lines.append(f"   {t('status_cmd.idle')}")
        lines.append(f"   {t('status_cmd.notification')}: {t('status_cmd.hook_driven')}\n")

    await update.message.reply_text('\n'.join(lines))


async def sessions_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看會話列表"""
    if not check_user_permission(update):
        await update.message.reply_text(t('bot.unauthorized'))
        return

    sessions_text = bot_state.message_router.format_session_list() if bot_state.message_router else t('session.not_initialized')
    await update.message.reply_text(sessions_text)


async def restart_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """重啟指定會話"""
    if not check_user_permission(update):
        await update.message.reply_text(t('bot.unauthorized'))
        return

    if not context.args:
        await update.message.reply_text(t('session.specify_name'))
        return

    session_name = context.args[0].replace('#', '').replace('@', '')

    if not patterns.is_safe_session_name(session_name) or not bot_state.session_manager.get_session(session_name):
        await update.message.reply_text(t('session.not_found', name=session_name))
        return

    await update.message.reply_text(t('session.restarting', name=session_name))

    # 重啟會話
    success = bot_state.session_manager.restart_session(session_name)

    if success:
        await update.message.reply_text(t('session.restart_success', name=session_name))
    else:
        await update.message.reply_text(t('session.restart_failure', name=session_name))


async def reload_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """重新載入配置文件"""
    if not check_user_permission(update):
        await update.message.reply_text(t('bot.unauthorized'))
        return

    await update.message.reply_text(t('reload.reloading'))

    # 執行重載
    success, message, changes = reload_sessions_config()

    if success:
        # 格式化變更詳情
        details = []
        if changes.get('added'):
            details.append(t('reload.added_label', sessions=', '.join(['#' + s for s in changes['added']])))
        if changes.get('removed'):
            details.append(t('reload.removed_label', sessions=', '.join(['#' + s for s in changes['removed']])))
        if changes.get('kept'):
            details.append(t('reload.kept_label', sessions=', '.join(['#' + s for s in changes['kept']])))

        full_message = message
        if details:
            full_message += "\n\n" + "\n".join(details)

        await update.message.reply_text(full_message)
    else:
        await update.message.reply_text(f"❌ {message}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理用戶訊息"""
    if not check_user_permission(update):
        await update.message.reply_text(t('bot.unauthorized'))
        return

    if not check_rate_limit(update.effective_user.id):
        await update.message.reply_text(t('bot.rate_limited'))
        return

    bot_state.telegram_chat_id = update.effective_chat.id

    user_message = update.message.text

    # 驗證訊息長度
    if len(user_message) > app_config.security.MAX_MESSAGE_LENGTH:
        await update.message.reply_text(t('bot.message_too_long', max_length=app_config.security.MAX_MESSAGE_LENGTH))
        return

    # 偵測串接語法：#session msg >> #session2 prefix
    if patterns.CHAIN_DETECT.search(user_message):
        await _handle_chain_message(update, user_message)
        return

    # 路由訊息
    routes = bot_state.message_router.parse_message(user_message)

    # 檢查錯誤
    if routes and routes[0][0] == '__error__':
        await update.message.reply_text(f"❌ {routes[0][1]}")
        return

    # 將訊息放入佇列
    for session_name, actual_message in routes:
        try:
            bot_state.message_queue.put_nowait((session_name, actual_message))
        except queue.Full:
            await update.message.reply_text(t('bot.queue_full'))
            return

    # 發送確認
    if len(routes) == 1:
        confirm_text = t('session.sent_single', name=routes[0][0])
    else:
        confirm_text = t('session.sent_multiple', count=len(routes))

    await update.message.reply_text(confirm_text)


async def _handle_chain_message(update: Update, user_message: str):
    """處理串接語法：#session1 msg >> #session2 prefix >> ..."""
    segments = patterns.CHAIN_SPLIT.split(user_message)

    # 第一段必須是 #session message 格式
    first_routes = bot_state.message_router.parse_message(segments[0].strip())
    if not first_routes or first_routes[0][0] == '__error__':
        error_msg = first_routes[0][1] if first_routes else t('chain.invalid_syntax', segment=segments[0].strip())
        await update.message.reply_text(f"❌ {error_msg}")
        return

    source_session = first_routes[0][0]
    source_message = first_routes[0][1]

    # 檢查串接深度限制（segments 包含起始 + 後續，總步數 = len(segments)）
    max_depth = app_config.chain.MAX_CHAIN_DEPTH
    if len(segments) > max_depth:
        await update.message.reply_text(t('chain.too_deep', max_depth=max_depth))
        return

    # 解析後續串接目標（含循環偵測）
    chain_steps = []
    seen_sessions = {source_session}
    for seg in segments[1:]:
        seg = seg.strip()
        match = patterns.CHAIN_TARGET.match(seg)
        if not match:
            await update.message.reply_text(t('chain.invalid_syntax', segment=seg))
            return
        target_name = match.group(1)
        # 循環偵測：同一 session 不可出現兩次
        if target_name in seen_sessions:
            await update.message.reply_text(t('chain.cycle_detected', name=target_name))
            return
        seen_sessions.add(target_name)
        prefix = (match.group(2) or '').strip()
        session_config = bot_state.session_manager.get_session(target_name)
        if not session_config:
            await update.message.reply_text(t('chain.invalid_target', name=target_name))
            return
        chain_steps.append((target_name, prefix, session_config))

    # 寫入 chain 檔
    all_names = [source_session] + [name for name, _, _ in chain_steps]
    try:
        _write_chain_file(source_session, chain_steps, all_names)
    except (OSError, ValueError) as e:
        logger.error(f"Failed to write chain file: {e}")
        await update.message.reply_text(f"❌ {e}")
        return

    # 串接提示放最前面（A 的回應會寫入檔案給 B 讀取，不需嚴格字元限制）
    source_message = t('chain.length_hint', max_chars=app_config.telegram.MAX_SEND_LENGTH).strip() + "\n\n" + source_message

    # 將第一段訊息放入佇列
    try:
        bot_state.message_queue.put_nowait((source_session, source_message))
    except queue.Full:
        await update.message.reply_text(t('bot.queue_full'))
        return

    # 發送確認
    chain_desc = " >> ".join([f"#{name}" for name, _, _ in chain_steps])
    await update.message.reply_text(t('chain.setup_success', source=source_session, chain=chain_desc))


def _write_chain_file(source_session: str, chain_steps: list, chain_path: list):
    """寫入串接配置檔"""

    # 驗證所有 session 名稱安全性（防 path traversal）
    for name in chain_path:
        if not patterns.is_safe_session_name(name):
            raise ValueError(f"Unsafe session name: {name}")

    chain_dir = app_config.chain.CHAIN_DIR
    os.makedirs(chain_dir, mode=0o700, exist_ok=True)

    # 從後往前建構巢狀結構
    chain_data = None
    for target_name, prefix, session_config in reversed(chain_steps):
        chain_data = {
            "target_session": target_name,
            "target_tmux": session_config.tmux_session,
            "target_cli_type": session_config.cli_type,
            "target_path": session_config.path,
            "prompt_prefix": prefix,
            "next_chain": chain_data,
            "chain_path": chain_path,
            "created_at": datetime.now().isoformat(),
        }

    chain_file = os.path.join(chain_dir, f"{source_session}.json")
    fd = os.open(chain_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(chain_data, f, ensure_ascii=False, indent=2)


async def chain_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看或取消活躍的串接"""
    if not check_user_permission(update):
        await update.message.reply_text(t('bot.unauthorized'))
        return

    chain_dir = app_config.chain.CHAIN_DIR

    # /chain cancel #session
    if context.args and len(context.args) >= 2 and context.args[0] == 'cancel':
        session_name = context.args[1].replace('#', '')
        if not patterns.is_safe_session_name(session_name):
            await update.message.reply_text(t('session.not_found', name=session_name))
            return
        chain_file = os.path.join(chain_dir, f"{session_name}.json")
        if os.path.exists(chain_file):
            os.remove(chain_file)
            await update.message.reply_text(t('chain.cancelled', source=session_name))
        else:
            await update.message.reply_text(t('chain.not_found', source=session_name))
        return

    # /chain — 列出活躍的串接
    if not os.path.exists(chain_dir):
        await update.message.reply_text(t('chain.no_active'))
        return

    lines = []
    for f_name in os.listdir(chain_dir):
        if not f_name.endswith('.json'):
            continue
        source = f_name[:-5]  # 移除 .json
        try:
            with open(os.path.join(chain_dir, f_name), 'r', encoding='utf-8') as f:
                chain = json.load(f)
            target = chain.get('target_session', '?')
            task = chain.get('prompt_prefix', '') or '-'
            lines.append(t('chain.status_entry', source=source, target=target, task=task))
        except (json.JSONDecodeError, OSError):
            continue

    if lines:
        text = t('chain.status_title') + "\n" + "\n".join(lines)
    else:
        text = t('chain.no_active')

    await update.message.reply_text(text)


def _parse_callback_data(data: str, prefix: str) -> tuple:
    """解析 callback_data，移除前綴後拆分為 (session_name, value)

    Returns:
        (session_name, value) 或 (None, None) 若格式不正確
    """
    payload = data[len(prefix):]
    parts = payload.rsplit(':', 1)
    if len(parts) != 2:
        return None, None
    return parts[0], parts[1]


def _send_tmux_selection(session_name: str, choice_num: str) -> None:
    """透過 tmux 按鍵序列選擇指定選項（Down × N-1 次 + Enter）"""
    bridge = bot_state.session_manager.get_bridge(session_name) if bot_state.session_manager else None
    if not bridge or not bridge.session_exists():
        return

    try:
        num = int(choice_num)
        session_config = bot_state.session_manager.get_session(session_name)
        if not session_config:
            return
        tmux_session = session_config.tmux_session
        for _ in range(num - 1):
            result = subprocess.run(
                ['tmux', 'send-keys', '-t', tmux_session, 'Down'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                logger.warning(f"tmux send-keys Down failed: {result.stderr}")
                return
            time.sleep(0.1)
        result = subprocess.run(
            ['tmux', 'send-keys', '-t', tmux_session, 'Enter'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            logger.warning(f"tmux send-keys Enter failed: {result.stderr}")
    except Exception as e:
        logger.warning(f"Failed to send selection keys: {e}")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 Inline Keyboard 按鈕點擊"""
    query = update.callback_query
    await query.answer()

    user_id = str(update.effective_user.id)
    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        await query.edit_message_text(t('bot.unauthorized'))
        return

    data = query.data

    # 文字輸入選項：input_{session}:{num}（選擇後提示使用者追加訊息）
    if data.startswith('input_'):
        session_name, choice_num = _parse_callback_data(data, 'input_')
        if not session_name:
            return

        _send_tmux_selection(session_name, choice_num)
        _poll_last_sent[session_name] = time.time()

        await query.edit_message_text(
            text=f"{query.message.text}\n\n✏️ {t('callback.text_input_hint', session=session_name)}",
            reply_markup=None
        )
        return

    # 互動輪詢選項：select_{session}:{num}（用 tmux 按鍵序列選擇）
    if data.startswith('select_'):
        session_name, choice_num = _parse_callback_data(data, 'select_')
        if not session_name:
            return

        _send_tmux_selection(session_name, choice_num)
        _poll_last_sent[session_name] = time.time()

        await query.edit_message_text(
            text=f"{query.message.text}\n\n{t('callback.selected', session=session_name, choice=choice_num)}",
            reply_markup=None
        )
        return

    # 一般確認選項：choice_{session}:{num}（文字發送到佇列）
    if not data.startswith('choice_'):
        return

    session_name, choice = _parse_callback_data(data, 'choice_')
    if not session_name:
        return

    try:
        bot_state.message_queue.put_nowait((session_name, choice))
    except queue.Full:
        await query.edit_message_text(
            text=f"{query.message.text}\n\n{t('callback.queue_full')}",
            reply_markup=None
        )
        return

    _poll_last_sent[session_name] = time.time()

    await query.edit_message_text(
        text=f"{query.message.text}\n\n{t('callback.selected', session=session_name, choice=choice)}",
        reply_markup=None
    )


def _mark_session_busy(session_name: str) -> None:
    """標記 session 為忙碌狀態"""
    if not patterns.is_safe_session_name(session_name):
        return
    status_dir = app_config.status.STATUS_DIR
    os.makedirs(status_dir, mode=0o700, exist_ok=True)
    busy_file = os.path.join(status_dir, f"{session_name}.busy")
    try:
        fd = os.open(busy_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(datetime.now().isoformat())
    except OSError as e:
        logger.warning(f"Failed to mark session busy: {e}")


BUSY_TIMEOUT_SECONDS = 3600  # busy 狀態超過 1 小時自動清除

def _get_session_busy_seconds(session_name: str) -> int:
    """取得 session 忙碌秒數，未忙碌返回 -1。超過 BUSY_TIMEOUT_SECONDS 自動清除。"""
    busy_file = os.path.join(app_config.status.STATUS_DIR, f"{session_name}.busy")
    try:
        with open(busy_file, 'r', encoding='utf-8') as f:
            start_time = datetime.fromisoformat(f.read().strip())
        seconds = int((datetime.now() - start_time).total_seconds())
        if seconds > BUSY_TIMEOUT_SECONDS:
            try:
                os.remove(busy_file)
            except OSError:
                pass
            return -1
        return seconds
    except (FileNotFoundError, ValueError, OSError):
        return -1


def message_queue_processor():
    """處理訊息佇列（Telegram → Claude）"""
    while True:
        try:
            item = bot_state.message_queue.get(timeout=app_config.queue.QUEUE_TIMEOUT)
            session_name, message = item

            logger.info(t('bridge.queue_processing', session=session_name, preview=message[:50]))

            # 發送到對應會話
            bot_state.session_manager.send_to_session(session_name, message)
            _mark_session_busy(session_name)

            time.sleep(app_config.tmux.COMMAND_DELAY)

        except queue.Empty:
            continue
        except Exception as e:
            logger.error(t('bridge.queue_error', error=e))


def load_sessions_config():
    """載入會話配置"""
    session_manager = SessionManager()

    try:
        with open(SESSIONS_CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        if not config or 'sessions' not in config:
            logger.error(t('bridge.config_error', file=SESSIONS_CONFIG_FILE))
            sys.exit(1)

        for session in config['sessions']:
            name = session['name']
            path = session['path']
            tmux = session.get('tmux')
            cli_type = session.get('cli_type', 'claude')
            cli_args = session.get('cli_args', session.get('claude_args', ''))

            session_manager.add_session(name, path, tmux, cli_args, cli_type)

        logger.info(t('bridge.config_loaded', count=len(config['sessions'])))

    except FileNotFoundError:
        logger.error(t('bridge.config_not_found', file=SESSIONS_CONFIG_FILE))
        sys.exit(1)
    except Exception as e:
        logger.error(t('bridge.config_load_failed', error=e))
        sys.exit(1)

    # 原子更新全域狀態
    bot_state.update_manager_and_router(session_manager, MessageRouter(session_manager))


def reload_sessions_config():
    """熱重載會話配置"""
    try:
        with open(SESSIONS_CONFIG_FILE, 'r', encoding='utf-8') as f:
            new_config = yaml.safe_load(f)

        if not new_config or 'sessions' not in new_config:
            return False, t('bridge.config_format_error', file=SESSIONS_CONFIG_FILE), {}

        old_sessions = set(bot_state.session_manager.get_all_sessions())
        new_sessions_config = {s['name']: s for s in new_config['sessions']}
        new_sessions = set(new_sessions_config.keys())

        added = new_sessions - old_sessions
        removed = old_sessions - new_sessions
        kept = old_sessions & new_sessions

        changes = {
            'added': list(added),
            'removed': list(removed),
            'kept': list(kept)
        }

        logger.info(t('reload.log_summary', added=len(added), removed=len(removed), kept=len(kept)))

        # 終止被移除會話的 tmux
        for name in removed:
            logger.info(t('reload.stop_session', name=name))
            bot_state.session_manager.kill_session(name)

        # 創建新的 SessionManager
        new_manager = SessionManager()

        for session in new_config['sessions']:
            name = session['name']
            path = session['path']
            tmux = session.get('tmux')
            cli_type = session.get('cli_type', 'claude')
            cli_args = session.get('cli_args', session.get('claude_args', ''))

            new_manager.add_session(name, path, tmux, cli_args, cli_type)

            # 新增的會話，創建 tmux 會話
            if name in added:
                logger.info(t('reload.add_session', name=name))
                bridge = new_manager.get_bridge(name)
                if not bridge.session_exists():
                    bridge.create_session(work_dir=path,
                                          session_alias=name,
                                          cli_args=cli_args)

        # 原子更新全域狀態
        bot_state.update_manager_and_router(new_manager, MessageRouter(new_manager))

        message = t('reload.success', added=len(added), removed=len(removed), kept=len(kept))
        return True, message, changes

    except FileNotFoundError:
        return False, t('reload.file_not_found', file=SESSIONS_CONFIG_FILE), {}
    except Exception as e:
        logger.error(t('bridge.reload_config_error', error=e))
        return False, t('reload.failed', error=str(e)), {}


def log_rotation_worker():
    """定時檢查日誌大小，超過閾值截斷保留最後部分"""
    while True:
        time.sleep(app_config.tmux.LOG_CHECK_INTERVAL)
        try:
            log_dir = Path(app_config.tmux.LOG_DIR)
            if not log_dir.exists():
                continue
            for log_file in log_dir.glob("*.log"):
                try:
                    if log_file.stat().st_size > app_config.tmux.LOG_MAX_SIZE:
                        data = log_file.read_bytes()[-app_config.tmux.LOG_KEEP_SIZE:]
                        log_file.write_bytes(data)
                        logger.info(t('bridge.log_truncated', name=log_file.name))
                except Exception as e:
                    logger.debug(f"Log rotation error for {log_file}: {e}")
        except Exception as e:
            logger.debug(f"Log rotation scan error: {e}")


# 互動偵測輪詢狀態
_poll_lock = threading.Lock()
_poll_sent_hashes: dict = {}    # {hash: True}，保持插入順序做 LRU 淘汰
_POLL_HASH_MAX_SIZE = 1000      # hash 集合上限，防記憶體洩漏
_poll_last_sent: dict = {}  # {session_name: timestamp}，防短時間重複
POLL_COOLDOWN = 30  # 同一 session 發送冷卻時間（秒）

# 文字輸入選項的關鍵字（選擇後需要使用者追加輸入）
TEXT_INPUT_KEYWORDS = ['Type something', 'Tell Claude what to change',
                       'tell Codex what to do differently']


def _capture_tmux_pane(session_name: str) -> str:
    """用 tmux capture-pane 取得渲染後的螢幕內容（適用於 ink/React TUI）"""
    try:
        result = subprocess.run(
            ['tmux', 'capture-pane', '-t', session_name, '-p', '-S', '-50'],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout if result.returncode == 0 else ''
    except Exception:
        return ''


def _clean_ansi(text: str) -> str:
    """清理 ANSI escape codes 和控制字元"""
    # 先把 cursor forward \x1b[NC] 替換為空格（TUI 用它代替空格）
    text = re.sub(r'\x1b\[(\d+)C', lambda m: ' ' * int(m.group(1)), text)
    text = patterns.ANSI_ESCAPE.sub('', text)
    text = patterns.CONTROL_CHARS.sub('', text)
    return text


_OPTION_EXTRACTORS = {
    'gemini': lambda text: _extract_options_gemini(text),
    'codex': lambda text: _extract_options_codex(text),
}


def _extract_options(text: str, cli_type: str = 'claude') -> tuple:
    """從清理後的文字提取標題和選項行，根據 CLI 類型分派邏輯

    Returns:
        (title, options) — title 為提問文字，options 為 [(num, label), ...]
    """
    return _OPTION_EXTRACTORS.get(cli_type, _extract_options_claude)(text)


def _is_border_line(line: str) -> bool:
    """判斷是否為分隔線（╌ 或 ─ 連續 10 個以上）"""
    stripped = line.strip()
    return ('╌' in stripped or
            (stripped.startswith('─') and len(stripped) > 10))


def _extract_options_claude(text: str) -> tuple:
    """Claude Code 格式：分隔線後 + ❯ 標記選項"""
    lines = text.split('\n')

    # 找最後一條分隔線（╌ 或 ─），只在其後搜尋選項
    last_border_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if _is_border_line(lines[i]):
            last_border_idx = i
            break

    # 沒有分隔線 → 退回用 ❯ 標記直接搜尋（從尾部往前找 ❯ 行）
    if last_border_idx < 0:
        # 從尾部找 ❯ 所在行，往前擴展選項區塊
        marker_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            if '❯' in lines[i]:
                marker_idx = i
                break
        if marker_idx < 0:
            return "", []
        search_start = max(0, marker_idx - 10)
    else:
        search_start = last_border_idx + 1

    options = []
    first_option_idx = None
    has_marker = False

    for i in range(search_start, len(lines)):
        line_stripped = lines[i].strip()
        if not line_stripped:
            continue
        match = patterns.CONFIRMATION_OPTION.match(line_stripped)
        if match:
            num, label = match.group(1), match.group(2).strip()
            if len(num) <= 2:
                if first_option_idx is None:
                    first_option_idx = i
                if '❯' in lines[i]:
                    has_marker = True
                options.append((num, label))

    # 沒有 ❯ 標記的編號列表不是互動選項
    if not has_marker:
        return "", []

    # 標題：分隔線後、選項前的文字
    title = ""
    if first_option_idx is not None:
        title_lines = []
        border_count = 0
        for i in range(first_option_idx - 1, max(first_option_idx - 60, -1), -1):
            if i < 0:
                break
            line = lines[i].strip()
            if not line:
                continue
            if _is_border_line(lines[i]):
                break
            title_lines.insert(0, line)
        title = '\n'.join(title_lines)
        if len(title) > 3000:
            title = title[-3000:]

    return title, options


def _extract_options_gemini(text: str) -> tuple:
    """Gemini CLI 格式：╭╰ 框框包裹，│ 邊線，● 標記當前選項"""
    lines = text.split('\n')

    # 找最後一個 ╰ 結束行（框框底部）
    box_end = -1
    for i in range(len(lines) - 1, -1, -1):
        if '╰' in lines[i]:
            box_end = i
            break

    if box_end < 0:
        return "", []

    # 找對應的 ╭ 開始行
    box_start = -1
    for i in range(box_end - 1, -1, -1):
        if '╭' in lines[i]:
            box_start = i
            break

    if box_start < 0:
        return "", []

    # 在框框內搜尋選項（移除 │ 邊線後匹配）
    options = []
    title_lines = []
    first_option_idx = None

    for i in range(box_start + 1, box_end):
        line = lines[i]
        # 移除 │ 邊線
        cleaned_line = line.replace('│', '').strip()
        if not cleaned_line:
            continue

        match = patterns.GEMINI_OPTION.match(cleaned_line)
        if match:
            num, label = match.group(1), match.group(2).strip()
            if len(num) <= 2:
                if first_option_idx is None:
                    first_option_idx = i
                options.append((num, label))
        elif first_option_idx is None:
            # 選項之前的內容作為標題
            title_lines.append(cleaned_line)

    title = '\n'.join(title_lines)
    if len(title) > 3000:
        title = title[-3000:]

    return title, options


def _extract_options_codex(text: str) -> tuple:
    """Codex CLI 格式：› 標記當前選項，純編號列表

    Codex 使用 ink/React TUI，需透過 tmux capture-pane 取得渲染後文字。
    格式範例：
        › 1. Yes, proceed (y)
          2. Yes, and don't ask again for ... (p)
          3. No, and tell Codex what to do differently (esc)
    """
    lines = text.split('\n')

    # Codex 選項模式：可選的 › 前綴 + 編號
    codex_option_re = re.compile(r'^\s*[›]?\s*(\d+)\.\s*(.+)')

    # 從尾部往前掃描找到選項區塊
    options = []
    first_option_idx = None
    last_option_idx = None
    has_marker = False  # 至少一個選項要有 › 標記

    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        match = codex_option_re.match(line)
        if match:
            num, label = match.group(1), match.group(2).strip()
            if len(num) <= 2:
                if last_option_idx is None:
                    last_option_idx = i
                first_option_idx = i
                if '›' in lines[i]:
                    has_marker = True
                options.insert(0, (num, label))
        elif last_option_idx is not None:
            # 遇到非選項行且已找到選項，選項區塊結束
            break

    # 沒有 › 標記的編號列表不是互動選項
    if not options or not has_marker:
        return "", []

    # 標題：選項區塊之前的內容（往前最多 30 行）
    title_lines = []
    for i in range(first_option_idx - 1, max(first_option_idx - 30, -1), -1):
        if i < 0:
            break
        line = lines[i].strip()
        if not line:
            continue
        # 遇到分隔線或 › 提示行（非選項的輸入行）停止
        if line.startswith('─') and len(line) > 10:
            break
        if line.startswith('›') and not codex_option_re.match(line):
            break
        title_lines.insert(0, line)

    title = '\n'.join(title_lines)
    if len(title) > 3000:
        title = title[-3000:]

    return title, options


def interaction_polling_worker():
    """輪詢 tmux 輸出，偵測互動選項並推送到 Telegram"""
    while True:
        time.sleep(app_config.tmux.POLL_INTERVAL)
        try:
            if not bot_state.session_manager or not bot_state.telegram_chat_id:
                continue

            for name in bot_state.session_manager.get_all_sessions():
                config = bot_state.session_manager.get_session(name)
                if not config:
                    continue

                cli_type = config.cli_type if config else 'claude'

                # Codex ink/React TUI 用游標定位重繪，日誌無法解析
                # 改用 tmux capture-pane 取得渲染後畫面
                if cli_type == 'codex':
                    bridge = bot_state.session_manager.get_bridge(name)
                    if not bridge or not bridge.session_exists():
                        continue
                    cleaned = _capture_tmux_pane(bridge.session_name)
                else:
                    log_file = config.log_file
                    if not os.path.exists(log_file):
                        continue

                    # 讀取日誌尾部（最後 5000 字元，足以包含選項區塊）
                    try:
                        file_size = os.path.getsize(log_file)
                        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                            f.seek(max(0, file_size - 5000))
                            new_content = f.read()
                    except Exception:
                        continue

                    if not new_content:
                        continue

                    # 清理 ANSI
                    cleaned = _clean_ansi(new_content)
                title, options = _extract_options(cleaned, cli_type)

                if len(options) < 2:
                    continue

                # 防重複：冷卻時間 + hash（加鎖保護）
                now = time.time()
                with _poll_lock:
                    last_sent = _poll_last_sent.get(name, 0)
                    if now - last_sent < POLL_COOLDOWN:
                        continue

                    options_text = '|'.join(f"{n}.{l}" for n, l in options)
                    options_hash = hashlib.md5(options_text.encode()).hexdigest()
                    if options_hash in _poll_sent_hashes:
                        continue
                    # 限界：超過上限時刪除最舊的一半（dict 保持插入順序）
                    if len(_poll_sent_hashes) >= _POLL_HASH_MAX_SIZE:
                        keys = list(_poll_sent_hashes.keys())
                        for k in keys[:len(keys) // 2]:
                            del _poll_sent_hashes[k]
                    _poll_sent_hashes[options_hash] = True
                    _poll_last_sent[name] = now

                # 組合標題（Telegram API 限制 4096 字元）
                header_parts = [f"📋 [#{name}]"]
                if title:
                    header_parts.append(title)
                header = '\n'.join(header_parts)
                if len(header) > 4000:
                    header = header[:4000] + "\n\n⋯"

                # 組合 InlineKeyboard 並用 requests 直接呼叫 Telegram API
                # （輪詢執行緒無法使用 async，故用同步 requests）
                try:
                    import requests as req
                    inline_keyboard = []
                    for num, label in options:
                        is_text_input = any(kw.lower() in label.lower() for kw in TEXT_INPUT_KEYWORDS)
                        prefix = "input_" if is_text_input else "select_"
                        btn_label = f"✏️ {num}. {label}" if is_text_input else f"{num}. {label}"
                        inline_keyboard.append([{"text": btn_label, "callback_data": f"{prefix}{name}:{num}"}])
                    payload = {
                        "chat_id": bot_state.telegram_chat_id,
                        "text": header,
                        "reply_markup": json.dumps({"inline_keyboard": inline_keyboard})
                    }
                    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    resp = req.post(url, json=payload, timeout=10)
                    if resp.ok:
                        logger.info(f"Sent interaction buttons for #{name}")
                    else:
                        logger.warning(f"Failed to send buttons: {resp.text}")
                except Exception as e:
                    logger.warning(f"Failed to send interaction buttons: {e}")

        except Exception as e:
            logger.error(f"Interaction polling error: {e}")


def setup_bridge():
    """設置橋接"""
    logger.info(t('bridge.setup'))

    # 載入配置
    load_sessions_config()

    # 創建所有 tmux 會話
    if not bot_state.session_manager.create_all_sessions():
        logger.error(t('bridge.create_failed'))
        sys.exit(1)

    # 啟動訊息佇列處理執行緒
    queue_thread = threading.Thread(target=message_queue_processor, daemon=True)
    queue_thread.start()

    # 啟動日誌輪替執行緒
    rotation_thread = threading.Thread(target=log_rotation_worker, daemon=True)
    rotation_thread.start()

    # 啟動互動偵測輪詢執行緒
    polling_thread = threading.Thread(target=interaction_polling_worker, daemon=True)
    polling_thread.start()

    logger.info(t('bridge.setup_complete'))


def main():
    """主程式"""
    import i18n
    i18n.init()

    if not TELEGRAM_BOT_TOKEN:
        logger.error(t('bot.missing_token'))
        sys.exit(1)

    if not ALLOWED_USER_IDS:
        logger.critical(t('bot.missing_user_ids'))
        sys.exit(1)

    # 設置橋接
    setup_bridge()

    # 創建 Telegram Application
    bot_state.telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 註冊命令處理器
    bot_state.telegram_app.add_handler(CommandHandler("start", start))
    bot_state.telegram_app.add_handler(CommandHandler("status", status))
    bot_state.telegram_app.add_handler(CommandHandler("sessions", sessions_list))
    bot_state.telegram_app.add_handler(CommandHandler("restart", restart_session))
    bot_state.telegram_app.add_handler(CommandHandler("reload", reload_config))
    bot_state.telegram_app.add_handler(CommandHandler("chain", chain_command))

    # 註冊按鈕回調處理器
    bot_state.telegram_app.add_handler(CallbackQueryHandler(button_callback))

    # 註冊訊息處理器
    bot_state.telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 啟動 Bot
    logger.info(t('bot.started'))
    logger.info(t('bot.config_file', file=SESSIONS_CONFIG_FILE))
    logger.info(t('bot.session_count', count=len(bot_state.session_manager.get_all_sessions())))
    logger.info(t('bot.notification_mode'))

    # 設置 signal handler（支援後台優雅停止）
    def shutdown_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(t('bot.shutdown_signal', signal=sig_name))
        logger.info(t('bot.shutdown_complete'))
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    try:
        bot_state.telegram_app.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info(t('bot.shutting_down'))
        logger.info(t('bot.shutdown_complete'))


if __name__ == '__main__':
    main()
