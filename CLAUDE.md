# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

一個透過 tmux 橋接多個 Claude Code 實例的 Telegram Bot，實現透過 Telegram 訊息遠端控制和雙向通訊 Claude Code 會話。

## 開發命令

### 執行 Bot

```bash
# 推薦：使用統一管理工具（後台運行，含配置驗證）
./bridge.sh start          # 後台啟動
./bridge.sh stop           # 優雅停止（含清理 tmux）
./bridge.sh restart        # 重啟
./bridge.sh status         # 查看狀態
./bridge.sh logs           # 查看 bot 日誌
./bridge.sh logs session   # 查看指定會話日誌
./bridge.sh validate       # 僅驗證配置

# 手動：前台執行（開發用）
python3 telegram_bot_multi.py
```

### 依賴管理

```bash
# 安裝依賴
pip install -r requirements.txt

# 驗證安裝
python3 -c "import telegram; import yaml; import requests; print('Dependencies OK')"
```

### 配置設定

```bash
# 創建環境變數文件
cp .env.example .env
# 編輯填入：TELEGRAM_BOT_TOKEN 和 ALLOWED_USER_IDS

# 創建會話配置（不在版控中）
cp sessions.yaml.example sessions.yaml
# 編輯填入實際專案路徑
```

### 測試

```bash
# 執行所有測試
pytest

# 含覆蓋率報告
pytest --cov
```

測試檔案位於 `tests/` 目錄：
- `test_config.py` - 配置模組測試
- `test_message_router.py` - 訊息路由器測試
- `test_send_notification.py` - 通知發送測試

配置：`pytest.ini`

### tmux 會話管理

```bash
# 列出所有 tmux 會話
tmux ls

# 連接到特定 Claude 會話
tmux attach -t claude-rental

# 終止特定會話
tmux kill-session -t claude-rental

# 查看會話日誌
tail -f ~/.claude_bridge/logs/claude_rental.log
```

## 架構說明

### 資料流程

**接收訊息（Telegram → Claude）**:
```
Telegram 用戶
    ↓ (發送帶 #project 路由的訊息)
telegram_bot_multi.py (async handlers, queue management)
    ↓ (解析路由)
MessageRouter (regex 解析, 驗證會話)
    ↓ (訊息入隊)
message_queue (threading.queue, 序列化處理)
    ↓ (發送到會話)
SessionManager (管理多個會話)
    ↓ (tmux send-keys)
TmuxBridge (subprocess 執行)
    ↓ (寫入 stdin)
Claude Code 實例 (運行在 tmux 中，配置了 hooks）
```

**發送回應（Claude → Telegram）** - **Hook 驅動**:
```
Claude Code 實例完成回應
    ↓ (觸發 Stop hook)
notify_telegram.sh (從 stdin 讀取 last_assistant_message)
    ↓ (格式化訊息)
send_telegram_notification.py (呼叫 Telegram Bot API)
    ↓ (即時推送，延遲 < 1 秒)
Telegram 用戶
```

### 核心元件

**bridge.sh**
- 統一 CLI 管理工具
- 子命令：`start`（後台啟動）、`stop`（優雅停止 + 清理 tmux）、`restart`、`status`、`logs`、`validate`
- PID 管理：`~/.claude_bridge/bridge.pid`
- 啟動前自動執行配置驗證（檢查 .env、sessions.yaml、路徑、權限等）

**config.py**
- 集中配置管理，消除魔數
- 4 個配置 dataclass：`TelegramConfig`、`TmuxConfig`、`QueueConfig`、`SecurityConfig`
- 全域實例 `config` 和預編譯正則 `patterns`（`CompiledPatterns` 類）
- 從環境變數讀取 `bot_token`、`allowed_user_ids`、`sessions_config_file`

**telegram_bot_multi.py**
- 入口點和主事件循環
- 使用 python-telegram-bot 的 Long Polling 模式（不是 Webhook）
- `BotState` dataclass 管理全域狀態，含 `threading.Lock` 保護執行緒安全更新
- `message_queue`（sync `queue.Queue`）處理 Telegram → Claude 訊息
- Claude → Telegram 回應完全由 Hook 機制處理（不再使用 output_queue）
- 按鈕回調數據格式：`choice_{session_name}:{num}`（冒號分隔符避免會話名稱中的底線造成問題）
- **重要**：新增命令時需使用 `telegram_app.add_handler(CommandHandler(...))` 註冊

**MessageRouter (message_router.py)**
- 路由語法：`#session_name 訊息` 或 `#all 訊息`
- **無預設會話**：沒有 `#` 前綴的訊息會返回錯誤並顯示可用會話列表
- 無效路由返回 `[('__error__', message)]`
- 正則表達式模式：`r'^#([\w]+)\s+(.+)$'`（inline 定義），允許會話名稱包含底線
- **注意**：config.py 中有預編譯版本 `MESSAGE_ROUTE = r'^#([\w\-]+)\s+(.+)$'`（含連字號），但目前未被 MessageRouter 引用

