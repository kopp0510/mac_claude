#!/bin/bash
# Claude Code Telegram Bridge - 統一管理工具
# 用法: ./bridge.sh {start|stop|restart|status|logs|validate}

set -euo pipefail

# === 路徑常數 ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRIDGE_DIR="${HOME}/.claude_bridge"
LOG_DIR="${BRIDGE_DIR}/logs"
PID_FILE="${BRIDGE_DIR}/bridge.pid"
BOT_LOG="${LOG_DIR}/bot.log"
VENV_DIR="${SCRIPT_DIR}/venv"

# === 顏色輸出 ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}✅${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; }
step()  { echo -e "${BLUE}▶${NC} $1"; }

# === 初始化目錄 ===
init_dirs() {
    mkdir -p "$LOG_DIR"
}

# === PID 管理 ===
get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    fi
}

is_running() {
    local pid
    pid=$(get_pid)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    return 1
}

# === 配置驗證 ===
do_validate() {
    echo "🔍 驗證配置..."
    echo ""

    local errors=0

    # 優先使用 venv 的 Python（有依賴）
    local PYTHON="python3"
    if [ -x "$VENV_DIR/bin/python3" ]; then
        PYTHON="$VENV_DIR/bin/python3"
    fi

    # 1. .env 存在
    if [ -f "$SCRIPT_DIR/.env" ]; then
        info ".env 文件存在"

        # 檢查 TELEGRAM_BOT_TOKEN
        local token
        token=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$SCRIPT_DIR/.env" | cut -d= -f2- | tr -d '"' | tr -d "'")
        if [ -z "$token" ] || [ "$token" = "your_bot_token_here" ]; then
            error "TELEGRAM_BOT_TOKEN 未設置或為佔位符"
            errors=$((errors + 1))
        else
            info "TELEGRAM_BOT_TOKEN 已設置"
        fi
    else
        error ".env 文件不存在（請執行: cp .env.example .env）"
        errors=$((errors + 1))
    fi

    # 2. sessions.yaml 存在且有效
    if [ -f "$SCRIPT_DIR/sessions.yaml" ]; then
        info "sessions.yaml 存在"

        # 檢查是否有配置的會話
        local session_count
        session_count=$($PYTHON -c "
import yaml, sys
try:
    with open('$SCRIPT_DIR/sessions.yaml') as f:
        c = yaml.safe_load(f)
    sessions = c.get('sessions', []) if c else []
    print(len(sessions))
except Exception as e:
    print(f'ERROR:{e}', file=sys.stderr)
    print(0)
" 2>/dev/null)

        if [ "$session_count" -gt 0 ] 2>/dev/null; then
            info "找到 ${session_count} 個會話配置"
        else
            error "sessions.yaml 中沒有有效的會話配置"
            errors=$((errors + 1))
        fi

        # 檢查每個會話路徑是否存在
        local path_results
        path_results=$($PYTHON -c "
import yaml
with open('$SCRIPT_DIR/sessions.yaml') as f:
    c = yaml.safe_load(f)
import os
for s in (c.get('sessions', []) if c else []):
    name = s.get('name', '?')
    path = s.get('path', '')
    if os.path.isdir(path):
        print(f'OK:{name}:{path}')
    else:
        print(f'FAIL:{name}:{path}')
" 2>/dev/null)

        while IFS=: read -r status name path; do
            if [ "$status" = "OK" ]; then
                info "會話 #${name} 路徑存在: ${path}"
            else
                error "會話 #${name} 路徑不存在: ${path}"
                errors=$((errors + 1))
            fi
        done <<< "$path_results"
    else
        error "sessions.yaml 不存在（請執行: cp sessions.yaml.example sessions.yaml）"
        errors=$((errors + 1))
    fi

    # 3. tmux 已安裝
    if command -v tmux &>/dev/null; then
        info "tmux 已安裝: $(tmux -V)"
    else
        error "tmux 未安裝（請執行: brew install tmux）"
        errors=$((errors + 1))
    fi

    # 4. claude CLI 已安裝
    if command -v claude &>/dev/null; then
        info "Claude CLI 已安裝"
    else
        error "Claude CLI 未安裝"
        errors=$((errors + 1))
    fi

    # 5. 腳本權限
    if [ -x "$SCRIPT_DIR/notify_telegram.sh" ]; then
        info "notify_telegram.sh 可執行"
    else
        warn "notify_telegram.sh 不可執行（將自動修正）"
    fi

    if [ -x "$SCRIPT_DIR/send_telegram_notification.py" ]; then
        info "send_telegram_notification.py 可執行"
    else
        warn "send_telegram_notification.py 不可執行（將自動修正）"
    fi

    # 6. Python 依賴
    if [ -d "$VENV_DIR" ]; then
        info "虛擬環境存在"
        if "$VENV_DIR/bin/python3" -c "import telegram; import yaml; import requests" 2>/dev/null; then
            info "Python 依賴已安裝"
        else
            warn "Python 依賴不完整（啟動時會自動安裝）"
        fi
    else
        warn "虛擬環境不存在（啟動時會自動創建）"
    fi

    # 7. 日誌目錄
    if [ -d "$LOG_DIR" ]; then
        info "日誌目錄存在: ${LOG_DIR}"
    else
        info "日誌目錄將在啟動時創建: ${LOG_DIR}"
    fi

    echo ""
    if [ "$errors" -gt 0 ]; then
        error "發現 ${errors} 個問題，請修正後再啟動"
        return 1
    else
        info "所有檢查通過"
        return 0
    fi
}

# === 啟動 ===
do_start() {
    if is_running; then
        local pid
        pid=$(get_pid)
        warn "Bot 已在運行中 (PID: ${pid})"
        return 1
    fi

    step "驗證配置..."
    if ! do_validate; then
        return 1
    fi

    echo ""
    step "初始化環境..."
    init_dirs

    # 確保虛擬環境存在
    if [ ! -d "$VENV_DIR" ]; then
        step "創建虛擬環境..."
        python3 -m venv "$VENV_DIR"
    fi

    # 啟動虛擬環境並安裝依賴
    source "$VENV_DIR/bin/activate"
    if ! python3 -c "import telegram; import yaml; import requests" 2>/dev/null; then
        step "安裝 Python 依賴..."
        pip3 install -q -r "$SCRIPT_DIR/requirements.txt"
    fi

    # 確保腳本有執行權限
    chmod +x "$SCRIPT_DIR/notify_telegram.sh" 2>/dev/null || true
    chmod +x "$SCRIPT_DIR/send_telegram_notification.py" 2>/dev/null || true

    # 載入環境變數
    set -a
    source "$SCRIPT_DIR/.env"
    set +a

    # 後台啟動 bot
    step "啟動 Bot（後台模式）..."
    cd "$SCRIPT_DIR"
    nohup "$VENV_DIR/bin/python3" telegram_bot_multi.py >> "$BOT_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    # 等待確認啟動
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        echo ""
        info "Bot 已啟動 (PID: ${pid})"
        info "日誌: ${BOT_LOG}"
        info "使用 './bridge.sh status' 查看狀態"
        info "使用 './bridge.sh stop' 停止"
    else
        error "Bot 啟動失敗，查看日誌: ${BOT_LOG}"
        rm -f "$PID_FILE"
        tail -20 "$BOT_LOG" 2>/dev/null
        return 1
    fi
}

# === 停止 ===
do_stop() {
    if ! is_running; then
        warn "Bot 未在運行"
        # 清理可能殘留的 PID 檔案
        rm -f "$PID_FILE"
        # 仍然嘗試清理 tmux 會話
        cleanup_tmux
        return 0
    fi

    local pid
    pid=$(get_pid)

    step "停止 Bot (PID: ${pid})..."

    # 發送 SIGTERM
    kill "$pid" 2>/dev/null

    # 等待進程退出（最多 10 秒）
    local count=0
    while [ $count -lt 10 ] && kill -0 "$pid" 2>/dev/null; do
        sleep 1
        count=$((count + 1))
    done

    # 如果還沒退出，強制終止
    if kill -0 "$pid" 2>/dev/null; then
        warn "進程未回應 SIGTERM，強制終止..."
        kill -9 "$pid" 2>/dev/null
        sleep 1
    fi

    # 清理 PID 檔案
    rm -f "$PID_FILE"

    # 清理 tmux 會話
    cleanup_tmux

    info "Bot 已停止"
}

# === 獲取配置的 tmux 會話名稱列表 ===
get_configured_tmux_sessions() {
    local PYTHON="python3"
    if [ -x "$VENV_DIR/bin/python3" ]; then
        PYTHON="$VENV_DIR/bin/python3"
    fi

    if [ -f "$SCRIPT_DIR/sessions.yaml" ]; then
        $PYTHON -c "
import yaml
with open('$SCRIPT_DIR/sessions.yaml') as f:
    c = yaml.safe_load(f)
for s in (c.get('sessions', []) if c else []):
    name = s.get('name', '')
    tmux = s.get('tmux', f'claude-{name}')
    print(tmux)
" 2>/dev/null
    fi
}

# === 清理 tmux 會話 ===
cleanup_tmux() {
    local configured
    configured=$(get_configured_tmux_sessions)

    if [ -z "$configured" ]; then
        return
    fi

    step "清理 tmux 會話..."
    while IFS= read -r session; do
        if tmux has-session -t "$session" 2>/dev/null; then
            tmux kill-session -t "$session" 2>/dev/null && \
                info "已終止: ${session}" || true
        fi
    done <<< "$configured"
}

# === 重啟 ===
do_restart() {
    step "重啟 Bot..."
    do_stop
    echo ""
    sleep 1
    do_start
}

# === 狀態 ===
do_status() {
    echo "📊 Claude Bridge 狀態"
    echo ""

    # Bot 進程狀態
    if is_running; then
        local pid
        pid=$(get_pid)
        info "Bot 運行中 (PID: ${pid})"

        # 顯示運行時間
        local uptime
        uptime=$(ps -o etime= -p "$pid" 2>/dev/null | xargs)
        if [ -n "$uptime" ]; then
            echo "   運行時間: ${uptime}"
        fi
    else
        error "Bot 未運行"
    fi

    echo ""

    # tmux 會話狀態
    echo "🖥️  tmux 會話:"
    local configured has_active=false
    configured=$(get_configured_tmux_sessions)
    if [ -n "$configured" ]; then
        while IFS= read -r session; do
            if tmux has-session -t "$session" 2>/dev/null; then
                echo "   ✅ ${session}（運行中）"
                has_active=true
            else
                echo "   ❌ ${session}（未啟動）"
            fi
        done <<< "$configured"
    fi
    if [ "$has_active" = false ]; then
        echo "   （無活躍的會話）"
    fi

    echo ""

    # 日誌文件
    echo "📁 日誌文件:"
    if [ -d "$LOG_DIR" ]; then
        local log_files
        log_files=$(ls -la "$LOG_DIR"/*.log 2>/dev/null || true)
        if [ -n "$log_files" ]; then
            while IFS= read -r line; do
                echo "   ${line}"
            done <<< "$log_files"
        else
            echo "   （無日誌文件）"
        fi
    else
        echo "   （日誌目錄不存在）"
    fi
}

# === 日誌 ===
do_logs() {
    local session="${1:-}"

    if [ -z "$session" ]; then
        # 查看 bot 主日誌
        if [ -f "$BOT_LOG" ]; then
            step "查看 Bot 日誌: ${BOT_LOG}"
            tail -f "$BOT_LOG"
        else
            error "Bot 日誌不存在: ${BOT_LOG}"
        fi
    else
        # 查看指定會話日誌
        session="${session#\#}" # 移除可能的 # 前綴
        local session_log="${LOG_DIR}/claude_${session}.log"
        if [ -f "$session_log" ]; then
            step "查看會話日誌: ${session_log}"
            tail -f "$session_log"
        else
            error "會話日誌不存在: ${session_log}"
            echo "可用的日誌:"
            ls "$LOG_DIR"/claude_*.log 2>/dev/null || echo "  （無）"
        fi
    fi
}

# === 使用說明 ===
usage() {
    echo "Claude Code Telegram Bridge 管理工具"
    echo ""
    echo "用法: $(basename "$0") <命令> [參數]"
    echo ""
    echo "命令:"
    echo "  start       後台啟動 Bot"
    echo "  stop        停止 Bot 並清理 tmux 會話"
    echo "  restart     重啟 Bot"
    echo "  status      查看運行狀態"
    echo "  logs [會話] 查看日誌（預設為 Bot 日誌）"
    echo "  validate    驗證配置"
    echo ""
    echo "範例:"
    echo "  $(basename "$0") start"
    echo "  $(basename "$0") logs lottery_api"
    echo "  $(basename "$0") status"
}

# === 主程式 ===
main() {
    local command="${1:-}"
    shift || true

    case "$command" in
        start)    do_start ;;
        stop)     do_stop ;;
        restart)  do_restart ;;
        status)   do_status ;;
        logs)     do_logs "$@" ;;
        validate) do_validate ;;
        *)        usage ;;
    esac
}

main "$@"
