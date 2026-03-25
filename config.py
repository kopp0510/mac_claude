#!/usr/bin/env python3
"""
配置管理模組
集中管理所有配置參數，消除魔數
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TmuxConfig:
    """Tmux 相關配置"""
    # 日誌設定
    LOG_DIR: str = os.path.expanduser("~/.ai_bridge/logs")  # 日誌目錄
    LOG_FILE_MODE: int = 0o600      # 日誌文件權限（只有擁有者可讀寫）
    LOG_MAX_SIZE: int = 10 * 1024 * 1024   # 10MB 觸發截斷
    LOG_KEEP_SIZE: int = 5 * 1024 * 1024   # 截斷後保留 5MB
    LOG_CHECK_INTERVAL: int = 1800         # 檢查間隔 30 分鐘

    # 會話設定
    SESSION_INIT_DELAY: float = 2.0 # 會話初始化等待時間（秒）
    COMMAND_DELAY: float = 1.0      # 命令間延遲（秒）


@dataclass
class QueueConfig:
    """佇列相關配置"""
    MESSAGE_QUEUE_SIZE: int = 1000  # 訊息佇列大小限制
    QUEUE_TIMEOUT: float = 1.0      # 佇列讀取超時（秒）


@dataclass
class SecurityConfig:
    """安全相關配置"""
    # 輸入驗證
    MAX_MESSAGE_LENGTH: int = 10000     # 最大輸入訊息長度


@dataclass
class AppConfig:
    """應用程式總配置"""
    tmux: TmuxConfig = field(default_factory=TmuxConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)

    # 環境變數
    @property
    def bot_token(self) -> Optional[str]:
        return os.getenv('TELEGRAM_BOT_TOKEN')

    @property
    def allowed_user_ids(self) -> List[str]:
        ids = os.getenv('ALLOWED_USER_IDS', '')
        return [uid.strip() for uid in ids.split(',') if uid.strip()]

    @property
    def sessions_config_file(self) -> str:
        return os.getenv('SESSIONS_CONFIG_FILE', 'sessions.yaml')


# 全域配置實例
config = AppConfig()


class CompiledPatterns:
    """預編譯的正則表達式"""
    # ANSI 控制碼（含 OSC 序列如 0;⠐ 標題設置）
    ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*\x07?)')

    # 控制字元（保留換行和 tab）
    CONTROL_CHARS = re.compile(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]')

    # 多餘空行
    MULTIPLE_NEWLINES = re.compile(r'\n{3,}')

    # 確認選項模式
    CONFIRMATION_OPTION = re.compile(r'^\s*[❯]?\s*(\d+)\.\s*(.+)')

    # 會話名稱模式
    SESSION_NAME = re.compile(r'^[\w\-]+$')

    # 訊息路由模式
    MESSAGE_ROUTE = re.compile(r'^#([\w\-]+)\s+(.+)$', re.DOTALL)

    # 框線字元
    BOX_CHARS = re.compile(r'^[│╭╮╰╯├─┤┼]+\s*$')


# 預編譯模式實例
patterns = CompiledPatterns()