**SessionManager (session_manager.py)**
- 將會話名稱映射到 SessionConfig (name, path, tmux_session, log_file)
- 每個會話有自己的 TmuxBridge 實例
- 支援透過 telegram_bot_multi.py 中的 `reload_sessions_config()` 熱重載
- `restart_session()` 終止舊 tmux 會話並創建新的

**TmuxBridge (tmux_bridge.py)**
- 創建分離的 tmux 會話：`tmux new-session -d -s {name}`
- 啟用日誌記錄：`tmux pipe-pane -t {session} -o 'cat >> {logfile}'`
- 發送命令：`tmux send-keys -t {session} -l {text}` 然後 `tmux send-keys Enter`
- 日誌文件格式：`~/.claude_bridge/logs/claude_{session_name}.log`
- **配置 Claude Code hooks**：在會話創建時自動寫入 `.claude/settings.local.json`，設置 Stop hook 觸發通知腳本

**notify_telegram.sh（Hook 腳本）**
- 由 Claude Code 的 Stop hook 觸發（當 Claude 完成回應時）
- 從 stdin JSON 讀取 `last_assistant_message`（優先）或 fallback 解析 transcript
- 透過 command 前綴傳遞 `TELEGRAM_SESSION_NAME` 環境變數
- 使用 venv 的 Python 確保依賴可用
- 調用 `send_telegram_notification.py` 發送到 Telegram

**send_telegram_notification.py（Telegram 發送器）**
- 獨立的 Python 腳本，直接呼叫 Telegram Bot API
- 從 .env 讀取 `TELEGRAM_BOT_TOKEN` 和 `ALLOWED_USER_IDS`
- 處理訊息格式化（Markdown、截斷長訊息）
- 發送到所有授權用戶的 chat ID，含重試機制

### 關鍵架構決策

1. **Hook 驅動通知**：使用 Claude Code 的 Stop hook 事件驅動通知
   - **優勢**：即時、準確、低延遲、直接從結構化數據獲取乾淨的回覆
   - **實現**：TmuxBridge 創建會話時自動配置 `.claude/settings.local.json` 的 hooks 設置
   - **環境變數傳遞**：透過 command 前綴傳遞 `TELEGRAM_SESSION_NAME`

2. **單向佇列**：`message_queue`（sync `queue.Queue`）處理 Telegram → Claude 訊息。Claude → Telegram 完全由 Hook 處理，無需佇列

3. **會話隔離**：每個 Claude Code 實例運行在獨立的 tmux 會話中，有專用的日誌文件。會話之間不會互相干擾

4. **無預設會話**：強制明確的 `#session` 路由，防止意外將命令發送到錯誤的專案

5. **回調中的冒號分隔符**：按鈕 callback_data 使用 `choice_{session}:{num}` 而不是底線，以支援像 "mac_claude" 這樣的會話名稱

## 配置說明

### sessions.yaml 結構

```yaml
sessions:
  - name: rental              # 用於路由：#rental
    path: /path/to/project   # Claude Code 的工作目錄
    tmux: claude-rental      # 可選：tmux 會話名稱（預設為 claude-{name}）
```

**重要事項**：
- `name` 用於 Telegram 路由（`#name`）
- `tmux` 是實際的 tmux 會話名稱（可以與 `name` 不同）
- `path` 必須是絕對路徑
- 文件不在版本控制中（在 .gitignore 裡）

### .env 變數

```env
TELEGRAM_BOT_TOKEN=...       # 從 @BotFather 獲取
ALLOWED_USER_IDS=123,456     # 逗號分隔，空白 = 允許所有人
SESSIONS_CONFIG_FILE=sessions.yaml  # 可選，預設為 sessions.yaml
```

### Claude Code Hooks 配置（自動生成）

當 TmuxBridge 創建新會話時，會自動在專案目錄的 `.claude/settings.local.json` 中寫入 hooks：

```json
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "TELEGRAM_SESSION_NAME=session_name /path/to/mac_claude/notify_telegram.sh",
        "timeout": 30
      }]
    }]
  }
}
```

**注意**：hooks 必須在 `settings.local.json`（不是 `config.json`），Claude Code 只從 settings 檔案讀取 hooks。

**手動驗證 hooks 配置**：
```bash
# 查看專案的 hook 配置
cat /path/to/project/.claude/settings.local.json

# 測試 hook 腳本（需要設置環境變數）
export TELEGRAM_SESSION_NAME=test
echo '{"transcript_path": "/path/to/transcript.json"}' | ./notify_telegram.sh
```

## Telegram Bot 命令實作

新增 Telegram 命令時：

1. 在 telegram_bot_multi.py 創建 async 處理函數：
   ```python
   async def my_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
       if not check_user_permission(update):
           await update.message.reply_text("❌ 未授權的用戶")
           return
       # 實作內容
   ```

2. 在 main() 中註冊：
   ```python
   telegram_app.add_handler(CommandHandler("mycommand", my_command))
   ```

3. 更新 `start()` 函數中的幫助文字

