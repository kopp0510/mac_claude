# Claude Code Telegram 多會話橋接

通過 Telegram 與多個正在運行的 Claude Code 實例進行雙向互動。

## 功能特性

- 🔄 **雙向通訊**：Claude Code 的輸出即時推送到 Telegram，Telegram 的訊息也能傳回 Claude Code
- 🔀 **多會話並行**：同時管理多個 Claude Code 實例，並行執行任務
- 🏷️ **來源標記**：所有回覆都標記來源 `📍 project`，清楚辨識
- 📮 **智能路由**：使用 `#project` 語法指定目標，或 `#all` 廣播給所有會話
- 🖥️ **同時操作**：可以同時在終端和 Telegram 與 Claude Code 互動
- 🤖 **Hook 即時通知**：Claude 完成回應時透過 Hook 即時推送，延遲 < 1 秒
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

**方式 A：本機直接運行**
```bash
./bridge.sh start
./bridge.sh status
./bridge.sh stop
```

**方式 B：Docker 運行**
```bash
# 1. 編輯 docker-compose.yml 掛載你的專案目錄
# 2. sessions.yaml 中的 path 須與容器內路徑對齊

# 建構並啟動
docker compose up -d --build

# 查看日誌
docker compose logs -f

# 停止
docker compose down
```

**Docker 認證方式：**
- **API Key**：在 `.env` 加 `ANTHROPIC_API_KEY=sk-ant-...`
- **Max/Pro OAuth**：先在本機執行 `claude` 登入一次，Docker 會掛載 `~/.claude/` 讀取認證

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

所有回覆都會標記來源（Hook 驅動，即時推送）：

```
📍 rental

這是一個房租管理系統...

📍 api

測試完成！所有測試通過。
```

### Telegram 命令

- `/start` - 顯示幫助和會話列表
- `/status` - 查看所有會話狀態
- `/sessions` - 查看會話列表
- `/restart #session` - 重啟指定會話
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
# 查看所有會話
tmux ls

# 連接到指定會話（tmux 名稱見 sessions.yaml 配置）
tmux attach -t <tmux_session_name>

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
    path: /path/to/rental-management
    tmux: claude-rental

  - name: api
    path: /path/to/api-server
    tmux: claude-api

  - name: docs
    path: /path/to/documentation
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

### 即時通知（Hook 驅動）

1. Claude Code 完成回應時觸發 Stop hook
2. `notify_telegram.sh` 從 hook stdin 讀取 `last_assistant_message`
3. `send_telegram_notification.py` 透過 Telegram Bot API 即時推送
4. 延遲 < 1 秒，事件驅動，回覆內容乾淨無 ANSI 碼

### 訊息路由

1. `MessageRouter` 解析 `#project` 語法
2. `SessionManager` 將訊息路由到對應會話
3. 使用 `tmux send-keys` 注入到 Claude Code
4. 支援 `#all` 廣播給所有會話

### 並行執行

- 所有會話獨立運行，互不干擾
- 每個會話有獨立的 Hook 通知
- 回覆按完成順序即時推送，附上來源標記

## 文件說明

**主程式：**
- `telegram_bot_multi.py` - Telegram Bot 主程式

**核心模組：**
- `session_manager.py` - 會話管理器
- `message_router.py` - 訊息路由器
- `tmux_bridge.py` - Tmux 橋接模組
- `config.py` - 集中配置管理

**Hook 通知：**
- `notify_telegram.sh` - Claude Code Stop hook 腳本
- `send_telegram_notification.py` - Telegram API 發送器

**啟動與配置：**
- `bridge.sh` - 統一管理工具（start/stop/restart/status/logs/validate）
- `sessions.yaml` - 會話配置
- `.env` - 環境變數
- `requirements.txt` - Python 依賴

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
# 檢查 hook 配置（必須在 settings.local.json，不是 config.json）
cat /path/to/project/.claude/settings.local.json

# 檢查 hook 腳本權限
ls -la notify_telegram.sh send_telegram_notification.py

# 查看 hook 除錯日誌
cat ~/.claude_bridge/logs/hook_debug_*.log

# 查看 bot 日誌
./bridge.sh logs
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