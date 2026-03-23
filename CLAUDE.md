# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

一個透過 tmux 橋接多個 Claude Code 實例的 Telegram Bot，實現透過 Telegram 訊息遠端控制和雙向通訊 Claude Code 會話。

## 開發命令

### 執行 Bot

```bash
# 推薦：使用啟動腳本（自動處理虛擬環境、依賴、驗證）
./start_bridge.sh

# 手動：直接執行
python3 telegram_bot_multi.py

# 開發：使用特定 Python 版本
python3.13 telegram_bot_multi.py
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
- `test_output_monitor.py` - 輸出監控測試
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
tail -f /tmp/claude_rental.log
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

**發送回應（Claude → Telegram）** - **使用 Hooks（新架構）**:
```
Claude Code 實例完成回應
    ↓ (觸發 Stop hook)
notify_telegram.sh (解析 transcript.json)
    ↓ (提取最後的 assistant 訊息)
send_telegram_notification.py (格式化訊息)
    ↓ (直接呼叫 Telegram Bot API)
Telegram 用戶
```

**緩衝區和日誌（保留用於 /buffer 命令）**:
```
Claude Code 輸出
    ↓ (tmux pipe-pane 記錄)
/tmp/claude_{name}.log
    ↓ (可選：OutputMonitor 輪詢)
MultiSessionMonitor (管理緩衝區)
    ↓ (/buffer 命令查詢)
Telegram 用戶
```

### 核心元件

**config.py**
- 集中配置管理，消除魔數
- 5 個配置 dataclass：`TelegramConfig`、`MonitorConfig`、`TmuxConfig`、`QueueConfig`、`SecurityConfig`
- 全域實例 `config` 和預編譯正則 `patterns`（`CompiledPatterns` 類）
- 從環境變數讀取 `bot_token`、`allowed_user_ids`、`sessions_config_file`

**telegram_bot_multi.py**
- 入口點和主事件循環
- 使用 python-telegram-bot 的 Long Polling 模式（不是 Webhook）
- `BotState` dataclass 管理全域狀態，含 `threading.Lock` 保護 session_manager 和 message_router 的執行緒安全更新
- 兩個 `queue.Queue`（sync）佇列：`message_queue` 處理接收，`output_queue` 處理發送（透過 async wrapper 消費）
- 佇列有大小限制（來自 `config.queue`）
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
- 日誌文件格式：`/tmp/claude_{session_name}.log`
- **配置 Claude Code hooks**：在會話創建時自動寫入 `.claude/config.json`，設置 Stop hook 觸發通知腳本

**notify_telegram.sh（新組件 - Hook 腳本）**
- 由 Claude Code 的 Stop hook 觸發（當 Claude 完成回應時）
- 從 stdin 接收 hook 數據（JSON 格式，包含 session_id、transcript_path）
- 透過環境變數 `TELEGRAM_SESSION_NAME` 識別會話
- 解析 transcript.json 提取最後的 assistant 訊息
- 調用 `send_telegram_notification.py` 發送到 Telegram

**send_telegram_notification.py（新組件 - Telegram 發送器）**
- 獨立的 Python 腳本，直接呼叫 Telegram Bot API
- 從 .env 讀取 `TELEGRAM_BOT_TOKEN` 和 `ALLOWED_USER_IDS`
- 處理訊息格式化（Markdown、截斷長訊息）
- 發送到所有授權用戶的 chat ID
- **優勢**：即時、事件驅動，無需輪詢

**OutputMonitor (output_monitor.py)** - **保留用於緩衝區功能**
- 基於文件的監控（tmux pipe-pane 輸出）
- 主要用於 `/buffer` 命令查詢歷史輸出
- 過濾掉：ANSI 碼、"Whisking"、"Contemplating"、工具調用細節
- 偵測確認提示：類似 "1. Yes" "2. No" 的模式
- **訊息格式化**：<4000 字元 = 單條訊息，4000-12000 = 分段並標記 [1/3]，>12000 = 上傳為 .txt 文件

**MultiSessionMonitor (multi_session_monitor.py)** - **保留用於緩衝區管理**
- 為每個會話創建一個 OutputMonitor 執行緒
- 管理輸出緩衝區供 `/buffer` 命令使用
- 回調包裝器模式：`make_callback(session_name)` 注入會話上下文
- `add_monitor()` 用於熱重載時動態添加會話
- `stop_monitor()` 用於移除會話

### 關鍵架構決策

1. **Hook 驅動通知（新）**：使用 Claude Code 的 Stop hook 事件驅動通知，取代輪詢機制
   - **優勢**：即時、準確、低延遲、直接從 transcript.json 獲取結構化數據
   - **實現**：TmuxBridge 創建會話時自動配置 `.claude/config.json` 的 hooks 設置
   - **環境變數傳遞**：透過 hook 配置的 `env` 欄位傳遞 `TELEGRAM_SESSION_NAME`

2. **雙佇列系統**：`message_queue` 和 `output_queue` 都是 `queue.Queue`（sync），`output_queue` 透過 async wrapper（`output_queue_handler`）在事件循環中消費。選用 sync queue 是因為 tmux 操作在同步執行緒中執行

3. **基於文件的日誌**：tmux pipe-pane 寫入文件，保留用於 `/buffer` 命令查詢歷史輸出

4. **會話隔離**：每個 Claude Code 實例運行在獨立的 tmux 會話中，有專用的日誌文件。會話之間不會互相干擾

5. **無預設會話**：強制明確的 `#session` 路由，防止意外將命令發送到錯誤的專案

