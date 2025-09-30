#!/usr/bin/env python3
"""
Telegram Bot - Claude Code 雙向橋接
接收 Claude Code 輸出並推送到 Telegram，同時接收 Telegram 訊息並注入到 Claude Code
"""

import os
import sys
import logging
import asyncio
import queue
import threading
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

import yaml
from session_manager import SessionManager
from message_router import MessageRouter
from multi_session_monitor import MultiSessionMonitor
from output_monitor import MessageFormatter

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

# 配置
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALLOWED_USER_IDS = [uid.strip() for uid in os.getenv('ALLOWED_USER_IDS', '').split(',') if uid.strip()]
CLAUDE_WORK_DIR = os.getenv('CLAUDE_WORK_DIR', os.getcwd())
TMUX_SESSION_NAME = os.getenv('TMUX_SESSION_NAME', 'claude')

# 全域變數
session_manager = None
message_router = None
multi_monitor = None
message_queue = queue.Queue()  # Telegram 訊息佇列
output_queue = queue.Queue()  # Claude 輸出佇列
telegram_app = None
telegram_chat_id = None  # 當前聊天的 chat_id


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

    global telegram_chat_id
    telegram_chat_id = update.effective_chat.id

    welcome_message = """
🤖 Claude Code Telegram 橋接 Bot

可用命令：
/start - 顯示此幫助訊息
/status - 查看橋接狀態
/attach - 查看如何連接到 Claude 終端
/buffer - 獲取當前緩衝區的內容
/clear - 清空緩衝區

💡 使用說明：
• 直接發送訊息，會傳送給 Claude Code
• Claude Code 的回覆會自動推送到這裡
• 你也可以直接在終端操作，不會衝突
• 訊息會排隊處理，避免衝突

📝 當前工作目錄: {work_dir}
🖥️  Tmux 會話: {session}
""".format(work_dir=CLAUDE_WORK_DIR, session=TMUX_SESSION_NAME)

    await update.message.reply_text(welcome_message)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看橋接狀態"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    bridge_status = tmux_bridge.get_status()

    status_text = f"""
📊 橋接狀態

Tmux:
  • 已安裝: {'✅' if bridge_status['tmux_installed'] else '❌'}
  • 會話存在: {'✅' if bridge_status['session_exists'] else '❌'}
  • 會話名稱: {bridge_status['session_name']}

日誌:
  • 日誌文件: {bridge_status['log_file']}
  • 文件存在: {'✅' if bridge_status['log_exists'] else '❌'}
  • 文件大小: {bridge_status['log_size']} bytes

監控:
  • 監控狀態: {'🟢 運行中' if output_monitor.is_monitoring else '🔴 已停止'}
  • 緩衝區大小: {len(output_monitor.buffer)} 字元

佇列:
  • 待處理訊息: {message_queue.qsize()} 條
"""

    await update.message.reply_text(status_text)


async def attach_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """顯示如何連接到 Claude 終端"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    info_text = f"""
🖥️  連接到 Claude 終端

在終端執行以下命令：

```
tmux attach -t {TMUX_SESSION_NAME}
```

退出 tmux 會話（不終止 Claude）：
• 按 `Ctrl+B` 然後按 `D` (detach)

終止 Claude 和會話：
• 在 Claude 中輸入 exit
• 或按 `Ctrl+C`
"""

    await update.message.reply_text(info_text)


async def get_buffer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """獲取當前緩衝區內容"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    buffer_content = output_monitor.get_current_buffer()

    if not buffer_content:
        await update.message.reply_text("📭 緩衝區為空")
        return

    # 格式化並發送
    messages = MessageFormatter.format_for_telegram(buffer_content)
    await send_messages_to_telegram(update.effective_chat.id, messages)


async def clear_buffer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清空緩衝區"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    output_monitor.buffer = ""
    await update.message.reply_text("🗑️ 緩衝區已清空")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理用戶訊息"""
    if not check_user_permission(update):
        await update.message.reply_text("❌ 未授權的用戶")
        return

    global telegram_chat_id
    telegram_chat_id = update.effective_chat.id

    user_message = update.message.text

    # 將訊息放入佇列
    message_queue.put(user_message)

    # 發送確認
    await update.message.reply_text(f"✅ 已發送給 Claude Code\n⏳ 佇列中有 {message_queue.qsize()} 條訊息")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 Inline Keyboard 按鈕點擊"""
    query = update.callback_query
    await query.answer()

    # 檢查權限
    user_id = str(update.effective_user.id)
    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        await query.edit_message_text("❌ 未授權的用戶")
        return

    # 獲取選擇
    data = query.data
    if data.startswith('choice_'):
        choice = data.replace('choice_', '')

        # 發送選擇到 Claude Code
        message_queue.put(choice)

        # 更新訊息
        await query.edit_message_text(
            text=f"{query.message.text}\n\n✅ 已選擇: {choice}",
            reply_markup=None
        )


