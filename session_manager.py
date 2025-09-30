#!/usr/bin/env python3
"""
Session Manager - 管理多個 Claude Code tmux 會話
"""

import logging
from typing import Dict, List, Optional
from tmux_bridge import TmuxBridge

logger = logging.getLogger(__name__)


class SessionConfig:
    """會話配置"""

    def __init__(self, name: str, path: str, tmux_session: str):
        self.name = name
        self.path = path
        self.tmux_session = tmux_session
        self.log_file = f"/tmp/claude_{name}.log"


class SessionManager:
    """管理多個 Claude Code 會話"""

    def __init__(self):
        self.sessions: Dict[str, SessionConfig] = {}
        self.bridges: Dict[str, TmuxBridge] = {}

    def add_session(self, name: str, path: str, tmux_session: str = None):
        """
        添加一個會話

        Args:
            name: 會話名稱（用於 #name 路由）
            path: 工作目錄
            tmux_session: tmux 會話名稱（如果不提供，使用 name）
        """
        if tmux_session is None:
            tmux_session = f"claude-{name}"

        config = SessionConfig(name, path, tmux_session)
        self.sessions[name] = config

        # 創建對應的 TmuxBridge
        bridge = TmuxBridge(session_name=tmux_session, log_file=config.log_file)
        self.bridges[name] = bridge

        logger.info(f"✅ 添加會話: {name} @ {path}")

    def get_session(self, name: str) -> Optional[SessionConfig]:
        """獲取會話配置"""
        return self.sessions.get(name)

    def get_bridge(self, name: str) -> Optional[TmuxBridge]:
        """獲取 tmux 橋接"""
        return self.bridges.get(name)

    def get_all_sessions(self) -> List[str]:
        """獲取所有會話名稱"""
        return list(self.sessions.keys())

    def create_all_sessions(self) -> bool:
        """創建所有 tmux 會話"""
        success = True

        for name, config in self.sessions.items():
            bridge = self.bridges[name]

            if not bridge.session_exists():
                logger.info(f"📝 創建會話: {name}")
                if not bridge.create_session(work_dir=config.path):
                    logger.error(f"❌ 創建會話失敗: {name}")
                    success = False
            else:
                logger.info(f"✅ 會話已存在: {name}")

        return success

    def send_to_session(self, name: str, message: str) -> bool:
        """
        發送訊息到指定會話

        Args:
            name: 會話名稱
            message: 訊息內容

        Returns:
            bool: 是否成功
        """
        bridge = self.bridges.get(name)
        if not bridge:
            logger.error(f"❌ 找不到會話: {name}")
            return False

        return bridge.send_command(message)

    def send_to_all(self, message: str) -> Dict[str, bool]:
        """
        發送訊息到所有會話

        Args:
            message: 訊息內容

        Returns:
            dict: {session_name: success}
        """
        results = {}
        for name in self.sessions.keys():
            results[name] = self.send_to_session(name, message)

        return results

    def get_status(self) -> Dict[str, dict]:
        """
        獲取所有會話的狀態

        Returns:
            dict: {session_name: status_info}
        """
        status = {}

        for name, bridge in self.bridges.items():
            config = self.sessions[name]
            status[name] = {
                'name': name,
                'path': config.path,
                'tmux_session': config.tmux_session,
                'log_file': config.log_file,
                'exists': bridge.session_exists(),
                'status': bridge.get_status()
            }

        return status

    def kill_session(self, name: str) -> bool:
        """終止指定會話"""
        bridge = self.bridges.get(name)
        if not bridge:
            return False

        return bridge.kill_session()

    def kill_all_sessions(self):
        """終止所有會話"""
        for name in self.sessions.keys():
            self.kill_session(name)

    def restart_session(self, name: str) -> bool:
        """
        重啟指定會話

        Args:
            name: 會話名稱

        Returns:
            bool: 是否成功
        """
        config = self.sessions.get(name)
        bridge = self.bridges.get(name)

        if not config or not bridge:
            logger.error(f"❌ 找不到會話: {name}")
            return False

        logger.info(f"🔄 重啟會話: {name}")

        # 終止舊會話
        if bridge.session_exists():
            logger.info(f"  終止舊會話: {config.tmux_session}")
            bridge.kill_session()

        # 創建新會話
        logger.info(f"  創建新會話: {config.tmux_session}")
        if bridge.create_session(work_dir=config.path):
            logger.info(f"✅ 會話重啟成功: {name}")
            return True
        else:
            logger.error(f"❌ 會話重啟失敗: {name}")
            return False


if __name__ == '__main__':
    # 測試代碼
    manager = SessionManager()

    # 添加測試會話
    manager.add_session('project1', '/Users/danlio/project1')
    manager.add_session('project2', '/Users/danlio/project2')

    # 顯示狀態
    status = manager.get_status()
    for name, info in status.items():
        print(f"\n會話: {name}")
        print(f"  路徑: {info['path']}")
        print(f"  tmux: {info['tmux_session']}")
        print(f"  存在: {info['exists']}")