6. **回調中的冒號分隔符**：按鈕 callback_data 使用 `choice_{session}:{num}` 而不是底線，以支援像 "mac_claude" 這樣的會話名稱

7. **雙通知機制（過渡期）**：
   - **主要**：Hook 驅動（notify_telegram.sh → send_telegram_notification.py → Telegram API）
   - **備用**：OutputMonitor 輪詢（保留用於緩衝區和舊版相容）

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

當 TmuxBridge 創建新會話時，會自動在專案目錄創建 `.claude/config.json`：

```json
{
  "hooks": {
    "Stop": [{
      "type": "command",
      "command": "/path/to/mac_claude/notify_telegram.sh",
      "env": {
        "TELEGRAM_SESSION_NAME": "session_name"
      }
    }]
  }
}
```

**手動驗證 hooks 配置**：
```bash
# 查看專案的 hook 配置
cat /path/to/project/.claude/config.json

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
- `/status` - 顯示所有會話的 tmux 會話狀態
- `/sessions` - 列出配置的會話
- `/buffer #session` - 顯示會話的緩存輸出
- `/clear #session` - 清空會話的輸出緩衝區
- `/restart #session` - 終止並重建 tmux 會話
- `/reload` - 熱重載 sessions.yaml 無需重啟 bot

## 熱重載機制

`/reload` 命令（實作在 `reload_sessions_config()` 中）執行以下步驟：

1. 載入新的 sessions.yaml
2. 與當前會話比較（新增/移除/保留）
3. 停止已移除會話的監控器
4. 終止已移除會話的 tmux 會話
5. 用新配置中的所有會話創建新的 SessionManager
6. 為新增的會話創建 tmux 會話
7. 為新增的會話添加監控器
8. 更新全域的 `session_manager` 和 `message_router` 引用

**關鍵要點**：保留的會話持續運行；只有新增/移除的會話會受影響。

## 常見修改

### 調整閒置超時

編輯 config.py 的 `MonitorConfig.IDLE_TIMEOUT`（預設 8.0 秒）：
```python
@dataclass
class MonitorConfig:
    IDLE_TIMEOUT: float = 8.0  # 修改此值
```

如果 Claude 回應被截斷則增加，如需更快回應時間則減少。

### 添加輸出過濾器

編輯 output_monitor.py 的 `clean_output()` 方法。當前過濾器包括：
- 進度訊息的關鍵字（定義在 config.py 的 `CompiledPatterns.PROCESSING_KEYWORDS`）
- ANSI 轉義碼移除（`CompiledPatterns.ANSI_ESCAPE`）
- 工具調用清理（`CompiledPatterns.TOOL_INVOKE`）
- 文件內容截斷

### 更改訊息格式閾值

編輯 config.py 的 `TelegramConfig`：
```python
@dataclass
class TelegramConfig:
    MAX_MESSAGE_LENGTH: int = 4000   # 單條訊息最大長度
    MAX_TOTAL_LENGTH: int = 12000    # 超過此長度上傳為文件
```

### 支援新的確認提示模式

編輯 config.py 的 `CompiledPatterns.CONFIRMATION_OPTION`。當前正則：`r'^\s*[❯]?\s*(\d+)\.\s*(.+)'`

## 故障排除

### Bot 無法接收訊息
1. 檢查 bot 使用 Long Polling（不是 Webhook）：`telegram_app.run_polling()`
2. 驗證 .env 中的 TELEGRAM_BOT_TOKEN
3. 檢查是否在 BotFather 中用 `/setcommands` 停止了 bot

### 會話無回應
1. 檢查 tmux 會話存在：`tmux ls`
2. 檢查日誌文件存在且正在寫入：`ls -la /tmp/claude_*.log`
3. 驗證 tmux pipe-pane 是否啟動：連接到會話並檢查日誌輸出
4. 嘗試 `/restart #session` 重建會話