async def send_messages_to_telegram(chat_id, messages, confirmation=None):
    """
    發送訊息到 Telegram

    Args:
        chat_id: 聊天 ID
        messages: 訊息列表或包含文件資訊的字典
        confirmation: 確認提示資訊 {'type': 類型, 'options': 選項列表}
    """
    if not telegram_app or not chat_id:
        logger.error("Telegram app 或 chat_id 未初始化")
        return

    try:
        for msg in messages:
            if isinstance(msg, dict) and msg.get('type') == 'file':
                # 發送文件
                file_content = msg['content'].encode('utf-8')
                filename = msg['filename']

                await telegram_app.bot.send_document(
                    chat_id=chat_id,
                    document=BytesIO(file_content),
                    filename=filename,
                    caption="📄 Claude Code 輸出（文件）"
                )
            else:
                # 發送文字訊息
                reply_markup = None

                # 如果有確認提示，添加 Inline Keyboard
                if confirmation and confirmation.get('options'):
                    keyboard = []
                    for option in confirmation['options']:
                        # 創建按鈕
                        num = option['num']
                        text = option['text']

                        # 簡化按鈕文字
                        if 'Yes' in text and 'allow all' in text:
                            button_text = f"✅ {num}. 允許所有編輯"
                        elif 'Yes' in text:
                            button_text = f"✅ {num}. Yes"
                        elif 'No' in text:
                            button_text = f"❌ {num}. No"
                        else:
                            button_text = f"{num}. {text[:20]}"

                        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"choice_{num}")])

                    reply_markup = InlineKeyboardMarkup(keyboard)

                await telegram_app.bot.send_message(
                    chat_id=chat_id,
                    text=msg,
                    reply_markup=reply_markup
                )

    except Exception as e:
        logger.error(f"發送訊息到 Telegram 失敗: {e}")


def on_output_complete(output):
    """
    當 Claude Code 輸出完成時的回調

    Args:
        output: 完整的輸出內容
    """
    if not telegram_chat_id:
        logger.warning("沒有活動的 Telegram 聊天")
        return

    # 過濾空內容或太短的內容
    if not output or len(output.strip()) < 10:
        logger.info("輸出太短，忽略")
        return

    logger.info(f"收到完整輸出: {len(output)} 字元")
    logger.debug(f"輸出內容預覽: {output[:100]}...")

    # 檢測確認提示
    confirmation = output_monitor.detect_confirmation_prompt(output)

    # 格式化訊息
    messages = MessageFormatter.format_for_telegram(output)

    # 確保有有效訊息才推送
    if messages:
        # 放入輸出佇列，由主執行緒處理
        output_queue.put({
            'chat_id': telegram_chat_id,
            'messages': messages,
            'confirmation': confirmation
        })
    else:
        logger.info("格式化後沒有有效訊息，忽略")


def message_queue_processor():
    """處理訊息佇列（在獨立執行緒中運行）"""
    while True:
        try:
            # 從佇列取出訊息
            message = message_queue.get(timeout=1)

            if message:
                logger.info(f"處理佇列訊息: {message[:50]}...")

                # 暫停監控，避免抓到輸入的回顯
                if output_monitor:
                    output_monitor.buffer = ""  # 清空緩衝區

                # 發送到 Claude Code
                tmux_bridge.send_command(message)

                # 等待一小段時間讓輸入被處理
                import time
                time.sleep(1)

        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"處理佇列訊息時錯誤: {e}")


def setup_bridge():
    """設置橋接"""
    global tmux_bridge, output_monitor

    logger.info("🔧 設置 tmux 橋接...")

    # 初始化 tmux 橋接
    tmux_bridge = TmuxBridge(session_name=TMUX_SESSION_NAME)

    # 檢查並創建會話
    if not tmux_bridge.session_exists():
        logger.info("📝 創建 tmux 會話...")
        success = tmux_bridge.create_session(work_dir=CLAUDE_WORK_DIR)
        if not success:
            logger.error("❌ 創建 tmux 會話失敗")
            sys.exit(1)
    else:
        logger.info("✅ tmux 會話已存在")

    # 初始化輸出監控器（增加超時時間到 8 秒，確保 Claude 完成回覆）
    output_monitor = OutputMonitor(tmux_bridge, idle_timeout=8.0)

    # 啟動監控
    output_monitor.start_monitoring(callback=on_output_complete)

    # 啟動訊息佇列處理執行緒
    queue_thread = threading.Thread(target=message_queue_processor, daemon=True)
    queue_thread.start()

    logger.info("✅ 橋接設置完成")


def main():
    """主程式"""
    global telegram_app

    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ 請設置 TELEGRAM_BOT_TOKEN 環境變數")
        sys.exit(1)

    # 設置橋接
    setup_bridge()

    # 創建 Telegram Application
    telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 註冊命令處理器
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("status", status))
    telegram_app.add_handler(CommandHandler("attach", attach_info))
    telegram_app.add_handler(CommandHandler("buffer", get_buffer))
    telegram_app.add_handler(CommandHandler("clear", clear_buffer))

    # 註冊按鈕回調處理器
    telegram_app.add_handler(CallbackQueryHandler(button_callback))

    # 註冊訊息處理器
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 設置輸出佇列處理器（定期檢查）
    async def output_queue_handler(application):
        """處理輸出佇列"""
        while True:
            try:
                if not output_queue.empty():
                    item = output_queue.get_nowait()
                    chat_id = item['chat_id']
                    messages = item['messages']
                    confirmation = item.get('confirmation')

                    await send_messages_to_telegram(chat_id, messages, confirmation)

                await asyncio.sleep(0.1)  # 每 100ms 檢查一次
            except Exception as e:
                logger.error(f"處理輸出佇列時錯誤: {e}")
                await asyncio.sleep(1)

    # 註冊 post_init 回調來啟動輸出佇列處理
    async def post_init(application):
        asyncio.create_task(output_queue_handler(application))

    telegram_app.post_init = post_init

    # 啟動 Bot
    logger.info("🚀 Telegram Bot 已啟動")
    logger.info(f"📝 工作目錄: {CLAUDE_WORK_DIR}")
    logger.info(f"🖥️  Tmux 會話: {TMUX_SESSION_NAME}")

    try:
        telegram_app.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("\n🛑 正在關閉...")
        output_monitor.stop_monitoring()
        logger.info("👋 已關閉")


if __name__ == '__main__':
    main()