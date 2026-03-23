#!/usr/bin/env python3
"""
訊息路由模組測試
"""

import pytest
from unittest.mock import MagicMock
from message_router import MessageRouter


class TestMessageRouter:
    """MessageRouter 類測試"""

    @pytest.fixture
    def mock_session_manager(self):
        """建立模擬的 SessionManager"""
        manager = MagicMock()
        manager.get_all_sessions.return_value = ['rental', 'mac_claude', 'test']

        # get_session 需要回傳帶 path/tmux_session 屬性的物件，或不存在時回傳 None
        valid_sessions = {
            'rental': MagicMock(path='/tmp/rental', tmux_session='claude-rental'),
            'mac_claude': MagicMock(path='/tmp/mac_claude', tmux_session='claude-mac_claude'),
            'test': MagicMock(path='/tmp/test', tmux_session='claude-test'),
        }
        manager.get_session.side_effect = lambda name: valid_sessions.get(name)
        return manager

    @pytest.fixture
    def router(self, mock_session_manager):
        """建立測試用的 MessageRouter"""
        return MessageRouter(mock_session_manager)

    def test_parse_single_session(self, router):
        """測試單會話路由"""
        result = router.parse_message("#rental hello world")
        assert len(result) == 1
        assert result[0][0] == "rental"
        assert result[0][1] == "hello world"

    def test_parse_all_sessions(self, router):
        """測試廣播到所有會話"""
        result = router.parse_message("#all hello everyone")
        assert len(result) == 3  # 3 個會話
        session_names = [r[0] for r in result]
        assert "rental" in session_names
        assert "mac_claude" in session_names

    def test_parse_invalid_session(self, router):
        """測試無效會話"""
        result = router.parse_message("#nonexistent hello")
        assert len(result) == 1
        assert result[0][0] == "__error__"

    def test_parse_no_prefix(self, router):
        """測試無前綴訊息"""
        result = router.parse_message("hello without prefix")
        assert len(result) == 1
        assert result[0][0] == "__error__"

    def test_parse_underscore_session(self, router):
        """測試含底線的會話名稱"""
        result = router.parse_message("#mac_claude test message")
        assert len(result) == 1
        assert result[0][0] == "mac_claude"
        assert result[0][1] == "test message"

    def test_format_session_list(self, router):
        """測試會話列表格式化"""
        result = router.format_session_list()
        assert "#rental" in result
        assert "#mac_claude" in result
        assert "#test" in result
