#!/usr/bin/env python3
"""
Session Manager - 管理多個 Claude Code tmux 會話
"""

import logging
from typing import Dict, List, Optional
from tmux_bridge import TmuxBridge
from cli_provider import CliProvider, ClaudeProvider, create_provider
from i18n import t

logger = logging.getLogger(__name__)


class SessionConfig:
    """會話配置"""

    def __init__(self, name: str, path: str, tmux_session: str,
                 cli_args: str = "", cli_type: str = "claude"):
        from config import config as app_config
        self.name = name
        self.path = path
        self.tmux_session = tmux_session
        self.cli_args = cli_args
        self.cli_type = cli_type
        self.log_file = f"{app_config.tmux.LOG_DIR}/{cli_type}_{name}.log"


class SessionManager:
    """管理多個 Claude Code 會話"""

    def __init__(self):
        self.sessions: Dict[str, SessionConfig] = {}
        self.bridges: Dict[str, TmuxBridge] = {}

    def add_session(self, name: str, path: str, tmux_session: str = None,
                    cli_args: str = "", cli_type: str = "claude"):
        """
        添加一個會話

        Args:
            name: 會話名稱（用於 #name 路由）
            path: 工作目錄
            tmux_session: tmux 會話名稱（如果不提供，使用 provider 預設前綴）
            cli_args: CLI 啟動參數（如 --model sonnet）
            cli_type: CLI 類型（claude 或 gemini）
        """
        provider = create_provider(cli_type)

        if tmux_session is None:
            tmux_session = f"{provider.default_tmux_prefix}{name}"

        config = SessionConfig(name, path, tmux_session, cli_args, cli_type)
        self.sessions[name] = config

        # 創建對應的 TmuxBridge（注入 CLI Provider）
        bridge = TmuxBridge(session_name=tmux_session, log_file=config.log_file,
                            cli_provider=provider)
        self.bridges[name] = bridge

        logger.info(t('session.added', name=name, path=path, cli_type=cli_type))

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
                logger.info(t('session.creating', name=name))
                if not bridge.create_session(work_dir=config.path,
                                             session_alias=name,
                                             cli_args=config.cli_args):
                    logger.error(t('session.create_failed', name=name))
                    success = False
            else:
                logger.info(t('session.already_exists', name=name))

        return success

    def send_to_session(self, name: str, message: str) -> bool:
        """發送訊息到指定會話"""
        bridge = self.bridges.get(name)
        if not bridge:
            logger.error(t('session.send_not_found', name=name))
            return False

        return bridge.send_command(message)

    def send_to_all(self, message: str) -> Dict[str, bool]:
        """發送訊息到所有會話"""
        return {name: self.send_to_session(name, message) for name in self.sessions}

    def get_status(self) -> Dict[str, dict]:
        """獲取所有會話的狀態"""
        status = {}

        for name, bridge in self.bridges.items():
            config = self.sessions[name]
            status[name] = {
                'name': name,
                'path': config.path,
                'tmux_session': config.tmux_session,
                'log_file': config.log_file,
                'cli_args': config.cli_args,
                'cli_type': config.cli_type,
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
        for name in self.sessions:
            self.kill_session(name)

    def restart_session(self, name: str) -> bool:
        """重啟指定會話"""
        config = self.sessions.get(name)
        bridge = self.bridges.get(name)

        if not config or not bridge:
            logger.error(t('session.send_not_found', name=name))
            return False

        logger.info(t('session.restart_log', name=name))

        # 終止舊會話
        if bridge.session_exists():
            logger.info(t('session.kill_old', tmux=config.tmux_session))
            bridge.kill_session()

        # 創建新會話
        logger.info(t('session.create_new', tmux=config.tmux_session))
        if bridge.create_session(work_dir=config.path, session_alias=name,
                                 cli_args=config.cli_args):
            logger.info(t('session.restart_success_log', name=name))
            return True
        else:
            logger.error(t('session.restart_failed_log', name=name))
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