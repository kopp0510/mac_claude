#!/usr/bin/env python3
"""
Tmux 橋接管理模組
管理 tmux 會話，處理輸入注入和輸出監控
"""

import os
import subprocess
import time
import re
from pathlib import Path


class TmuxBridge:
    """Tmux 橋接管理器"""

    def __init__(self, session_name="claude", log_file="/tmp/claude_tmux.log"):
        self.session_name = session_name
        self.log_file = log_file
        self.last_read_position = 0

    def check_tmux_installed(self):
        """檢查 tmux 是否已安裝"""
        try:
            result = subprocess.run(
                ['which', 'tmux'],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception:
            return False

    def session_exists(self):
        """檢查 tmux 會話是否存在"""
        try:
            result = subprocess.run(
                ['tmux', 'has-session', '-t', self.session_name],
                capture_output=True
            )
            return result.returncode == 0
        except Exception:
            return False

    def create_session(self, work_dir=None):
        """
        創建 tmux 會話並啟動 Claude Code

        Args:
            work_dir: 工作目錄

        Returns:
            bool: 是否成功
        """
        if not self.check_tmux_installed():
            raise Exception("tmux 未安裝。請執行: brew install tmux")

        if self.session_exists():
            print(f"⚠️  tmux 會話 '{self.session_name}' 已存在")
            return True

        try:
            # 清理舊的日誌檔案
            if os.path.exists(self.log_file):
                os.remove(self.log_file)

            # 創建 tmux 會話（detached 模式）
            cmd = ['tmux', 'new-session', '-d', '-s', self.session_name]

            if work_dir:
                cmd.extend(['-c', work_dir])

            subprocess.run(cmd, check=True)

            # 啟動日誌記錄
            subprocess.run([
                'tmux', 'pipe-pane', '-t', self.session_name,
                '-o', f'cat >> {self.log_file}'
            ], check=True)

            # 在會話中啟動 claude
            time.sleep(0.5)  # 等待會話初始化
            self.send_command('claude')

            print(f"✅ tmux 會話 '{self.session_name}' 已創建")
            print(f"📝 日誌文件: {self.log_file}")

            return True

        except subprocess.CalledProcessError as e:
            print(f"❌ 創建 tmux 會話失敗: {e}")
            return False

    def send_command(self, command):
        """
        發送命令到 tmux 會話

        Args:
            command: 要發送的命令
        """
        if not self.session_exists():
            raise Exception(f"tmux 會話 '{self.session_name}' 不存在")

        try:
            # 使用 send-keys 發送命令
            # 使用 -l 來發送字面文字，避免特殊字元被解釋
            subprocess.run([
                'tmux', 'send-keys', '-t', self.session_name, '-l',
                command
            ], check=True)

            # 然後發送 Enter 鍵
            subprocess.run([
                'tmux', 'send-keys', '-t', self.session_name,
                'Enter'
            ], check=True)

            return True

        except subprocess.CalledProcessError as e:
            print(f"❌ 發送命令失敗: {e}")
            return False

    def send_text(self, text):
        """
        發送文字到 tmux 會話（不自動按 Enter）

        Args:
            text: 要發送的文字
        """
        if not self.session_exists():
            raise Exception(f"tmux 會話 '{self.session_name}' 不存在")

        try:
            subprocess.run([
                'tmux', 'send-keys', '-t', self.session_name,
                '-l', text
            ], check=True)

            return True

        except subprocess.CalledProcessError as e:
            print(f"❌ 發送文字失敗: {e}")
            return False

    def read_new_output(self):
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
            print(f"❌ 讀取日誌失敗: {e}")
            return ""

    def get_full_output(self):
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
            print(f"❌ 讀取日誌失敗: {e}")
            return ""

    def attach_session(self):
        """附加到 tmux 會話（進入互動模式）"""
        if not self.session_exists():
            print(f"❌ tmux 會話 '{self.session_name}' 不存在")
            return False

        try:
            subprocess.run(['tmux', 'attach-session', '-t', self.session_name])
            return True
        except Exception as e:
            print(f"❌ 附加會話失敗: {e}")
            return False

    def kill_session(self):
        """終止 tmux 會話"""
        if not self.session_exists():
            return True

        try:
            subprocess.run(['tmux', 'kill-session', '-t', self.session_name])
            print(f"🛑 tmux 會話 '{self.session_name}' 已終止")

            # 清理日誌文件
            if os.path.exists(self.log_file):
                os.remove(self.log_file)

            return True

        except Exception as e:
            print(f"❌ 終止會話失敗: {e}")
            return False

    def get_status(self):
        """
        獲取會話狀態

        Returns:
            dict: 狀態資訊
        """
        return {
            "tmux_installed": self.check_tmux_installed(),
            "session_exists": self.session_exists(),
            "session_name": self.session_name,
            "log_file": self.log_file,
            "log_exists": os.path.exists(self.log_file),
            "log_size": os.path.getsize(self.log_file) if os.path.exists(self.log_file) else 0
        }


if __name__ == '__main__':
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