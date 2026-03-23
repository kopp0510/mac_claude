#!/bin/bash

# Hook script for Claude Code to send notifications to Telegram
# This script is called by Claude Code's Stop hook when Claude finishes responding
# Environment variables:
#   - TELEGRAM_SESSION_NAME: Session name for routing
#   - TELEGRAM_BOT_TOKEN: Bot token from .env
#   - TELEGRAM_CHAT_ID: User's chat ID from .env

set -euo pipefail

# Read hook input from stdin (contains session_id, transcript_path, etc.)
INPUT=$(cat)

# 獲取腳本目錄
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 日誌目錄（使用更安全的位置）
LOG_DIR="${HOME}/.claude_bridge/logs"
mkdir -p "$LOG_DIR"

# Debug logging
DEBUG_LOG="${LOG_DIR}/hook_debug_${TELEGRAM_SESSION_NAME:-unknown}.log"

log_debug() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$DEBUG_LOG"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >> "$DEBUG_LOG"
    echo "Error: $1" >&2
}

log_debug "Hook triggered"
log_debug "Input: $INPUT"

# Load environment variables
if [ -f "$SCRIPT_DIR/.env" ]; then
    # 安全地載入 .env（避免注入）
    while IFS='=' read -r key value; do
        # 跳過註解和空行
        [[ -z "$key" || "$key" =~ ^# ]] && continue
        # 移除引號
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        # 只導出已知的變數
        case "$key" in
            TELEGRAM_BOT_TOKEN|ALLOWED_USER_IDS)
                export "$key=$value"
                ;;
        esac
    done < "$SCRIPT_DIR/.env"
fi

# Validate required variables
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    log_error "Missing TELEGRAM_BOT_TOKEN"
    exit 1
fi

if [ -z "${TELEGRAM_SESSION_NAME:-}" ]; then
    log_error "Missing TELEGRAM_SESSION_NAME"
    exit 1
fi

# Extract transcript path from JSON input with validation
TRANSCRIPT_PATH=$(echo "$INPUT" | python3 -c "
import sys
import json

try:
    data = json.load(sys.stdin)
    path = data.get('transcript_path', '')
    # 驗證路徑格式
    if path and path.endswith('.json') and '/' in path:
        print(path)
except Exception as e:
    print('', file=sys.stderr)
" 2>/dev/null)

# 驗證 transcript 路徑
if [ -z "$TRANSCRIPT_PATH" ]; then
    log_error "Cannot extract transcript path from input"
    exit 1
fi

if [ ! -f "$TRANSCRIPT_PATH" ]; then
    log_error "Transcript file not found: $TRANSCRIPT_PATH"
    exit 1
fi

# 驗證路徑是否在預期目錄內（防止路徑遍歷攻擊）
REAL_PATH=$(realpath "$TRANSCRIPT_PATH" 2>/dev/null || echo "")
if [[ ! "$REAL_PATH" =~ ^/.*/.claude/transcripts/.*\.json$ ]]; then
    log_error "Invalid transcript path: $TRANSCRIPT_PATH"
    exit 1
fi

log_debug "Transcript path: $TRANSCRIPT_PATH"

# Extract the last assistant message from transcript
# The transcript is a JSON file with a messages array
LAST_MESSAGE=$(python3 << 'PYTHON_SCRIPT'
import sys
import json
import os

transcript_path = os.environ.get('TRANSCRIPT_PATH_FOR_PYTHON', '')

try:
    with open(transcript_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    messages = data.get('messages', [])

    # Collect recent assistant messages (since last user message)
    assistant_messages = []
    for msg in reversed(messages):
        if msg.get('role') == 'user':
            break  # Stop at the last user message
        if msg.get('role') == 'assistant':
            assistant_messages.insert(0, msg)  # Insert at beginning to maintain order

    if not assistant_messages:
        sys.exit(0)

    # Combine all assistant message parts
    all_parts = []

    for msg in assistant_messages:
        content = msg.get('content', [])

        # Process content in order, preserving text and tool_use sequence
        for c in content:
            if c.get('type') == 'text':
                text = c.get('text', '').strip()
                if not text:
                    continue

                # Filter out confirmation prompt UI elements
                lines = text.split('\n')
                filtered_lines = []
                in_box = False

                for line in lines:
                    # Detect confirmation box (starts with box chars)
                    if any(char in line for char in ['╭', '╰', '│']):
                        in_box = True
                        continue

                    # Skip confirmation prompt patterns
                    if 'Do you want to proceed?' in line:
                        in_box = True
                        continue

                    if in_box and line.strip().startswith(('❯', '1.', '2.', '3.')):
                        continue

                    # Tool output indicators (⎿) are kept for context
                    if '⎿' in line:
                        filtered_lines.append(line)
                        continue

                    # Add non-box content
                    if not in_box:
                        filtered_lines.append(line)
                    else:
                        # Exit box mode when we hit real content
                        if line.strip() and not line.strip().startswith('│'):
                            in_box = False
                            filtered_lines.append(line)

                cleaned_text = '\n'.join(filtered_lines).strip()

                # Keep text blocks even if short
                if cleaned_text and len(cleaned_text) > 0:
                    all_parts.append(cleaned_text)

            elif c.get('type') == 'tool_use':
                # Add tool context for better understanding
                tool_name = c.get('name', 'Unknown')
                tool_input = c.get('input', {})

                if tool_name == 'Read':
                    all_parts.append(f"📖 Reading: {tool_input.get('file_path', 'file')}")
                elif tool_name == 'Write':
                    all_parts.append(f"✍️ Writing: {tool_input.get('file_path', 'file')}")
                elif tool_name == 'Edit':
                    all_parts.append(f"✏️ Editing: {tool_input.get('file_path', 'file')}")
                elif tool_name == 'Bash':
                    cmd = tool_input.get('command', '')[:100]
                    desc = tool_input.get('description', '')
                    if desc:
                        all_parts.append(f"⚙️ {desc}\n   `{cmd}`")
                    else:
                        all_parts.append(f"⚙️ Running: `{cmd}`")
                elif tool_name == 'Glob':
                    all_parts.append(f"🔍 Searching: {tool_input.get('pattern', '*')}")
                elif tool_name == 'Grep':
                    all_parts.append(f"🔍 Grepping: {tool_input.get('pattern', '')}")

    if all_parts:
        combined = '\n\n'.join(all_parts)
        print(combined)
    else:
        print('[No content extracted]', file=sys.stderr)

except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
PYTHON_SCRIPT
)

# 設置環境變數供 Python 腳本使用
export TRANSCRIPT_PATH_FOR_PYTHON="$TRANSCRIPT_PATH"

# Re-run with the environment variable set
LAST_MESSAGE=$(TRANSCRIPT_PATH_FOR_PYTHON="$TRANSCRIPT_PATH" python3 << 'PYTHON_SCRIPT'
import sys
import json
import os

transcript_path = os.environ.get('TRANSCRIPT_PATH_FOR_PYTHON', '')

try:
    with open(transcript_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    messages = data.get('messages', [])

    # Collect recent assistant messages (since last user message)
    assistant_messages = []
    for msg in reversed(messages):
        if msg.get('role') == 'user':
            break
        if msg.get('role') == 'assistant':
            assistant_messages.insert(0, msg)

    if not assistant_messages:
        sys.exit(0)

    all_parts = []

    for msg in assistant_messages:
        content = msg.get('content', [])

        for c in content:
            if c.get('type') == 'text':
                text = c.get('text', '').strip()
                if not text:
                    continue

                lines = text.split('\n')
                filtered_lines = []
                in_box = False

                for line in lines:
                    if any(char in line for char in ['╭', '╰', '│']):
                        in_box = True
                        continue

                    if 'Do you want to proceed?' in line:
                        in_box = True
                        continue

                    if in_box and line.strip().startswith(('❯', '1.', '2.', '3.')):
                        continue

                    if '⎿' in line:
                        filtered_lines.append(line)
                        continue

                    if not in_box:
                        filtered_lines.append(line)
                    else:
                        if line.strip() and not line.strip().startswith('│'):
                            in_box = False
                            filtered_lines.append(line)

                cleaned_text = '\n'.join(filtered_lines).strip()
                if cleaned_text:
                    all_parts.append(cleaned_text)

            elif c.get('type') == 'tool_use':
                tool_name = c.get('name', 'Unknown')
                tool_input = c.get('input', {})

                if tool_name == 'Read':
                    all_parts.append(f"📖 Reading: {tool_input.get('file_path', 'file')}")
                elif tool_name == 'Write':
                    all_parts.append(f"✍️ Writing: {tool_input.get('file_path', 'file')}")
                elif tool_name == 'Edit':
                    all_parts.append(f"✏️ Editing: {tool_input.get('file_path', 'file')}")
                elif tool_name == 'Bash':
                    cmd = tool_input.get('command', '')[:100]
                    desc = tool_input.get('description', '')
                    if desc:
                        all_parts.append(f"⚙️ {desc}\n   `{cmd}`")
                    else:
                        all_parts.append(f"⚙️ Running: `{cmd}`")
                elif tool_name == 'Glob':
                    all_parts.append(f"🔍 Searching: {tool_input.get('pattern', '*')}")
                elif tool_name == 'Grep':
                    all_parts.append(f"🔍 Grepping: {tool_input.get('pattern', '')}")

    if all_parts:
        print('\n\n'.join(all_parts))

except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
PYTHON_SCRIPT
)

# Log extraction result
log_debug "Extracted message length: ${#LAST_MESSAGE}"
log_debug "Message preview: ${LAST_MESSAGE:0:100}"

if [ -z "$LAST_MESSAGE" ]; then
    log_debug "No message to send, exiting quietly"
    exit 0
fi

# Format message with session name
SESSION_HEADER="📍 *${TELEGRAM_SESSION_NAME}*"
FORMATTED_MESSAGE="${SESSION_HEADER}

${LAST_MESSAGE}"

# Send to Telegram using the shared notification endpoint
log_debug "Sending to Telegram..."
if python3 "$SCRIPT_DIR/send_telegram_notification.py" "$TELEGRAM_SESSION_NAME" "$FORMATTED_MESSAGE"; then
    log_debug "Successfully sent to Telegram"
else
    log_error "Failed to send to Telegram"
    exit 1
fi

exit 0