現有命令：
- `/start` - 顯示幫助和會話列表
- `/status` - 顯示所有會話狀態（含 Hook 通知狀態）
- `/sessions` - 列出配置的會話
- `/restart #session` - 終止並重建 tmux 會話
- `/reload` - 熱重載 sessions.yaml 無需重啟 bot

## 熱重載機制

`/reload` 命令（實作在 `reload_sessions_config()` 中）執行以下步驟：

1. 載入新的 sessions.yaml
2. 與當前會話比較（新增/移除/保留）
3. 終止已移除會話的 tmux 會話
4. 用新配置中的所有會話創建新的 SessionManager
5. 為新增的會話創建 tmux 會話（含 Hook 配置）
6. 更新全域的 `session_manager` 和 `message_router` 引用

**關鍵要點**：保留的會話持續運行；只有新增/移除的會話會受影響。

## 常見修改

### 更改訊息截斷閾值

編輯 `send_telegram_notification.py` 的 `MAX_MESSAGE_LENGTH`（預設 4000）。
超過此長度的 Hook 回覆會被截斷並標註 `[Message truncated]`。

### 調整 Hook 超時

編輯 `tmux_bridge.py` 的 `_configure_claude_hooks()` 中的 `"timeout": 30`（預設 30 秒）。

## 故障排除

### Bot 無法接收訊息
1. 檢查 bot 使用 Long Polling（不是 Webhook）：`telegram_app.run_polling()`
2. 驗證 .env 中的 TELEGRAM_BOT_TOKEN
3. 檢查是否在 BotFather 中用 `/setcommands` 停止了 bot

### 會話無回應
1. 檢查 tmux 會話存在：`tmux ls`
2. 檢查日誌文件存在且正在寫入：`ls -la ~/.claude_bridge/logs/claude_*.log`
3. 驗證 tmux pipe-pane 是否啟動：連接到會話並檢查日誌輸出
4. 嘗試 `/restart #session` 重建會話

### 輸出未出現在 Telegram（Hook 機制）
1. **檢查 hook 配置**：確認專案目錄 `.claude/settings.local.json` 包含 Stop hook
   ```bash
   cat /path/to/project/.claude/settings.local.json | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('hooks',{}), indent=2))"
   ```
2. **檢查 hook 腳本權限**：確認 `notify_telegram.sh` 可執行
   ```bash
   ls -la notify_telegram.sh send_telegram_notification.py
   ```
3. **查看 hook 除錯日誌**：
   ```bash
   cat ~/.claude_bridge/logs/hook_debug_*.log
   ```
4. **檢查 Telegram Bot Token**：確認 .env 中的 TELEGRAM_BOT_TOKEN 正確
5. **查看 Claude 日誌**：連接到 tmux 會話查看 hook 是否有錯誤訊息
   ```bash
   tmux attach -t <tmux_session_name>  # tmux 名稱見 sessions.yaml 的 tmux 欄位
   ```

### 除錯工具

- **分析 transcript 結構**：`python3 test_transcript_parser.py <transcript_path>` — 顯示訊息結構、content blocks、tool_use 詳情
- **測試 hook 腳本**：`bash test_hook.sh` — 端到端測試 hook 通知流程

### 會話名稱包含底線的問題
如果按鈕回調在會話名稱包含底線時失敗，驗證 callback_data 格式使用冒號分隔符：`choice_{session}:{num}`（不是 `choice_{session}_{num}`）

## 重要限制

- 需要 tmux（在 macOS 上用 Homebrew tmux 測試過）
- 必須安裝 Claude Code CLI 並在 PATH 中
- 日誌存放在 `~/.claude_bridge/logs/`（持久化，不會因重啟丟失）
- 需要 Python 3.7+（asyncio 支援）
- Long Polling 模式需要持續的網路連接
- 每個會話需要唯一的 tmux 會話名稱
- 會話名稱應符合 `[\w]+` 模式（字母數字 + 底線）

## 測試流程

### 基本功能測試

1. 驗證配置：`./bridge.sh validate`
2. 啟動 bot：`./bridge.sh start`
3. 驗證狀態：`./bridge.sh status`（應顯示 Bot 運行中 + tmux 會話）
4. 在 Telegram 發送 `/start` 確認 bot 回應
5. 發送測試訊息：`#session_name 你好`
6. **驗證 hook 觸發**：應收到 `📍 session_name` 格式的乾淨回覆（延遲 < 1 秒）
7. 查看日誌：`./bridge.sh logs`
8. 測試熱重載：編輯 sessions.yaml，使用 `/reload`，驗證變更
9. 停止：`./bridge.sh stop`（應清理所有 tmux 會話）

### 單元測試

```bash
pytest tests/ -v
# 應該 37 個測試全部通過
```

## 安全注意事項

- ALLOWED_USER_IDS 提供基本存取控制
- .env 和 sessions.yaml 在 .gitignore 中
- 無 webhook 模式意味著沒有公開 URL 暴露
- tmux 會話以當前用戶權限運行
- 日誌文件權限設為 0o600（僅擁有者可讀寫，由 TmuxBridge 設定）