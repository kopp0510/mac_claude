#!/usr/bin/env python3
"""
Telegram Bot - Claude Code 多會話並行橋接
支援同時管理多個 Claude Code 實例
"""

import os
import sys
import logging
import asyncio
import queue
import threading
import yaml
from io import BytesIO
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from session_manager import SessionManager
from message_router import MessageRouter
from multi_session_monitor import MultiSessionMonitor
from output_monitor import MessageFormatter
from config import config as app_config

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
    """Bot 狀態管理類，替代全域變數"""
    session_manager: Optional[SessionManager] = None
    message_router: Optional[MessageRouter] = None
    multi_monitor: Optional[MultiSessionMonitor] = None
    telegram_app: Optional[Application] = None
    telegram_chat_id: Optional[int] = None

    # 使用有大小限制的佇列
    message_queue: queue.Queue = field(
        default_factory=lambda: queue.Queue(maxsize=app_config.queue.MESSAGE_QUEUE_SIZE)
    )
    output_queue: queue.Queue = field(
        default_factory=lambda: queue.Queue(maxsize=app_config.queue.OUTPUT_QUEUE_SIZE)
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /start 命令"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    bot_state.telegram_chat_id = update.effective_chat.id

    sessions_list = bot_state.message_router.format_session_list() if bot_state.message_router else "尚未初始化"

    welcome_message = f"""
🤖 Claude Code 多會話橋接 Bot

{sessions_list}

可用命令：
/start - 顯示此幫助訊息
/status - 查看所有會話狀態
/sessions - 查看會話列表
/buffer #session - 獲取指定會話的緩衝區內容
/clear #session - 清空指定會話的緩衝區
/restart #session - 重啟指定會話
/reload - 重新載入 sessions.yaml 配置
"""

    await update.message.reply_text(welcome_message)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看所有會話狀態"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    status_info = bot_state.session_manager.get_status()

    lines = ["📊 會話狀態\n"]
    for name, info in status_info.items():
        status_emoji = "✅" if info['exists'] else "❌"
        lines.append(f"{status_emoji} #{name}")
        lines.append(f"   路徑: {info['path']}")
        lines.append(f"   tmux: {info['tmux_session']}")
        lines.append(f"   狀態: {'運行中' if info['exists'] else '未啟動'}\n")

    await update.message.reply_text('\n'.join(lines))


async def sessions_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看會話列表"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    sessions_text = bot_state.message_router.format_session_list() if bot_state.message_router else "❌ 系統未初始化"
    await update.message.reply_text(sessions_text)


async def get_buffer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """獲取指定會話的緩衝區內容"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    # 解析參數
    if not context.args:
        await update.message.reply_text("❌ 請指定會話名稱，例如: /buffer #rental")
        return

    session_name = context.args[0].replace('#', '').replace('@', '')
    buffer_content = bot_state.multi_monitor.get_buffer(session_name)

    if not buffer_content:
        await update.message.reply_text(f"📭 #{session_name} 緩衝區為空")
        return

    messages = MessageFormatter.format_for_telegram(buffer_content)
    for msg in messages:
        if isinstance(msg, dict) and msg.get('type') == 'file':
            await update.message.reply_document(
                document=BytesIO(msg['content'].encode('utf-8')),
                filename=msg['filename']
            )
        else:
            await update.message.reply_text(f"[#{session_name}]\n{msg}")


async def clear_buffer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清空指定會話的緩衝區"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    if not context.args:
        await update.message.reply_text("❌ 請指定會話名稱，例如: /clear #rental")
        return

    session_name = context.args[0].replace('#', '').replace('@', '')
    bot_state.multi_monitor.clear_buffer(session_name)
    await update.message.reply_text(f"🗑️ #{session_name} 緩衝區已清空")


async def restart_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """重啟指定會話"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    if not context.args:
        await update.message.reply_text("❌ 請指定會話名稱，例如: /restart #rental")
        return

    session_name = context.args[0].replace('#', '').replace('@', '')

    # 檢查會話是否存在
    if not bot_state.session_manager.get_session(session_name):
        await update.message.reply_text(f"❌ 會話不存在: #{session_name}")
        return

    await update.message.reply_text(f"🔄 正在重啟會話 #{session_name}...")

    # 重啟會話
    success = bot_state.session_manager.restart_session(session_name)

    if success:
        # 清空緩衝區
        bot_state.multi_monitor.clear_buffer(session_name)
        await update.message.reply_text(f"✅ #{session_name} 已成功重啟")
    else:
        await update.message.reply_text(f"❌ #{session_name} 重啟失敗，請查看日誌")


async def reload_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """重新載入配置文件"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    await update.message.reply_text("🔄 正在重載配置...")

    # 執行重載
    success, message, changes = reload_sessions_config()

    if success:
        # 格式化變更詳情
        details = []
        if changes.get('added'):
            details.append(f"➕ 新增: {', '.join(['#' + s for s in changes['added']])}")
        if changes.get('removed'):
            details.append(f"➖ 移除: {', '.join(['#' + s for s in changes['removed']])}")
        if changes.get('kept'):
            details.append(f"✅ 保留: {', '.join(['#' + s for s in changes['kept']])}")

        full_message = message
        if details:
            full_message += "\n\n" + "\n".join(details)

        await update.message.reply_text(full_message)
    else:
        await update.message.reply_text(f"❌ {message}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理用戶訊息"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    bot_state.telegram_chat_id = update.effective_chat.id

    user_message = update.message.text

    # 驗證訊息長度
    if len(user_message) > app_config.security.MAX_MESSAGE_LENGTH:
        await update.message.reply_text(f"❌ 訊息過長（最大 {app_config.security.MAX_MESSAGE_LENGTH} 字元）")
        return

    # 路由訊息
    routes = bot_state.message_router.parse_message(user_message)

    # 檢查錯誤
    if routes and routes[0][0] == '__error__':
        await update.message.reply_text(f"❌ {routes[0][1]}")
        return

    # 將訊息放入佇列（有大小限制）
    queued_count = 0
    for session_name, actual_message in routes:
        try:
            bot_state.message_queue.put_nowait((session_name, actual_message))
            queued_count += 1
        except queue.Full:
            await update.message.reply_text("⚠️ 訊息佇列已滿，請稍後再試")
            return

    # 發送確認
    target_names = [name for name, _ in routes]
    if len(target_names) == 1:
        confirm_text = f"✅ 已發送給 #{target_names[0]}"
    else:
        confirm_text = f"✅ 已發送給 {len(target_names)} 個會話"

    confirm_text += f"\n⏳ 佇列中有 {bot_state.message_queue.qsize()} 條訊息"
    await update.message.reply_text(confirm_text)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 Inline Keyboard 按鈕點擊"""
    query = update.callback_query
    await query.answer()

    user_id = str(update.effective_user.id)
    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        await query.edit_message_text("❌ 未授權的用戶")
        return

    # 解析回調數據: choice_{session}:{num}
    data = query.data
    if data.startswith('choice_'):
        # 移除 'choice_' 前綴後，用 ':' 分割 session_name 和 choice
        payload = data[7:]  # 移除 'choice_'
        parts = payload.rsplit(':', 1)  # 從右邊分割一次
        if len(parts) == 2:
            session_name = parts[0]
            choice = parts[1]

            # 發送選擇到對應會話（有大小限制）
            try:
                bot_state.message_queue.put_nowait((session_name, choice))
            except queue.Full:
                await query.edit_message_text(
                    text=f"{query.message.text}\n\n⚠️ 佇列已滿，請稍後再試",
                    reply_markup=None
                )
                return

            # 更新訊息
            await query.edit_message_text(
                text=f"{query.message.text}\n\n✅ [#{session_name}] 已選擇: {choice}",
                reply_markup=None
            )


async def send_messages_to_telegram(chat_id: int, session_name: str,
                                     messages: List[Any],
                                     confirmation: Optional[Dict] = None):
    """
    發送訊息到 Telegram

    Args:
        chat_id: 聊天 ID
        session_name: 會話名稱
        messages: 訊息列表
        confirmation: 確認提示資訊
    """
    if not bot_state.telegram_app or not chat_id:
        logger.error("Telegram app 或 chat_id 未初始化")
        return

    try:
        for msg in messages:
            if isinstance(msg, dict) and msg.get('type') == 'file':
                await bot_state.telegram_app.bot.send_document(
                    chat_id=chat_id,
                    document=BytesIO(msg['content'].encode('utf-8')),
                    filename=msg['filename'],
                    caption=f"📄 [#{session_name}] Claude Code 輸出"
                )
            else:
                # 添加來源標記
                tagged_msg = f"[#{session_name}]\n{msg}"

                reply_markup = None

                # 如果有確認提示，添加 Inline Keyboard
                if confirmation and confirmation.get('options'):
                    keyboard = []
                    for option in confirmation['options']:
                        num = option['num']
                        text = option['text']

                        if 'Yes' in text and 'allow all' in text:
                            button_text = f"✅ {num}. 允許所有編輯"
                        elif 'Yes' in text:
                            button_text = f"✅ {num}. Yes"
                        elif 'No' in text:
                            button_text = f"❌ {num}. No"
                        else:
                            button_text = f"{num}. {text[:20]}"

                        # callback_data 包含會話名稱，使用 : 作為分隔符避免與底線衝突
                        keyboard.append([InlineKeyboardButton(
                            button_text,
                            callback_data=f"choice_{session_name}:{num}"
                        )])

                    reply_markup = InlineKeyboardMarkup(keyboard)

                await bot_state.telegram_app.bot.send_message(
                    chat_id=chat_id,
                    text=tagged_msg,
                    reply_markup=reply_markup
                )

    except Exception as e:
        logger.error(f"發送訊息到 Telegram 失敗: {e}")


def on_output_complete(session_name: str, output: str):
    """
    當 Claude Code 輸出完成時的回調

    Args:
        session_name: 會話名稱
        output: 完整的輸出內容
    """
    if not bot_state.telegram_chat_id:
        logger.warning("沒有活動的 Telegram 聊天")
        return

    if not output or len(output.strip()) < app_config.monitor.MIN_RESPONSE_LENGTH:
        logger.info(f"[#{session_name}] 輸出太短，忽略")
        return

    logger.info(f"[#{session_name}] 收到完整輸出: {len(output)} 字元")

    # 檢測確認提示
    confirmation = bot_state.multi_monitor.detect_confirmation(session_name, output)

    # 格式化訊息
    messages = MessageFormatter.format_for_telegram(output)

    if messages:
        try:
            bot_state.output_queue.put_nowait({
                'chat_id': bot_state.telegram_chat_id,
                'session_name': session_name,
                'messages': messages,
                'confirmation': confirmation
            })
        except queue.Full:
            logger.warning(f"[#{session_name}] 輸出佇列已滿，訊息被丟棄")
    else:
        logger.info(f"[#{session_name}] 格式化後沒有有效訊息，忽略")


def message_queue_processor():
    """處理訊息佇列"""
    while True:
        try:
            item = bot_state.message_queue.get(timeout=app_config.queue.QUEUE_TIMEOUT)
            session_name, message = item

            logger.info(f"[#{session_name}] 處理訊息: {message[:50]}...")

            # 暫時清空該會話的緩衝區
            bot_state.multi_monitor.clear_buffer(session_name)

            # 發送到對應會話
            bot_state.session_manager.send_to_session(session_name, message)

            import time
            time.sleep(app_config.tmux.COMMAND_DELAY)

        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"處理佇列訊息時錯誤: {e}")


