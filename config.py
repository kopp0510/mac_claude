#!/usr/bin/env python3
"""
配置管理模組
集中管理所有配置參數，消除魔數
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TelegramConfig:
    """Telegram 相關配置"""
    # 訊息長度限制
    MAX_MESSAGE_LENGTH: int = 4000  # Telegram 單條訊息最大長度
    MAX_TOTAL_LENGTH: int = 12000   # 超過這個長度上傳為文件

    # API 配置
    API_TIMEOUT: int = 10           # API 請求超時（秒）
    MAX_RETRIES: int = 3            # 最大重試次數
    RETRY_DELAY: float = 1.0        # 重試延遲（秒）
    RETRY_BACKOFF: float = 2.0      # 重試退避倍數


@dataclass
class MonitorConfig:
    """監控相關配置"""
    # 超時設定
    IDLE_TIMEOUT: float = 8.0       # 閒置超時（秒）
    CONFIRMATION_TIMEOUT: float = 15.0  # 確認提示等待超時（秒）
    POLL_INTERVAL: float = 0.2      # 輪詢間隔（秒）

    # 緩衝區設定
    MAX_BUFFER_SIZE: int = 100000   # 最大緩衝區大小（字元）
    MAX_BUFFER_LINES: int = 10000   # 最大緩衝區行數

    # 內容過濾
    MIN_RESPONSE_LENGTH: int = 10   # 最小回應長度
    MIN_USER_INPUT_LENGTH: int = 20 # 判斷為用戶輸入的最小長度


@dataclass
class TmuxConfig:
    """Tmux 相關配置"""
    # 日誌設定
    LOG_DIR: str = os.path.expanduser("~/.claude_bridge/logs")  # 日誌目錄
    LOG_FILE_MODE: int = 0o600      # 日誌文件權限（只有擁有者可讀寫）

    # 會話設定
    SESSION_INIT_DELAY: float = 2.0 # 會話初始化等待時間（秒）
    COMMAND_DELAY: float = 1.0      # 命令間延遲（秒）


@dataclass
class QueueConfig:
    """佇列相關配置"""
    MESSAGE_QUEUE_SIZE: int = 1000  # 訊息佇列大小限制
    OUTPUT_QUEUE_SIZE: int = 1000   # 輸出佇列大小限制
    QUEUE_TIMEOUT: float = 1.0      # 佇列讀取超時（秒）


@dataclass
class SecurityConfig:
    """安全相關配置"""
    # 輸入驗證
    MAX_MESSAGE_LENGTH: int = 10000     # 最大輸入訊息長度
    MAX_SESSION_NAME_LENGTH: int = 50   # 最大會話名稱長度
    ALLOWED_SESSION_PATTERN: str = r'^[\w\-]+$'  # 允許的會話名稱模式


@dataclass
class AppConfig:
    """應用程式總配置"""
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
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


# 預編譯的正則表達式（用於提升效能）
import re

class CompiledPatterns:
    """預編譯的正則表達式"""
    # ANSI 控制碼（含 OSC 序列如 0;⠐ 標題設置）
    ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*\x07?)')

    # 控制字元（保留換行和 tab）
    CONTROL_CHARS = re.compile(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]')

    # Claude Code CLI spinner 和標題碼（如 0;⠐ xxx、0;✳ xxx）
    CLI_TITLE_CODE = re.compile(r'^0;[⠐⠂⠈⠀⠄⠑⠊⠉✳⠃⠆⠇⠋⠌⠍⠎⠏⠘⠙⠚⠛⠜⠝⠞⠟⠠⠡⠢⠣⠤⠥⠦⠧⠨⠩⠪⠫⠬⠭⠮⠯⠰⠱⠲⠳⠴⠵⠶⠷⠸⠹⠺⠻⠼⠽⠾⠿].*', re.MULTILINE)

    # Claude Code CLI 狀態行（各種變體：In: X | Out: X、數字 | Cached:、T... 等）
    CLI_STATUS_LINE = re.compile(r'(In:|Out:|Cached:|Total:).*\|', re.MULTILINE)

    # 統計行殘留（數字開頭後接 | Cached 等）
    CLI_STATS_FRAGMENT = re.compile(r'^\s*\d+\s*\|.*(?:Cached|Out|In|Total)', re.MULTILINE)

    # cwd 行（各種變體）
    CLI_CWD_LINE = re.compile(r'(?:^|\s)(?:cwd:|Users/)\S*/project/\S*', re.MULTILINE)

    # T... 路徑截斷
    CLI_TRUNCATED_PATH = re.compile(r'T\.{3}\S*/\S*', re.MULTILINE)

    # 提示符行（只有 ❯ 或 > 和空白）
    CLI_PROMPT_LINE = re.compile(r'^\s*❯\s*$', re.MULTILINE)

    # 多餘空行
    MULTIPLE_NEWLINES = re.compile(r'\n{3,}')

    # 確認選項模式
    CONFIRMATION_OPTION = re.compile(r'^\s*[❯]?\s*(\d+)\.\s*(.+)')

    # 會話名稱模式
    SESSION_NAME = re.compile(r'^[\w\-]+$')

    # 訊息路由模式
    MESSAGE_ROUTE = re.compile(r'^#([\w\-]+)\s+(.+)$', re.DOTALL)

    # 框線字元
    BOX_CHARS = re.compile(r'^[│╭╰╯├─┤┼]+\s*$')

    # 工具調用
    TOOL_INVOKE = re.compile(r'<invoke name="([^"]+)">.*?</invoke>', re.DOTALL)

    # 處理狀態關鍵字
    PROCESSING_KEYWORDS = [
        'Whisking…', 'Wibbling…', 'Thinking…',
        'esc to interrupt', 'Press shift+tab',
        '? for shortcuts', 'Plan Mode',
        'Contemplating', 'Crafting',
        'Sprouting', 'Brewing', 'Pondering',
        'Gathering', 'Composing', 'Assembling',
        '(thinking)', 'thinking)',
    ]


# 預編譯模式實例
patterns = CompiledPatterns()
