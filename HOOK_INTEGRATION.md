# Claude Code Hook 整合說明

## 概述

本專案已整合 Claude Code 的 Stop hook 機制，實現**事件驅動**的 Telegram 通知，取代原先的輪詢機制。

## 架構變更

### 之前（輪詢機制）
```
Claude 輸出 → tmux pipe-pane → 日誌文件
           → OutputMonitor 輪詢（8秒超時）
           → Telegram
```
**問題**：延遲高（8秒）、需要持續輪詢、可能錯過或截斷輸出

### 之後（Hook 機制）
```
Claude 完成回應 → Stop hook 觸發
                → notify_telegram.sh
                → 解析 transcript.json
                → send_telegram_notification.py
                → Telegram Bot API
                → 用戶收到通知
```
**優勢**：
- ✅ **即時**：延遲 < 1 秒
- ✅ **準確**：直接從 transcript.json 獲取完整訊息
- ✅ **可靠**：不依賴輪詢和超時偵測
- ✅ **高效**：事件驅動，無需持續監控文件

## 新增檔案

### 1. `notify_telegram.sh`
Claude Code hook 腳本，當 Claude 完成回應時自動執行。

**功能**：
- 從 stdin 接收 hook 數據（JSON）
- 透過環境變數 `TELEGRAM_SESSION_NAME` 識別會話
- 解析 `transcript.json` 提取最後的 assistant 訊息
- 呼叫 `send_telegram_notification.py` 發送

**環境變數**：
- `TELEGRAM_SESSION_NAME`：由 `.claude/config.json` 配置傳入
- `TELEGRAM_BOT_TOKEN`：從 `.env` 讀取
- `TELEGRAM_CHAT_ID`：從 `ALLOWED_USER_IDS` 讀取

### 2. `send_telegram_notification.py`
獨立的 Telegram 發送器，直接呼叫 Bot API。

**功能**：
- 讀取 `.env` 配置
- 格式化訊息（Markdown、截斷）
- 發送到所有授權用戶
- 處理錯誤和超時

**參數**：
```bash
./send_telegram_notification.py <session_name> <message>
```

### 3. `test_hook.sh`
測試腳本，驗證 hook 整合是否正常。

**用法**：
```bash
./test_hook.sh
# 會創建測試 transcript 並模擬 hook 執行
# 應該在 Telegram 收到測試訊息
```

## 程式碼變更

### `tmux_bridge.py`
新增 `_configure_claude_hooks()` 方法：
- 在創建 tmux 會話時自動配置 hooks
- 寫入 `.claude/config.json` 到專案目錄
- 設置 Stop hook 觸發 `notify_telegram.sh`
- 透過 `env` 欄位傳遞 `TELEGRAM_SESSION_NAME`

**關鍵變更**：
```python
def create_session(self, work_dir=None, session_alias=None):
    # ...
    self._configure_claude_hooks(work_dir, session_alias or self.session_name)
    # ...

def _configure_claude_hooks(self, work_dir, session_name):
    # 寫入 .claude/config.json
    hook_config = {
        "hooks": {
            "Stop": [{
                "type": "command",
                "command": "/path/to/notify_telegram.sh",
                "env": {"TELEGRAM_SESSION_NAME": session_name}
            }]
        }
    }
```

### `session_manager.py`
更新 `create_all_sessions()` 和 `restart_session()`：
- 傳遞 `session_alias` 參數給 `create_session()`
- 確保 hook 配置使用正確的會話名稱

### `requirements.txt`
新增依賴：
- `requests>=2.31.0`：用於 Telegram Bot API 呼叫

### `CLAUDE.md`
更新文檔：
- 新增資料流程圖（Hook 機制）
- 新增核心元件說明
- 新增關鍵架構決策
- 新增 Hook 配置說明
- 新增故障排除步驟
- 新增測試流程

## 配置檔案

### 專案目錄的 `.claude/config.json`（自動生成）
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

## 測試步驟

### 1. 基本驗證
```bash
# 檢查腳本權限
ls -la notify_telegram.sh send_telegram_notification.py

# 應該看到：
# -rwxr-xr-x  notify_telegram.sh
# -rwxr-xr-x  send_telegram_notification.py
```

### 2. 獨立測試 Hook 腳本
```bash
./test_hook.sh
# 按 Enter 後應該在 Telegram 收到測試訊息
```

### 3. 端到端測試
```bash
# 1. 啟動 bot
./start_bridge.sh

# 2. 檢查 hook 配置
cat /path/to/project/.claude/config.json

# 3. 在 Telegram 發送訊息
#lottery_api hello

# 4. 應該立即收到 Claude 回應（< 1秒）
```

### 4. 驗證舊機制備用
```bash
# 移除 hook 配置測試 OutputMonitor 是否仍能工作
mv /path/.claude/config.json /path/.claude/config.json.bak
# 重啟會話並測試（應該延遲約8秒收到訊息）
# 恢復配置
mv /path/.claude/config.json.bak /path/.claude/config.json
```

## 故障排除

### Hook 未觸發
1. 檢查 `.claude/config.json` 存在且格式正確
2. 檢查 `notify_telegram.sh` 有執行權限
3. 連接到 tmux 會話查看錯誤訊息：`tmux attach -t claude-session_name`

### 收不到 Telegram 通知
1. 驗證 `.env` 中的 `TELEGRAM_BOT_TOKEN` 正確
2. 驗證 `ALLOWED_USER_IDS` 包含你的 chat ID
3. 手動執行 `./test_hook.sh` 測試

### Python 模組錯誤
```bash
# 安裝依賴
pip install -r requirements.txt

# 驗證
python3 -c "import requests; import dotenv; print('OK')"
```

## 向後相容性

**OutputMonitor 保留**：
- 用於 `/buffer` 命令查詢歷史輸出
- 作為 hook 失敗時的備用機制
- 未來可以考慮完全移除輪詢邏輯

**現有功能不受影響**：
- 所有 Telegram 命令仍正常運作
- 會話管理和路由機制不變
- 熱重載功能正常

## 未來改進

1. **移除 OutputMonitor 輪詢**：hook 穩定後可完全依賴事件驅動
2. **支援更多 Hook 事件**：
   - `PreToolUse`：工具使用前通知
   - `Notification`：Claude 主動通知
3. **訊息格式優化**：利用 transcript 的結構化數據改善格式
4. **錯誤處理增強**：hook 失敗時的重試機制

## 相關文檔

- [Claude Code Hooks 官方文檔](https://docs.claude.com/en/docs/claude-code/hooks)
- [CLAUDE.md](./CLAUDE.md)：完整專案文檔
- [README.md](./README.md)：快速開始指南
