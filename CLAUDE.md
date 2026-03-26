# CLAUDE.md

透過 tmux 橋接多個 AI CLI 實例（Claude Code、Gemini CLI）的 Telegram Bot。
**僅負責訊息轉發，不處理 CLI 登入認證。**

## 開發命令

```bash
# Bot 管理
./bridge.sh start          # 後台啟動（含配置驗證）
./bridge.sh stop           # 優雅停止（含清理 hooks、tmux、日誌）
./bridge.sh restart        # 重啟
./bridge.sh status         # 查看狀態
./bridge.sh logs           # 查看 bot 日誌
./bridge.sh logs session   # 查看指定會話日誌
./bridge.sh validate       # 僅驗證配置

# 手動前台執行（開發用）
python3 telegram_bot_multi.py

# 測試
pytest                     # 執行所有測試（~177 個）
pytest --cov               # 含覆蓋率

# 配置
cp .env.example .env       # 填入 TELEGRAM_BOT_TOKEN 和 ALLOWED_USER_IDS
cp sessions.yaml.example sessions.yaml  # 填入實際專案路徑

# tmux 會話（名稱格式：{cli_type}-{name}）
tmux ls                    # 列出所有會話
tmux attach -t claude-myproject  # 連接會話
```

## 配置

### sessions.yaml

```yaml
sessions:
  - name: webapp              # 用於路由：#webapp
    path: /path/to/project   # 絕對路徑
    cli_type: claude          # 可選：claude（預設）或 gemini
    tmux: claude-webapp      # 可選：預設為 {cli_type}-{name}
    cli_args: "--model sonnet"  # 可選

  - name: devops
    path: /path/to/infra
    cli_type: gemini
    cli_args: "--yolo"
```

`cli_args` 向後相容 `claude_args`。文件在 .gitignore 中。

### .env

```env
TELEGRAM_BOT_TOKEN=...       # 必填，從 @BotFather 獲取
ALLOWED_USER_IDS=123,456     # 必填，逗號分隔（空白拒絕啟動）
LANGUAGE=zh-TW               # 可選：zh-TW（預設）或 en
```

## 架構

```
Telegram → telegram_bot_multi.py → MessageRouter → message_queue → SessionManager → TmuxBridge → CLI
CLI hook (Claude: Stop, Gemini: AfterAgent) → notify_telegram.sh → send_telegram_notification.py → Telegram
```

### 關鍵設計

- **Strategy 模式**：`cli_provider.py` 定義 `CliProvider` 介面，`ClaudeProvider`/`GeminiProvider` 各自處理啟動命令和 hook 配置。新增 CLI 只需新增 Provider
- **Hook 驅動通知**：hooks 由 `CliProvider.configure_hooks()` 自動配置到專案目錄
- **單向佇列**：Telegram → CLI 用 `queue.Queue`，CLI → Telegram 完全由 hook 處理
- **Gemini 特殊處理**：需要 extra Enter 送出、auto-trust folder、hook stdout 必須是 JSON
- **i18n 多語言**：`i18n.py` 模組 + `locales/` JSON/Shell 翻譯檔，透過 `.env` 的 `LANGUAGE` 切換語言（zh-TW / en）

## 新增 Telegram 命令

參考 `telegram_bot_multi.py` 中的現有 handler 模式，新增後需在 `main()` 中用 `add_handler(CommandHandler(...))` 註冊。

現有命令：`/start`、`/status`、`/sessions`、`/restart #session`、`/reload`

## Gotchas

### Claude Code Plan Mode 互動輪詢
- Plan mode 期間的選項（AskUserQuestion、ExitPlanMode）透過 **tmux 日誌輪詢**偵測並推送為 Telegram InlineKeyboard 按鈕
- `Stop` hook 不在 plan mode 期間觸發，改由 `interaction_polling_worker` 每 2 秒掃描 tmux 日誌尾部偵測選項
- 文字輸入選項（「Tell Claude what to change」「Type something.」）標記為 ✏️，選擇後提示使用者發送 `#session 回饋內容`
- 選項選擇透過 tmux 按鍵序列（Down × N + Enter），非文字輸入
- 防重複：hash + 30 秒冷卻

