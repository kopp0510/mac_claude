#!/usr/bin/env python3
"""
配置模組測試
"""

import pytest
from config import config, patterns, AppConfig, TelegramConfig, MonitorConfig


class TestConfig:
    """配置類測試"""

    def test_telegram_config_defaults(self):
        """測試 Telegram 配置預設值"""
        tc = TelegramConfig()
        assert tc.MAX_MESSAGE_LENGTH == 4000
        assert tc.MAX_TOTAL_LENGTH == 12000
        assert tc.API_TIMEOUT == 10
        assert tc.MAX_RETRIES == 3

    def test_monitor_config_defaults(self):
        """測試監控配置預設值"""
        mc = MonitorConfig()
        assert mc.IDLE_TIMEOUT == 8.0
        assert mc.POLL_INTERVAL == 0.2
        assert mc.MAX_BUFFER_SIZE == 100000

    def test_app_config_instance(self):
        """測試全域配置實例"""
        assert config is not None
        assert config.telegram is not None
        assert config.monitor is not None
        assert config.tmux is not None


class TestPatterns:
    """正則表達式模式測試"""

    def test_ansi_escape_pattern(self):
        """測試 ANSI 轉義碼匹配"""
        test_text = "\x1b[32mGreen\x1b[0m"
        cleaned = patterns.ANSI_ESCAPE.sub('', test_text)
        assert cleaned == "Green"

    def test_control_chars_pattern(self):
        """測試控制字元匹配"""
        test_text = "Hello\x00World\x0BTest"
        cleaned = patterns.CONTROL_CHARS.sub('', test_text)
        assert cleaned == "HelloWorldTest"

    def test_multiple_newlines_pattern(self):
        """測試多餘空行匹配"""
        test_text = "Line1\n\n\n\nLine2"
        cleaned = patterns.MULTIPLE_NEWLINES.sub('\n\n', test_text)
        assert cleaned == "Line1\n\nLine2"

    def test_confirmation_option_pattern(self):
        """測試確認選項匹配"""
        # 測試標準選項
        match = patterns.CONFIRMATION_OPTION.match("  1. Yes")
        assert match is not None
        assert match.group(1) == "1"
        assert match.group(2) == "Yes"

        # 測試帶符號選項
        match = patterns.CONFIRMATION_OPTION.match("❯ 2. No")
        assert match is not None
        assert match.group(1) == "2"

    def test_session_name_pattern(self):
        """測試會話名稱模式"""
        assert patterns.SESSION_NAME.match("webapp") is not None
        assert patterns.SESSION_NAME.match("mac_claude") is not None
        assert patterns.SESSION_NAME.match("test-123") is not None
        assert patterns.SESSION_NAME.match("invalid name") is None

    def test_message_route_pattern(self):
        """測試訊息路由模式"""
        match = patterns.MESSAGE_ROUTE.match("#webapp hello world")
        assert match is not None
        assert match.group(1) == "webapp"
        assert match.group(2) == "hello world"

    def test_box_chars_pattern(self):
        """測試框線字元模式"""
        assert patterns.BOX_CHARS.match("│") is not None
        assert patterns.BOX_CHARS.match("╭─────╮") is not None
        assert patterns.BOX_CHARS.match("Hello") is None