### 輸出未出現在 Telegram（使用 Hook 機制）
1. **檢查 hook 配置**：確認專案目錄有 `.claude/config.json` 且包含 Stop hook
   ```bash
   cat /path/to/project/.claude/config.json
   ```
2. **檢查 hook 腳本權限**：確認 `notify_telegram.sh` 可執行
   ```bash
   ls -la notify_telegram.sh send_telegram_notification.py
   ```
3. **測試 hook 腳本**：手動執行測試
   ```bash
   export TELEGRAM_SESSION_NAME=test
   echo '{"transcript_path": "/Users/.../.claude/transcripts/xxx.json"}' | ./notify_telegram.sh
   ```
4. **檢查 Telegram Bot Token**：確認 .env 中的 TELEGRAM_BOT_TOKEN 正確
5. **查看 Claude 日誌**：連接到 tmux 會話查看 hook 是否有錯誤訊息
   ```bash
   tmux attach -t claude-session_name
   ```
6. **備用方案**：如果 hook 失敗，OutputMonitor 仍會輪詢並發送（延遲較高）
7. 使用 `/buffer #session` 查看原始緩衝輸出

### 除錯工具

- **分析 transcript 結構**：`python3 test_transcript_parser.py <transcript_path>` — 顯示訊息結構、content blocks、tool_use 詳情
- **測試 hook 腳本**：`bash test_hook.sh` — 端到端測試 hook 通知流程

### 會話名稱包含底線的問題
如果按鈕回調在會話名稱包含底線時失敗，驗證 callback_data 格式使用冒號分隔符：`choice_{session}:{num}`（不是 `choice_{session}_{num}`）

## 重要限制

- 需要 tmux（在 macOS 上用 Homebrew tmux 測試過）
- 必須安裝 Claude Code CLI 並在 PATH 中
- /tmp 中的日誌文件在系統重啟時會被清除
- 需要 Python 3.7+（asyncio 支援）
- Long Polling 模式需要持續的網路連接
- 每個會話需要唯一的 tmux 會話名稱
- 會話名稱應符合 `[\w]+` 模式（字母數字 + 底線）

## 測試流程

### 基本功能測試

1. 啟動 bot：`./start_bridge.sh`
2. 驗證會話已創建：`tmux ls` 應顯示所有配置的會話
3. **驗證 hook 配置**：檢查每個專案目錄的 `.claude/config.json`
   ```bash
   # 應該看到 Stop hook 配置
   cat /path/to/project/.claude/config.json | jq .hooks.Stop
   ```
4. 在 Telegram 發送測試訊息：`#session_name hi`
5. **驗證 hook 觸發**：應該立即收到 Claude 回應（透過 hook，延遲 < 1 秒）
6. 如有問題檢查日誌：`tail -f /tmp/claude_session_name.log`
7. 監控 bot 日誌以查看路由和佇列活動
8. 使用 `/status` 在 Telegram 驗證所有會話都是活躍的
9. 測試熱重載：編輯 sessions.yaml，使用 `/reload`，驗證變更

### Hook 整合測試

1. **測試 hook 腳本獨立運行**：
   ```bash
   # 創建測試 transcript
   mkdir -p /tmp/test_transcript
   echo '{"messages": [{"role": "assistant", "content": [{"type": "text", "text": "Test message"}]}]}' > /tmp/test_transcript/test.json

   # 測試 hook
   export TELEGRAM_SESSION_NAME=test
   echo '{"transcript_path": "/tmp/test_transcript/test.json"}' | ./notify_telegram.sh

   # 應該在 Telegram 收到 "📍 test\n\nTest message"
   ```

2. **測試完整流程**：
   ```bash
   # 發送訊息到 Claude
   #test_session hello

   # 監控 tmux 會話查看 hook 執行
   tmux attach -t claude-test_session

   # 當 Claude 回應完成時，應該看到 hook 執行並立即收到 Telegram 通知
   ```

3. **驗證舊機制備用**：
   ```bash
   # 暫時移除 hook 配置
   mv /path/to/project/.claude/config.json /path/to/project/.claude/config.json.bak

   # 重啟會話
   /restart #session_name

   # 發送測試訊息，應該仍能收到回應（透過 OutputMonitor，延遲約 8 秒）

   # 恢復 hook 配置
   mv /path/to/project/.claude/config.json.bak /path/to/project/.claude/config.json
   ```

## 安全注意事項

- ALLOWED_USER_IDS 提供基本存取控制
- .env 和 sessions.yaml 在 .gitignore 中
- 無 webhook 模式意味著沒有公開 URL 暴露
- tmux 會話以當前用戶權限運行
- /tmp 中的日誌文件權限設為 0o600（僅擁有者可讀寫，由 TmuxBridge 設定）