### Hook 配置
- Claude hooks 必須寫入 `settings.local.json`（不是 `config.json`）
- Gemini hooks 超時單位為**毫秒**（30000 = 30 秒）
- Gemini hook stdout 必須輸出有效 JSON（`{}`）
- hooks 自動生成，見 `cli_provider.py` 的 `configure_hooks()`

### Gemini CLI
- 目錄必須被信任才能載入 hooks（`GeminiProvider` 自動處理 `~/.gemini/trustedFolders.json`）
- 輸入框需要兩次 Enter 才能送出（`extra_enter` 屬性）
- 若 hook 未觸發，檢查 `.gemini/settings.json` 和 `~/.ai_bridge/logs/hook_debug_*.log`
- Gemini 互動選項格式為 `╭╰` 框框 + `│` 邊線 + `●` 標記，由 `_extract_options_gemini()` 獨立處理（與 Claude 的 `❯` 格式分開）

### Telegram 發送
- Markdown 解析失敗時自動 fallback 為純文字重發
- 按鈕 callback_data 三種前綴：`select_{session}:{num}`（互動輪詢選項，tmux 按鍵選擇）、`input_{session}:{num}`（文字輸入選項，標記 ✏️）、`choice_{session}:{num}`（一般確認選項，文字發送到佇列）
- 無 `#` 前綴的訊息會返回錯誤（無預設會話）

### 日誌管理
- 格式：`~/.ai_bridge/logs/{cli_type}_{name}.log`
- **自動輪替**：超過 10MB 截斷保留 5MB（每 30 分鐘檢查，常數在 `config.py` 的 `TmuxConfig`）
- **stop 清理**：`bridge.sh stop` 移除所有 hooks（`cleanup_hooks`）、終止 tmux 會話、刪除會話日誌和 hook debug 日誌

### 其他
- 會話名稱模式：`[\w\-]+`
- `shlex.quote()` 防護 shell 注入
- ALLOWED_USER_IDS 為必填，空白拒絕啟動
- 每用戶速率限制：5 秒內最多 3 則
- **翻譯檔**：`locales/zh-TW.json` + `locales/en.json`（Python 用）、`locales/zh-TW.sh` + `locales/en.sh`（Shell 用）。新增字串需同時更新四個語言檔
- **登入由使用者自行處理**：本專案僅負責 Telegram ↔ CLI 的訊息轉發，不處理 Claude Code 或 Gemini CLI 的登入/認證。使用前須確保 CLI 已完成登入（`claude` / `gemini` 可正常執行）

### i18n 開發注意事項
- 所有使用者可見字串用 `t('module.key', var=value)` — 不要硬編碼中文或英文
- `notify_telegram.sh` 被 hook 獨立調用，內部呼叫 `send_telegram_notification.py`，後者需自行 `i18n.init()`（不共享 bot 的初始化）
- Python 中避免用 `t` 作為迴圈變數名（與 `from i18n import t` 衝突）
- `.env` 新增設定時，需在 `bridge.sh` 的 `do_validate()` 加入檢查並提醒使用者

### bridge.sh 注意事項
- 腳本使用 `set -euo pipefail`，`grep` 找不到結果時會返回非零退出碼導致腳本退出
- 需要 grep 可能無結果的場景，用 `set +o pipefail` / `set -o pipefail` 包裹
- Shell 翻譯變數含 `%s` 佔位符，使用時搭配 `printf`：`info "$(printf "$MSG_VAR" "$val")"`

## 故障排除

```bash
# Hook 未觸發
cat /path/to/project/.claude/settings.local.json  # Claude
cat /path/to/project/.gemini/settings.json         # Gemini
cat ~/.ai_bridge/logs/hook_debug_*.log             # debug log

# 會話問題
tmux ls                                            # 檢查 tmux 會話
./bridge.sh logs session_name                      # 查看會話日誌

# 測試 hook
export TELEGRAM_SESSION_NAME=test TELEGRAM_CLI_TYPE=claude
echo '{"last_assistant_message": "test"}' | ./notify_telegram.sh
```
