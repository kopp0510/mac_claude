#!/usr/bin/env python3
"""
Tmux 橋接管理模組
管理 tmux 會話，處理輸入注入和輸出監控
"""

import os
import stat
import subprocess
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from config import config

logger = logging.getLogger(__name__)


class TmuxBridge:
    """Tmux 橋接管理器"""

    def __init__(self, session_name: str = "claude", log_file: Optional[str] = None):
        """
        初始化 Tmux 橋接管理器

        Args:
            session_name: tmux 會話名稱
            log_file: 日誌文件路徑（可選，預設為 /tmp/claude_{session_name}.log）
        """
        self.session_name = session_name
        self.log_file = log_file or f"{config.tmux.LOG_DIR}/claude_{session_name}.log"
        self.last_read_position = 0

    def check_tmux_installed(self) -> bool:
        """檢查 tmux 是否已安裝"""
        try:
            result = subprocess.run(
                ['which', 'tmux'],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"檢查 tmux 安裝失敗: {e}")
            return False

    def session_exists(self) -> bool:
        """檢查 tmux 會話是否存在"""
        try:
            result = subprocess.run(
                ['tmux', 'has-session', '-t', self.session_name],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"檢查會話存在失敗: {e}")
            return False

    def _set_secure_file_permissions(self, file_path: str) -> bool:
        """
        設置安全的文件權限

        Args:
            file_path: 文件路徑

        Returns:
            bool: 是否成功
        """
        try:
            os.chmod(file_path, config.tmux.LOG_FILE_MODE)
            return True
        except Exception as e:
            logger.warning(f"設置文件權限失敗 {file_path}: {e}")
            return False

    def _create_log_file(self) -> bool:
        """
        創建日誌文件並設置安全權限

        Returns:
            bool: 是否成功
        """
        try:
            # 確保目錄存在
            log_dir = os.path.dirname(self.log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, mode=0o700)

            # 如果文件存在，先刪除
            if os.path.exists(self.log_file):
                os.remove(self.log_file)

            # 創建新文件
            Path(self.log_file).touch()

            # 設置安全權限
            self._set_secure_file_permissions(self.log_file)

            return True
        except Exception as e:
            logger.error(f"創建日誌文件失敗: {e}")
            return False

    def create_session(self, work_dir: Optional[str] = None,
                       session_alias: Optional[str] = None) -> bool:
        """
        創建 tmux 會話並啟動 Claude Code

        Args:
            work_dir: 工作目錄
            session_alias: 會話別名（用於 hook 通知）

        Returns:
            bool: 是否成功
        """
        if not self.check_tmux_installed():
            logger.error("tmux 未安裝。請執行: brew install tmux")
            raise Exception("tmux 未安裝。請執行: brew install tmux")

        if self.session_exists():
            logger.warning(f"tmux 會話 '{self.session_name}' 已存在")
            return True

        try:
            # 創建日誌文件（安全權限）
            if not self._create_log_file():
                logger.warning("創建日誌文件失敗，繼續執行...")

            # 創建 tmux 會話（detached 模式）
            cmd = ['tmux', 'new-session', '-d', '-s', self.session_name]

            if work_dir:
                cmd.extend(['-c', work_dir])

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"創建 tmux 會話失敗: {result.stderr}")
                return False

            # 啟動日誌記錄
            result = subprocess.run([
                'tmux', 'pipe-pane', '-t', self.session_name,
                '-o', f'cat >> {self.log_file}'
            ], capture_output=True, text=True)

            if result.returncode != 0:
                logger.warning(f"啟動日誌記錄失敗: {result.stderr}")

            # 配置 Claude Code hooks
            self._configure_claude_hooks(work_dir, session_alias or self.session_name)

            # 等待會話初始化
            time.sleep(config.tmux.SESSION_INIT_DELAY)

            # 在會話中啟動 claude
            self.send_command('claude')

            logger.info(f"tmux 會話 '{self.session_name}' 已創建")
            logger.info(f"日誌文件: {self.log_file}")

            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"創建 tmux 會話失敗: {e}")
            return False
        except Exception as e:
            logger.error(f"創建會話時發生錯誤: {e}")
            return False

    def _configure_claude_hooks(self, work_dir: Optional[str],
                                 session_name: str) -> bool:
        """
        配置 Claude Code hooks

        Args:
            work_dir: 工作目錄
            session_name: 會話名稱（用於通知路由）

        Returns:
            bool: 是否成功
        """
        if not work_dir:
            return False

        try:
            # 獲取專案根目錄的 notify_telegram.sh 路徑
            script_dir = Path(__file__).parent.absolute()
            hook_script = script_dir / 'notify_telegram.sh'

            if not hook_script.exists():
                logger.warning(f"Hook script not found: {hook_script}")
                return False

            # 設置 Stop hook（當 Claude 完成回應時觸發）
            # hooks 必須寫入 settings.local.json（不是 config.json）
            # 格式：hooks.Stop[].hooks[] — 需要內層 hooks 陣列包裝
            # 環境變數透過 command 前綴傳遞
            hook_command = f"TELEGRAM_SESSION_NAME={session_name} {hook_script}"
            stop_hooks = [{
                "hooks": [{
                    "type": "command",
                    "command": hook_command,
                    "timeout": 30
                }]
            }]

            # 寫入 .claude/settings.local.json
            import json
            config_dir = Path(work_dir) / '.claude'
            config_dir.mkdir(exist_ok=True)

            settings_file = config_dir / 'settings.local.json'

            # 讀取現有設定（保留 permissions 等）
            existing_settings = {}
            if settings_file.exists():
                try:
                    with open(settings_file, 'r', encoding='utf-8') as f:
                        existing_settings = json.load(f)
                except Exception as e:
                    logger.warning(f"讀取現有設定失敗: {e}")

            # 合併 hooks 配置（保留其他設定不動）
            if 'hooks' not in existing_settings:
                existing_settings['hooks'] = {}

            existing_settings['hooks']['Stop'] = stop_hooks

            # 寫入設定
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(existing_settings, f, indent=2, ensure_ascii=False)

            logger.info(f"已配置 Claude Code hooks: {session_name}")
            return True

        except Exception as e:
            logger.warning(f"配置 hooks 失敗: {e}")
            return False

    def send_command(self, command: str) -> bool:
        """
        發送命令到 tmux 會話

        Args:
            command: 要發送的命令

        Returns:
            bool: 是否成功
        """
        if not self.session_exists():
            logger.error(f"tmux 會話 '{self.session_name}' 不存在")
            return False

        try:
            # 使用 send-keys 發送命令
            # 使用 -l 來發送字面文字，避免特殊字元被解釋
            result = subprocess.run([
                'tmux', 'send-keys', '-t', self.session_name, '-l',
                command
            ], capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"發送命令失敗: {result.stderr}")
                return False

            # 然後發送 Enter 鍵
            result = subprocess.run([
                'tmux', 'send-keys', '-t', self.session_name,
                'Enter'
            ], capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"發送 Enter 失敗: {result.stderr}")
                return False

            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"發送命令失敗: {e}")
            return False
        except Exception as e:
            logger.error(f"發送命令時發生錯誤: {e}")
            return False

    def send_text(self, text: str) -> bool:
        """
        發送文字到 tmux 會話（不自動按 Enter）

        Args:
            text: 要發送的文字

        Returns:
            bool: 是否成功
        """
        if not self.session_exists():
            logger.error(f"tmux 會話 '{self.session_name}' 不存在")
            return False

        try:
            result = subprocess.run([
                'tmux', 'send-keys', '-t', self.session_name,
                '-l', text
            ], capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"發送文字失敗: {result.stderr}")
                return False

            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"發送文字失敗: {e}")
            return False
        except Exception as e:
            logger.error(f"發送文字時發生錯誤: {e}")
            return False

    def read_new_output(self) -> str:
        """
        讀取新的輸出（從上次讀取位置開始）

        Returns:
            str: 新的輸出內容
        """
        if not os.path.exists(self.log_file):
            return ""

        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                # 移動到上次讀取的位置
                f.seek(self.last_read_position)

                # 讀取新內容
                new_content = f.read()

                # 更新讀取位置
                self.last_read_position = f.tell()

                return new_content

        except Exception as e:
            logger.error(f"讀取日誌失敗: {e}")
            return ""

    def get_full_output(self) -> str:
        """
        獲取完整的輸出內容

        Returns:
            str: 完整輸出
        """
        if not os.path.exists(self.log_file):
            return ""

        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            logger.error(f"讀取日誌失敗: {e}")
            return ""

    def attach_session(self) -> bool:
        """附加到 tmux 會話（進入互動模式）"""
        if not self.session_exists():
            logger.error(f"tmux 會話 '{self.session_name}' 不存在")
            return False

        try:
            subprocess.run(['tmux', 'attach-session', '-t', self.session_name])
            return True
        except Exception as e:
            logger.error(f"附加會話失敗: {e}")
            return False

    def kill_session(self) -> bool:
        """終止 tmux 會話"""
        if not self.session_exists():
            return True

        try:
            result = subprocess.run(
                ['tmux', 'kill-session', '-t', self.session_name],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                logger.error(f"終止會話失敗: {result.stderr}")
                return False

            logger.info(f"tmux 會話 '{self.session_name}' 已終止")

            # 安全地清理日誌文件
            if os.path.exists(self.log_file):
                try:
                    os.remove(self.log_file)
                except Exception as e:
                    logger.warning(f"清理日誌文件失敗: {e}")

            return True

        except Exception as e:
            logger.error(f"終止會話失敗: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """
        獲取會話狀態

        Returns:
            dict: 狀態資訊
        """
        log_exists = os.path.exists(self.log_file)
        log_size = 0
        log_permissions = None

        if log_exists:
            try:
                stat_info = os.stat(self.log_file)
                log_size = stat_info.st_size
                log_permissions = oct(stat_info.st_mode)[-3:]
            except Exception:
                pass

        return {
            "tmux_installed": self.check_tmux_installed(),
            "session_exists": self.session_exists(),
            "session_name": self.session_name,
            "log_file": self.log_file,
            "log_exists": log_exists,
            "log_size": log_size,
            "log_permissions": log_permissions
        }


if __name__ == '__main__':
    # 設置日誌
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    # 測試代碼
    bridge = TmuxBridge()

    print("📊 狀態檢查:")
    status = bridge.get_status()
    for key, value in status.items():
        print(f"  {key}: {value}")

    if not status['tmux_installed']:
        print("\n❌ 請先安裝 tmux: brew install tmux")
    elif not status['session_exists']:
        print("\n💡 可以使用 bridge.create_session() 創建會話")
