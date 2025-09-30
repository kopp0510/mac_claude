#!/bin/bash
# Claude Code Telegram 多會話橋接啟動腳本

echo "🚀 啟動 Claude Code Telegram 多會話橋接..."

# 獲取腳本所在目錄
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 檢查 .env 文件
if [ ! -f .env ]; then
    echo "❌ 找不到 .env 文件"
    echo "💡 請複製 .env.example 並填入配置："
    echo "   cp .env.example .env"
    exit 1
fi

# 檢查 sessions.yaml 配置文件
if [ ! -f sessions.yaml ]; then
    echo "❌ 找不到 sessions.yaml 配置文件"
    echo "💡 請創建 sessions.yaml 並配置你的會話"
    exit 1
fi

# 載入環境變數
export $(grep -v '^#' .env | xargs)

# 檢查必要的環境變數
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "❌ TELEGRAM_BOT_TOKEN 未設置"
    exit 1
fi

# 檢查 tmux 是否安裝
if ! command -v tmux &> /dev/null; then
    echo "❌ tmux 未安裝"
    echo "💡 請執行: brew install tmux"
    exit 1
fi

# 檢查 claude 是否安裝
if ! command -v claude &> /dev/null; then
    echo "❌ Claude Code CLI 未安裝"
    echo "💡 請參考: https://docs.claude.com/claude-code"
    exit 1
fi

# 檢查並創建虛擬環境
if [ ! -d "venv" ]; then
    echo "📦 創建虛擬環境..."
    python3 -m venv venv
fi

# 啟動虛擬環境
echo "🔧 啟動虛擬環境..."
source venv/bin/activate

# 檢查並安裝 Python 依賴
if ! python3 -c "import telegram; import yaml" 2>/dev/null; then
    echo "📦 安裝 Python 依賴..."
    pip3 install -r requirements.txt
fi

echo "✅ 環境檢查通過"
echo ""

# 啟動 Telegram Bot（多會話版本）
echo "🤖 啟動多會話 Telegram Bot..."
python3 telegram_bot_multi.py