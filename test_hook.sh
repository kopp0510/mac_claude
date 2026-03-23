#!/bin/bash

# 測試 Claude Code hook 整合
# 此腳本創建測試數據並驗證 notify_telegram.sh 能正常運行

set -e

echo "🧪 測試 Hook 整合..."
echo ""

# 1. 創建測試 transcript
TEST_DIR="/tmp/test_claude_hook"
mkdir -p "$TEST_DIR"

TEST_TRANSCRIPT="$TEST_DIR/test_transcript.json"

cat > "$TEST_TRANSCRIPT" << 'EOF'
{
  "messages": [
    {
      "role": "user",
      "content": [{"type": "text", "text": "Hello"}]
    },
    {
      "role": "assistant",
      "content": [{"type": "text", "text": "Hello! This is a test message from Claude Code hook integration."}]
    }
  ]
}
EOF

echo "✅ 創建測試 transcript: $TEST_TRANSCRIPT"
echo ""

# 2. 檢查 hook 腳本存在
if [ ! -f "./notify_telegram.sh" ]; then
    echo "❌ notify_telegram.sh 不存在"
    exit 1
fi

if [ ! -x "./notify_telegram.sh" ]; then
    echo "❌ notify_telegram.sh 不可執行"
    exit 1
fi

echo "✅ notify_telegram.sh 存在且可執行"
echo ""

# 3. 檢查 Python 腳本存在
if [ ! -f "./send_telegram_notification.py" ]; then
    echo "❌ send_telegram_notification.py 不存在"
    exit 1
fi

if [ ! -x "./send_telegram_notification.py" ]; then
    echo "❌ send_telegram_notification.py 不可執行"
    exit 1
fi

echo "✅ send_telegram_notification.py 存在且可執行"
echo ""

# 4. 檢查 .env 文件
if [ ! -f "./.env" ]; then
    echo "❌ .env 文件不存在，請創建並配置 TELEGRAM_BOT_TOKEN"
    exit 1
fi

echo "✅ .env 文件存在"
echo ""

# 5. 測試 hook 腳本（不實際發送到 Telegram，只測試腳本執行）
echo "📝 測試 hook 腳本解析..."

export TELEGRAM_SESSION_NAME="test_session"

# 模擬 Claude Code hook 輸入
HOOK_INPUT="{\"session_id\": \"test\", \"transcript_path\": \"$TEST_TRANSCRIPT\"}"

echo "輸入數據："
echo "$HOOK_INPUT" | jq .
echo ""

# 執行 hook（會實際發送到 Telegram）
echo "⚠️  注意：這將發送測試訊息到 Telegram"
echo "按 Enter 繼續，或 Ctrl+C 取消..."
read

echo "$HOOK_INPUT" | ./notify_telegram.sh

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Hook 腳本執行成功"
    echo "請檢查 Telegram 是否收到測試訊息："
    echo "📍 test_session"
    echo ""
    echo "Hello! This is a test message from Claude Code hook integration."
else
    echo ""
    echo "❌ Hook 腳本執行失敗"
    exit 1
fi

# 清理
echo ""
echo "🧹 清理測試文件..."
rm -rf "$TEST_DIR"

echo ""
echo "✅ 測試完成！"
