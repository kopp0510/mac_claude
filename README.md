# Claude Code Telegram 多會話橋接

通過 Telegram 與多個正在運行的 Claude Code 實例進行雙向互動。

## 功能特性

- 🔄 **雙向通訊**：Claude Code 的輸出即時推送到 Telegram，Telegram 的訊息也能傳回 Claude Code
- 🔀 **多會話並行**：同時管理多個 Claude Code 實例，並行執行任務
- 🏷️ **來源標記**：所有回覆都標記來源 `[#project]`，清楚辨識
- 📮 **智能路由**：使用 `#project` 語法指定目標，或 `#all` 廣播給所有會話
- 🖥️ **同時操作**：可以同時在終端和 Telegram 與 Claude Code 互動
- 🤖 **智能過濾**：自動識別最終回覆，過濾處理訊息和 ANSI 控制碼
- 🎯 **互動式按鈕**：確認提示自動轉換為 Inline Keyboard 按鈕
- 📊 **分段發送**：長訊息自動分段，超長內容上傳為文件
- 🔒 **用戶驗證**：僅允許特定用戶使用
- ⚡ **訊息佇列**：避免衝突，訊息依序處理

## 系統架構

```
                    Telegram 用戶
                         │
                    #rental 訊息
                    #api 訊息
                    #all 訊息
                         │
                         ▼
                 ┌───────────────┐
                 │ telegram_bot  │
                 │   (路由器)    │
                 └───────┬───────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │  tmux   │    │  tmux   │    │  tmux   │
    │ rental  │    │   api   │    │  docs   │
    └────┬────┘    └────┬────┘    └────┬────┘
         │              │              │
         ▼              ▼              ▼
    [#rental]       [#api]         [#docs]
         │              │              │
         └──────────────┼──────────────┘
                        ▼
                    Telegram
```

## 快速開始

### 1. 安裝依賴

```bash
# 安裝 tmux
brew install tmux

# 安裝 Python 依賴
pip install -r requirements.txt
```

### 2. 創建 Telegram Bot

