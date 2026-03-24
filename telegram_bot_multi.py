#!/usr/bin/env python3
"""
Telegram Bot - Claude Code 多會話並行橋接
支援同時管理多個 Claude Code 實例
透過 Hook 機制即時接收 Claude 回應
"""

import os
import sys
import signal
import logging
import queue
import time
import threading
import yaml
from dataclasses import dataclass, field
from typing import Optional
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from collections import defaultdict
from session_manager import SessionManager
from message_router import MessageRouter
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


def check_rate_limit(user_id: int) -> bool:
    """檢查用戶是否超過速率限制"""
    now = time.time()
    timestamps = _rate_limit_store[user_id]
    _rate_limit_store[user_id] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limit_store[user_id]) >= RATE_LIMIT_MAX:
        return False
    _rate_limit_store[user_id].append(now)
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /start 命令"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    bot_state.telegram_chat_id = update.effective_chat.id

    sessions_list = bot_state.message_router.format_session_list() if bot_state.message_router else "尚未初始化"

    welcome_message = f"""🤖 Claude Code 多會話橋接 Bot

{sessions_list}

可用命令：
/start - 顯示此幫助訊息
/status - 查看所有會話狀態
/sessions - 查看會話列表
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
        if info.get('claude_args'):
            lines.append(f"   參數: {info['claude_args']}")
        lines.append(f"   狀態: {'運行中' if info['exists'] else '未啟動'}")
        lines.append(f"   通知: Hook 驅動\n")

    await update.message.reply_text('\n'.join(lines))


async def sessions_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看會話列表"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    sessions_text = bot_state.message_router.format_session_list() if bot_state.message_router else "❌ 系統未初始化"
    await update.message.reply_text(sessions_text)


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

    if not check_rate_limit(update.effective_user.id):
        await update.message.reply_text("⏳ 發送過於頻繁，請稍後再試")
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

    # 將訊息放入佇列
    for session_name, actual_message in routes:
        try:
            bot_state.message_queue.put_nowait((session_name, actual_message))
        except queue.Full:
            await update.message.reply_text("⚠️ 訊息佇列已滿，請稍後再試")
            return

    # 發送確認
    if len(routes) == 1:
        confirm_text = f"✅ 已發送給 #{routes[0][0]}"
    else:
        confirm_text = f"✅ 已發送給 {len(routes)} 個會話"

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
    if not data.startswith('choice_'):
        return

    payload = data[7:]  # 移除 'choice_'
    parts = payload.rsplit(':', 1)  # 從右邊分割一次
    if len(parts) != 2:
        return

    session_name, choice = parts

    try:
        bot_state.message_queue.put_nowait((session_name, choice))
    except queue.Full:
        await query.edit_message_text(
            text=f"{query.message.text}\n\n⚠️ 佇列已滿，請稍後再試",
            reply_markup=None
        )
        return

    await query.edit_message_text(
        text=f"{query.message.text}\n\n✅ [#{session_name}] 已選擇: {choice}",
        reply_markup=None
    )


def message_queue_processor():
    """處理訊息佇列（Telegram → Claude）"""
    while True:
        try:
            item = bot_state.message_queue.get(timeout=app_config.queue.QUEUE_TIMEOUT)
            session_name, message = item

            logger.info(f"[#{session_name}] 處理訊息: {message[:50]}...")

            # 發送到對應會話
            bot_state.session_manager.send_to_session(session_name, message)

            time.sleep(app_config.tmux.COMMAND_DELAY)

        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"處理佇列訊息時錯誤: {e}")


def load_sessions_config():
    """載入會話配置"""
    session_manager = SessionManager()

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
            claude_args = session.get('claude_args', '')

            session_manager.add_session(name, path, tmux, claude_args)

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
    """熱重載會話配置"""
    try:
        with open(SESSIONS_CONFIG_FILE, 'r', encoding='utf-8') as f:
            new_config = yaml.safe_load(f)

        if not new_config or 'sessions' not in new_config:
            return False, f"配置文件格式錯誤: {SESSIONS_CONFIG_FILE}", {}

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

        logger.info(f"🔄 重載配置: 新增 {len(added)}, 移除 {len(removed)}, 保留 {len(kept)}")

        # 終止被移除會話的 tmux
        for name in removed:
            logger.info(f"  停止會話: {name}")
            bot_state.session_manager.kill_session(name)

        # 創建新的 SessionManager
        new_manager = SessionManager()

        for session in new_config['sessions']:
            name = session['name']
            path = session['path']
            tmux = session.get('tmux')
            claude_args = session.get('claude_args', '')

            new_manager.add_session(name, path, tmux, claude_args)

            # 新增的會話，創建 tmux 會話
            if name in added:
                logger.info(f"  新增會話: {name}")
                bridge = new_manager.get_bridge(name)
                if not bridge.session_exists():
                    bridge.create_session(work_dir=path,
                                          session_alias=name,
                                          claude_args=claude_args)

        # 更新全域狀態
        bot_state.update_session_manager(new_manager)
        bot_state.update_message_router(MessageRouter(new_manager))

        message = f"✅ 配置已重載\n新增: {len(added)}\n移除: {len(removed)}\n保留: {len(kept)}"
        return True, message, changes

    except FileNotFoundError:
        return False, f"找不到配置文件: {SESSIONS_CONFIG_FILE}", {}
    except Exception as e:
        logger.error(f"❌ 重載配置失敗: {e}")
        return False, f"重載失敗: {str(e)}", {}


def setup_bridge():
    """設置橋接"""
    logger.info("🔧 設置橋接...")

    # 載入配置
    load_sessions_config()

    # 創建所有 tmux 會話
    if not bot_state.session_manager.create_all_sessions():
        logger.error("❌ 創建會話失敗")
        sys.exit(1)

    # 啟動訊息佇列處理執行緒
    queue_thread = threading.Thread(target=message_queue_processor, daemon=True)
    queue_thread.start()

    logger.info("✅ 橋接設置完成（Hook 驅動通知）")


def main():
    """主程式"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ 請設置 TELEGRAM_BOT_TOKEN 環境變數")
        sys.exit(1)

    if not ALLOWED_USER_IDS:
        logger.critical("❌ ALLOWED_USER_IDS 未設定，拒絕啟動（安全防護：防止任何人控制 bot）")
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

    # 註冊按鈕回調處理器
    bot_state.telegram_app.add_handler(CallbackQueryHandler(button_callback))

    # 註冊訊息處理器
    bot_state.telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 啟動 Bot
    logger.info("🚀 Telegram Bot 已啟動")
    logger.info(f"📝 配置文件: {SESSIONS_CONFIG_FILE}")
    logger.info(f"🖥️  會話數量: {len(bot_state.session_manager.get_all_sessions())}")
    logger.info("📡 通知方式: Hook 驅動（即時）")

    # 設置 signal handler（支援後台優雅停止）
    def shutdown_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"🛑 收到 {sig_name}，正在關閉...")
        logger.info("👋 已關閉")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    try:
        bot_state.telegram_app.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("\n🛑 正在關閉...")
        logger.info("👋 已關閉")


if __name__ == '__main__':
    main()
