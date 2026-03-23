#!/usr/bin/env python3
"""
輸出監控模組測試
"""

import pytest
from output_monitor import OutputMonitor, MessageFormatter


class TestOutputMonitor:
    """OutputMonitor 類測試"""

    @pytest.fixture
    def monitor(self):
        """建立測試用的 OutputMonitor"""
        return OutputMonitor(None)

    def test_clean_ansi_codes(self, monitor):
        """測試 ANSI 控制碼清理"""
        text = "\x1b[32m綠色文字\x1b[0m"
        result = monitor.clean_ansi_codes(text)
        assert result == "綠色文字"

    def test_clean_ansi_codes_multiple(self, monitor):
        """測試多個 ANSI 控制碼"""
        text = "\x1b[1m\x1b[31mBold Red\x1b[0m Normal"
        result = monitor.clean_ansi_codes(text)
        assert result == "Bold Red Normal"

    def test_is_likely_user_input_short(self, monitor):
        """測試短文字判斷為用戶輸入"""
        assert monitor.is_likely_user_input("hi") is True
        assert monitor.is_likely_user_input("> cmd") is True

    def test_is_likely_user_input_processing(self, monitor):
        """測試處理狀態訊息判斷"""
        text = "Whisking… please wait"
        assert monitor.is_likely_user_input(text) is True

    def test_detect_confirmation_prompt(self, monitor):
        """測試確認提示檢測"""
        text = """
Do you want to create this file?
  1. Yes
  2. No
"""
        result = monitor.detect_confirmation_prompt(text)
        assert result is not None
        assert result['type'] == 'confirmation'
        assert len(result['options']) == 2

    def test_detect_confirmation_prompt_none(self, monitor):
        """測試無確認提示"""
        text = "Just a normal message"
        result = monitor.detect_confirmation_prompt(text)
        assert result is None

    def test_extract_actual_response(self, monitor):
        """測試實際回覆提取"""
        text = "some noise ⏺ Here is the actual response"
        result = monitor.extract_actual_response(text)
        assert result is not None
        assert "actual response" in result

    def test_extract_actual_response_none(self, monitor):
        """測試無 ⏺ 標記"""
        text = "No marker here"
        result = monitor.extract_actual_response(text)
        assert result is None

    def test_clean_output_empty(self, monitor):
        """測試空輸出清理"""
        assert monitor.clean_output("") == ""
        assert monitor.clean_output("   ") == ""

    def test_clean_output_short(self, monitor):
        """測試過短內容過濾"""
        result = monitor.clean_output("hi")
        assert result == ""

    def test_filter_tool_calls(self, monitor):
        """測試工具調用過濾"""
        text = '<invoke name="Read">some content</invoke>'
        result = monitor.filter_tool_calls(text)
        assert "[調用工具: Read]" in result


class TestMessageFormatter:
    """MessageFormatter 類測試"""

    def test_format_short_message(self):
        """測試短訊息格式化"""
        text = "Short message"
        result = MessageFormatter.format_for_telegram(text)
        assert len(result) == 1
        assert result[0] == text

    def test_format_empty_message(self):
        """測試空訊息格式化"""
        result = MessageFormatter.format_for_telegram("")
        assert result == []

    def test_format_long_message_split(self):
        """測試長訊息分段"""
        # 創建一個超過單條限制但未超過總限制的訊息
        text = "A" * 5000
        result = MessageFormatter.format_for_telegram(text)
        assert len(result) > 1
        # 檢查分段標記
        assert "[1/" in result[0]

    def test_format_very_long_message_file(self):
        """測試超長訊息轉文件"""
        text = "A" * 15000  # 超過 MAX_TOTAL_LENGTH
        result = MessageFormatter.format_for_telegram(text)
        assert len(result) == 1
        assert result[0]['type'] == 'file'
        assert 'filename' in result[0]