1. 在 Telegram 找到 [@BotFather](https://t.me/BotFather)
2. 發送 `/newbot` 創建 bot
3. 保存 Bot Token

### 3. 獲取 User ID

1. 在 Telegram 找到 [@userinfobot](https://t.me/userinfobot)
2. 發送 `/start`
3. 記下 User ID

### 4. 配置

**創建 .env 文件：**

```bash
cp .env.example .env
```

編輯 `.env`：

```env
TELEGRAM_BOT_TOKEN=你的_bot_token
ALLOWED_USER_IDS=你的_user_id
```

**創建 sessions.yaml 配置文件：**

```yaml
sessions:
  - name: rental
    path: /Users/你的用戶名/project/rental-management
    tmux: claude-rental

  - name: api
    path: /Users/你的用戶名/project/api-server
    tmux: claude-api
```

### 5. 啟動

```bash
# 推薦：後台啟動（含配置驗證、自動安裝依賴）
./bridge.sh start

# 查看狀態
./bridge.sh status

# 停止
./bridge.sh stop
```

## 使用方法

### 訊息路由語法

在 Telegram 中發送訊息：

```
#rental 查詢當前路徑          → 發送給 rental 會話
#api 執行測試                → 發送給 api 會話
#all 生成文檔                → 發送給所有會話
```

**注意**：必須使用 `#` 前綴指定目標會話，沒有前綴的訊息會返回錯誤並顯示可用會話列表。

### 回覆格式

所有回覆都會標記來源：

```
[#rental]
/Users/你的用戶名/project/rental-management

[#api]
測試完成！所有測試通過。
```

### Telegram 命令

- `/start` - 顯示幫助和會話列表
- `/status` - 查看所有會話狀態
- `/sessions` - 查看會話列表
- `/buffer #rental` - 獲取指定會話的緩衝區內容
- `/clear #rental` - 清空指定會話的緩衝區
- `/restart #rental` - 重啟指定會話
- `/reload` - 重新載入 sessions.yaml 配置（無需重啟 Bot）

### 互動式按鈕

當 Claude 詢問確認時，會自動顯示按鈕：

```
[#rental]
Do you want to proceed with editing these 3 files?
  1. Yes, proceed with edits
  2. No, cancel

[✅ 1. Yes]  [❌ 2. No]  ← 點擊按鈕自動回覆
```

### 管理命令

```bash
./bridge.sh start          # 後台啟動 Bot
./bridge.sh stop           # 停止 Bot 並清理 tmux 會話
./bridge.sh restart        # 重啟 Bot
./bridge.sh status         # 查看 Bot 和會話狀態
./bridge.sh logs           # 查看 Bot 主日誌
./bridge.sh logs rental    # 查看指定會話日誌
./bridge.sh validate       # 驗證配置
```

### 連接到終端

你可以隨時 attach 到 tmux 會話直接操作：

```bash
# 連接到指定會話
tmux attach -t claude-rental

# 退出但不終止（按鍵）
Ctrl+B, 然後按 D
```

## 配置說明

### sessions.yaml 格式

```yaml
sessions:
  - name: 會話名稱          # 用於 #name 路由
    path: 專案路徑          # Claude Code 工作目錄
    tmux: tmux_會話名稱     # tmux 會話名稱（可選，預設 claude-{name}）
```

**範例：**

```yaml
sessions:
  - name: rental
    path: /Users/danlio/project/rental-management
    tmux: claude-rental

  - name: api
    path: /Users/danlio/project/api-server
    tmux: claude-api

  - name: docs
    path: /Users/danlio/project/documentation
    # tmux 會話名稱會自動設為 claude-docs
```
### .env 配置

```env
TELEGRAM_BOT_TOKEN=你的_telegram_bot_token
ALLOWED_USER_IDS=user_id_1,user_id_2
```

**變數說明：**
- `TELEGRAM_BOT_TOKEN` - 必填，從 BotFather 獲取
- `ALLOWED_USER_IDS` - 可選，留空則允許所有用戶

## 工作原理

### 即時通知（Hook 驅動 — 主要機制）

1. Claude Code 完成回應時觸發 Stop hook
2. `notify_telegram.sh` 解析 `transcript.json` 提取 assistant 訊息
3. `send_telegram_notification.py` 透過 Telegram Bot API 即時推送
4. 延遲 < 1 秒，事件驅動

### 輸出監控（備用機制）

1. 每個會話的 tmux 將輸出記錄到獨立日誌
2. `MultiSessionMonitor` 同時監控所有會話
3. 檢測輸出完成（閒置 8 秒）
4. 清理 ANSI 碼、過濾處理訊息
5. 格式化並推送到 Telegram，附上來源標記
6. 主要用於 `/buffer` 命令查詢歷史輸出

### 訊息路由

1. `MessageRouter` 解析 `#project` 語法
2. `SessionManager` 將訊息路由到對應會話
3. 使用 `tmux send-keys` 注入到 Claude Code
4. 支援 `#all` 廣播給所有會話

### 並行執行

- 所有會話獨立運行，互不干擾
- 每個會話有獨立的監控執行緒
- 回覆按完成順序推送，附上來源標記

## 文件說明

**主程式：**
- `telegram_bot_multi.py` - Telegram Bot 主程式

**核心模組：**
- `session_manager.py` - 會話管理器
- `message_router.py` - 訊息路由器
- `multi_session_monitor.py` - 多會話監控器
- `output_monitor.py` - 輸出監控和過濾
- `tmux_bridge.py` - Tmux 橋接模組
- `config.py` - 集中配置管理

**Hook 通知：**
- `notify_telegram.sh` - Claude Code Stop hook 腳本
- `send_telegram_notification.py` - Telegram API 發送器

**啟動與配置：**
- `bridge.sh` - 統一管理工具（start/stop/restart/status/logs/validate）
- `start_bridge.sh` - 舊版啟動腳本（仍可用）
- `sessions.yaml` - 會話配置
- `.env` - 環境變數
- `requirements.txt` - Python 依賴

## 訊息格式化

- **短訊息**（< 4000 字元）：單條發送
- **中等長度**（4000-12000 字元）：分段發送，標記 `[1/3]`、`[2/3]`
- **超長訊息**（> 12000 字元）：上傳為 `.txt` 文件

## 輸出過濾

自動過濾：
- ✅ 處理訊息（Whisking, Contemplating 等）
- ✅ ANSI 控制碼（顏色、游標移動）
- ✅ Tool 調用詳細內容
- ✅ 分隔線和提示符
- ✅ 超長文件內容（自動摘要）

## 安全建議

1. **限制用戶**：設置 `ALLOWED_USER_IDS` 只允許特定用戶
2. **保護配置**：`.env` 加入 `.gitignore`，不要提交敏感資訊
3. **工作目錄權限**：確保專案目錄權限正確
4. **網絡安全**：使用 Polling 模式，無需公開網址

## 故障排除

### 會話無法創建

```bash
# 檢查 tmux
which tmux

# 手動測試
tmux new -s test
```

### 無法接收輸出

```bash
# 檢查日誌文件
ls -la ~/.claude_bridge/logs/claude_*.log

# 查看日誌
tail -f ~/.claude_bridge/logs/claude_rental.log
```

### Bot 無法啟動

```bash
# 檢查配置
cat .env
cat sessions.yaml

# 檢查 Python 模組
python3 -c "import telegram; import yaml; import requests"
```

### Hook 通知未觸發

```bash
# 檢查 hook 配置是否存在
cat /path/to/project/.claude/config.json

# 檢查 hook 腳本權限
ls -la notify_telegram.sh send_telegram_notification.py

# 手動測試 hook
export TELEGRAM_SESSION_NAME=test
echo '{"transcript_path": "/path/to/transcript.json"}' | ./notify_telegram.sh

# 查看 hook 除錯日誌
cat ~/.claude_bridge/logs/hook_debug_*.log
```

### 訊息未送達

```bash
# 檢查 tmux 會話
tmux ls

# 在 Telegram 查看狀態
/status
```

## 常見問題

**Q: 為什麼要用 tmux？**
A: tmux 提供會話管理和日誌記錄，是實現雙向通訊的基礎。

**Q: 可以在遠程伺服器使用嗎？**
A: 可以！只要伺服器能連接 Telegram API。

**Q: 如何停止橋接？**
A: 使用管理工具一鍵停止（自動清理所有 tmux 會話）：
```bash
./bridge.sh stop
```

**Q: 如何添加新專案？**
A: 在 `sessions.yaml` 添加新配置，然後使用 `/reload` 命令熱重載配置，無需重啟 Bot。

**Q: 會話出現問題如何重啟？**
A: 使用 `/restart #session` 命令重啟指定會話，例如 `/restart #rental`。這會終止舊的 tmux 會話並創建新的會話。

**Q: 修改配置後需要重啟 Bot 嗎？**
A: 不需要！使用 `/reload` 命令即可熱重載 `sessions.yaml`，系統會自動添加新會話、移除舊會話，並保持現有會話運行。

## 授權

MIT License

## 相關連結

- [Claude Code 官方文檔](https://docs.claude.com/claude-code)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [python-telegram-bot](https://python-telegram-bot.readthedocs.io/)
- [tmux](https://github.com/tmux/tmux/wiki)