def load_sessions_config():
    """載入會話配置"""
    session_manager = SessionManager()

    # 載入配置文件
    try:
        with open(SESSIONS_CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        if not config or 'sessions' not in config:
            logger.error(f"❌ 配置文件格式錯誤: {SESSIONS_CONFIG_FILE}")
            sys.exit(1)

        for session in config['sessions']:
            name = session['name']
            path = session['path']
            tmux = session.get('tmux')

            session_manager.add_session(name, path, tmux)

        logger.info(f"✅ 載入 {len(config['sessions'])} 個會話配置")

    except FileNotFoundError:
        logger.error(f"❌ 找不到配置文件: {SESSIONS_CONFIG_FILE}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 載入配置失敗: {e}")
        sys.exit(1)

    # 更新全域狀態
    bot_state.update_session_manager(session_manager)
    bot_state.update_message_router(MessageRouter(session_manager))


def reload_sessions_config():
    """
    熱重載會話配置

    Returns:
        tuple: (success: bool, message: str, changes: dict)
    """
    try:
        # 載入新配置
        with open(SESSIONS_CONFIG_FILE, 'r', encoding='utf-8') as f:
            new_config = yaml.safe_load(f)

        if not new_config or 'sessions' not in new_config:
            return False, f"配置文件格式錯誤: {SESSIONS_CONFIG_FILE}", {}

        # 獲取當前會話列表
        old_sessions = set(bot_state.session_manager.get_all_sessions())
        new_sessions_config = {s['name']: s for s in new_config['sessions']}
        new_sessions = set(new_sessions_config.keys())

        # 計算變更
        added = new_sessions - old_sessions
        removed = old_sessions - new_sessions
        kept = old_sessions & new_sessions

        changes = {
            'added': list(added),
            'removed': list(removed),
            'kept': list(kept)
        }

        logger.info(f"🔄 重載配置: 新增 {len(added)}, 移除 {len(removed)}, 保留 {len(kept)}")

        # 停止被移除會話的監控
        for name in removed:
            logger.info(f"  停止會話: {name}")
            bot_state.multi_monitor.stop_monitor(name)
            bot_state.session_manager.kill_session(name)

        # 創建新的 SessionManager（保留舊會話）
        new_manager = SessionManager()

        # 添加所有新配置的會話
        for session in new_config['sessions']:
            name = session['name']
            path = session['path']
            tmux = session.get('tmux')

            new_manager.add_session(name, path, tmux)

            # 如果是新增的會話，創建 tmux 會話
            if name in added:
                logger.info(f"  新增會話: {name}")
                bridge = new_manager.get_bridge(name)
                if not bridge.session_exists():
                    bridge.create_session(work_dir=path)

        # 執行緒安全地更新全域變數
        bot_state.update_session_manager(new_manager)
        bot_state.update_message_router(MessageRouter(new_manager))

        # 為新增的會話設置監控
        for name in added:
            bot_state.multi_monitor.add_monitor(name, bot_state.session_manager, on_output_complete)

        message = f"✅ 配置已重載\n新增: {len(added)}\n移除: {len(removed)}\n保留: {len(kept)}"
        return True, message, changes

    except FileNotFoundError:
        return False, f"找不到配置文件: {SESSIONS_CONFIG_FILE}", {}
    except Exception as e:
        logger.error(f"❌ 重載配置失敗: {e}")
        return False, f"重載失敗: {str(e)}", {}


def setup_bridge():
    """設置橋接"""
    logger.info("🔧 設置多會話橋接...")

    # 載入配置
    load_sessions_config()

    # 創建所有 tmux 會話
    if not bot_state.session_manager.create_all_sessions():
        logger.error("❌ 創建會話失敗")
        sys.exit(1)

    # 初始化多會話監控器
    bot_state.multi_monitor = MultiSessionMonitor(
        bot_state.session_manager,
        idle_timeout=app_config.monitor.IDLE_TIMEOUT
    )

    # 啟動監控
    bot_state.multi_monitor.setup_monitors(callback=on_output_complete)

    # 啟動訊息佇列處理執行緒
    queue_thread = threading.Thread(target=message_queue_processor, daemon=True)
    queue_thread.start()

    logger.info("✅ 多會話橋接設置完成")


def main():
    """主程式"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ 請設置 TELEGRAM_BOT_TOKEN 環境變數")
        sys.exit(1)

    # 設置橋接
    setup_bridge()

    # 創建 Telegram Application
    bot_state.telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 註冊命令處理器
    bot_state.telegram_app.add_handler(CommandHandler("start", start))
    bot_state.telegram_app.add_handler(CommandHandler("status", status))
    bot_state.telegram_app.add_handler(CommandHandler("sessions", sessions_list))
    bot_state.telegram_app.add_handler(CommandHandler("buffer", get_buffer))
    bot_state.telegram_app.add_handler(CommandHandler("clear", clear_buffer))
    bot_state.telegram_app.add_handler(CommandHandler("restart", restart_session))
    bot_state.telegram_app.add_handler(CommandHandler("reload", reload_config))

    # 註冊按鈕回調處理器
    bot_state.telegram_app.add_handler(CallbackQueryHandler(button_callback))

    # 註冊訊息處理器
    bot_state.telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 設置輸出佇列處理器
    async def output_queue_handler(application):
        while True:
            try:
                if not bot_state.output_queue.empty():
                    item = bot_state.output_queue.get_nowait()
                    chat_id = item['chat_id']
                    session_name = item['session_name']
                    messages = item['messages']
                    confirmation = item.get('confirmation')

                    await send_messages_to_telegram(chat_id, session_name, messages, confirmation)

                await asyncio.sleep(0.1)
            except queue.Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"處理輸出佇列時錯誤: {e}")
                await asyncio.sleep(1)

    async def post_init(application):
        asyncio.create_task(output_queue_handler(application))

    bot_state.telegram_app.post_init = post_init

    # 啟動 Bot
    logger.info("🚀 Telegram Bot 已啟動（多會話模式）")
    logger.info(f"📝 配置文件: {SESSIONS_CONFIG_FILE}")
    logger.info(f"🖥️  會話數量: {len(bot_state.session_manager.get_all_sessions())}")

    try:
        bot_state.telegram_app.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("\n🛑 正在關閉...")
        bot_state.multi_monitor.stop_all()
        logger.info("👋 已關閉")


if __name__ == '__main__':
    main()
