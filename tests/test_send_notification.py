#!/usr/bin/env python3
"""
Telegram 通知發送模組測試
"""

import pytest
from unittest.mock import patch, MagicMock
from send_telegram_notification import send_telegram_message, send_to_chat


class TestSendTelegramNotification:
    """通知發送測試"""

    @patch('send_telegram_notification.load_dotenv')
    @patch('send_telegram_notification.os.getenv')
    def test_missing_token(self, mock_getenv, mock_load_dotenv):
        """測試缺少 Token"""
        mock_getenv.return_value = None
        result = send_telegram_message("test", "message")
        assert result is False

    @patch('send_telegram_notification.load_dotenv')
    @patch('send_telegram_notification.os.getenv')
    def test_missing_user_ids(self, mock_getenv, mock_load_dotenv):
        """測試缺少用戶 ID"""
        def getenv_side_effect(key, default=''):
            if key == 'TELEGRAM_BOT_TOKEN':
                return 'test_token'
            return default

        mock_getenv.side_effect = getenv_side_effect
        result = send_telegram_message("test", "message")
        assert result is False

    @patch('send_telegram_notification.requests.post')
    def test_send_to_chat_success(self, mock_post):
        """測試成功發送"""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_post.return_value = mock_response

        result = send_to_chat("token", "123456", "Hello")
        assert result is True
        mock_post.assert_called_once()

    @patch('send_telegram_notification.requests.post')
    def test_send_to_chat_retry_on_failure(self, mock_post):
        """測試失敗重試"""
        # 前兩次失敗，第三次成功
        mock_fail = MagicMock()
        mock_fail.ok = False
        mock_fail.json.return_value = {'error_code': 500, 'description': 'Server Error'}
        mock_fail.status_code = 500
        mock_fail.text = 'Server Error'

        mock_success = MagicMock()
        mock_success.ok = True

        mock_post.side_effect = [mock_fail, mock_fail, mock_success]

        result = send_to_chat("token", "123456", "Hello")
        assert result is True
        assert mock_post.call_count == 3

    @patch('send_telegram_notification.requests.post')
    def test_send_to_chat_non_retryable_error(self, mock_post):
        """測試不可重試的錯誤"""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.json.return_value = {'error_code': 401, 'description': 'Unauthorized'}
        mock_response.status_code = 401
        mock_response.text = 'Unauthorized'
        mock_post.return_value = mock_response

        result = send_to_chat("token", "123456", "Hello")
        assert result is False
        assert mock_post.call_count == 1  # 不重試

    def test_send_to_chat_invalid_chat_id(self):
        """測試無效的 chat_id"""
        result = send_to_chat("token", "invalid", "Hello")
        assert result is False
