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

    # 互動偵測輪詢
    POLL_INTERVAL: float = 2.0      # 輪詢間隔（秒）


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
class TelegramConfig:
    """Telegram 相關配置"""
    MAX_SEND_LENGTH: int = 4000      # Telegram 發送訊息長度上限


@dataclass
class StatusConfig:
    """會話狀態追蹤配置"""
    STATUS_DIR: str = os.path.expanduser("~/.ai_bridge/status")


@dataclass
class ChainConfig:
    """會話串接配置"""
    CHAIN_DIR: str = os.path.expanduser("~/.ai_bridge/chains")
    CHAIN_TTL_SECONDS: int = 3600    # chain 檔過期時間（1小時）
    MAX_CHAIN_DEPTH: int = 5         # 最大串接段數（含起始節點，即最多 4 次轉發）


@dataclass
class AppConfig:
    """應用程式總配置"""
    tmux: TmuxConfig = field(default_factory=TmuxConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    status: StatusConfig = field(default_factory=StatusConfig)
    chain: ChainConfig = field(default_factory=ChainConfig)

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

    # Claude Code 確認選項模式（❯ 1. xxx 或 1.xxx）
    CONFIRMATION_OPTION = re.compile(r'^\s*[❯]?\s*(\d+)\.\s*(.+)')

    # Gemini CLI 確認選項模式（● 1. xxx，框線已移除後）
    GEMINI_OPTION = re.compile(r'^\s*[●]?\s*(\d+)\.\s*(.*\S)')

    # 會話名稱模式
    SESSION_NAME = re.compile(r'^[\w\-]+$')

    # 訊息路由模式
    MESSAGE_ROUTE = re.compile(r'^#([\w\-]+)\s+(.+)$', re.DOTALL)

    # 串接偵測模式（偵測 >> #session 語法）
    CHAIN_DETECT = re.compile(r'\s+>>\s+#')

    # 串接分割模式
    CHAIN_SPLIT = re.compile(r'\s+>>\s+')

    # 串接目標解析模式（#session [可選前綴]）
    CHAIN_TARGET = re.compile(r'^#([\w\-]+)(?:\s+(.+))?$', re.DOTALL)

    # 框線字元
    BOX_CHARS = re.compile(r'^[│╭╮╰╯├─┤┼]+\s*$')


    # Session 名稱安全性驗證（檔案操作前必須呼叫）
    @staticmethod
    def is_safe_session_name(name: str) -> bool:
        """驗證 session 名稱不含路徑穿越字元"""
        return bool(CompiledPatterns.SESSION_NAME.match(name))


# 預編譯模式實例
patterns = CompiledPatterns()
