#!/usr/bin/env python3
"""SessionManager 單元測試"""

import pytest
from unittest.mock import patch, MagicMock

from session_manager import SessionManager, SessionConfig
from cli_provider import ClaudeProvider, GeminiProvider


class TestSessionConfig:
    """SessionConfig 測試"""

    def test_default_cli_type(self):
        config = SessionConfig("test", "/tmp/test", "claude-test")
        assert config.cli_type == "claude"
        assert config.cli_args == ""

    def test_custom_cli_type(self):
        config = SessionConfig("test", "/tmp/test", "gemini-test",
                               cli_args="--yolo", cli_type="gemini")
        assert config.cli_type == "gemini"
        assert config.cli_args == "--yolo"

    def test_log_file_uses_cli_type_prefix(self):
        config_claude = SessionConfig("proj", "/tmp", "claude-proj", cli_type="claude")
        assert "claude_proj" in config_claude.log_file

        config_gemini = SessionConfig("proj", "/tmp", "gemini-proj", cli_type="gemini")
        assert "gemini_proj" in config_gemini.log_file

    def test_attributes(self):
        config = SessionConfig("myname", "/path/to/project", "tmux-name",
                               cli_args="--model sonnet", cli_type="claude")
        assert config.name == "myname"
        assert config.path == "/path/to/project"
        assert config.tmux_session == "tmux-name"


class TestAddSession:
    """add_session 測試"""

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_default_tmux_prefix_claude(self, mock_create_provider, mock_bridge_cls):
        provider = ClaudeProvider()
        mock_create_provider.return_value = provider

        manager = SessionManager()
        manager.add_session("proj", "/tmp/proj")

        config = manager.get_session("proj")
        assert config.tmux_session == "claude-proj"

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_default_tmux_prefix_gemini(self, mock_create_provider, mock_bridge_cls):
        provider = GeminiProvider()
        mock_create_provider.return_value = provider

        manager = SessionManager()
        manager.add_session("proj", "/tmp/proj", cli_type="gemini")

        config = manager.get_session("proj")
        assert config.tmux_session == "gemini-proj"

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_custom_tmux_session(self, mock_create_provider, mock_bridge_cls):
        mock_create_provider.return_value = ClaudeProvider()

        manager = SessionManager()
        manager.add_session("proj", "/tmp/proj", tmux_session="my-tmux")

        config = manager.get_session("proj")
        assert config.tmux_session == "my-tmux"

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_bridge_created_with_provider(self, mock_create_provider, mock_bridge_cls):
        provider = GeminiProvider()
        mock_create_provider.return_value = provider

        manager = SessionManager()
        manager.add_session("proj", "/tmp/proj", cli_type="gemini")

        mock_bridge_cls.assert_called_once()
        call_kwargs = mock_bridge_cls.call_args
        assert call_kwargs.kwargs['cli_provider'] == provider

    @patch('session_manager.create_provider', side_effect=ValueError("不支援"))
    def test_unsupported_cli_type(self, mock_create_provider):
        manager = SessionManager()
        with pytest.raises(ValueError, match="不支援"):
            manager.add_session("proj", "/tmp/proj", cli_type="unknown")


class TestGetMethods:
    """get_session / get_bridge / get_all_sessions 測試"""

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_get_session_exists(self, mock_cp, mock_tb):
        mock_cp.return_value = ClaudeProvider()
        manager = SessionManager()
        manager.add_session("proj", "/tmp")
        assert manager.get_session("proj") is not None

    def test_get_session_not_exists(self):
        manager = SessionManager()
        assert manager.get_session("nonexistent") is None

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_get_bridge_exists(self, mock_cp, mock_tb):
        mock_cp.return_value = ClaudeProvider()
        manager = SessionManager()
        manager.add_session("proj", "/tmp")
        assert manager.get_bridge("proj") is not None

    def test_get_bridge_not_exists(self):
        manager = SessionManager()
        assert manager.get_bridge("nonexistent") is None

    def test_get_all_sessions_empty(self):
        manager = SessionManager()
        assert manager.get_all_sessions() == []

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_get_all_sessions(self, mock_cp, mock_tb):
        mock_cp.return_value = ClaudeProvider()
        manager = SessionManager()
        manager.add_session("a", "/tmp/a")
        manager.add_session("b", "/tmp/b")
        sessions = manager.get_all_sessions()
        assert set(sessions) == {"a", "b"}


class TestCreateAllSessions:
    """create_all_sessions 測試"""

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_all_success(self, mock_cp, mock_tb):
        mock_cp.return_value = ClaudeProvider()
        mock_bridge = MagicMock()
        mock_bridge.session_exists.return_value = False
        mock_bridge.create_session.return_value = True
        mock_tb.return_value = mock_bridge

        manager = SessionManager()
        manager.add_session("a", "/tmp/a")
        manager.add_session("b", "/tmp/b")
        assert manager.create_all_sessions() is True

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_partial_failure(self, mock_cp, mock_tb):
        mock_cp.return_value = ClaudeProvider()
        mock_bridge = MagicMock()
        mock_bridge.session_exists.return_value = False
        mock_bridge.create_session.return_value = False
        mock_tb.return_value = mock_bridge

        manager = SessionManager()
        manager.add_session("a", "/tmp/a")
        assert manager.create_all_sessions() is False

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_skip_existing(self, mock_cp, mock_tb):
        mock_cp.return_value = ClaudeProvider()
        mock_bridge = MagicMock()
        mock_bridge.session_exists.return_value = True
        mock_tb.return_value = mock_bridge

        manager = SessionManager()
        manager.add_session("a", "/tmp/a")
        assert manager.create_all_sessions() is True
        mock_bridge.create_session.assert_not_called()


class TestSendMethods:
    """send_to_session / send_to_all 測試"""

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_send_to_session(self, mock_cp, mock_tb):
        mock_cp.return_value = ClaudeProvider()
        mock_bridge = MagicMock()
        mock_bridge.send_command.return_value = True
        mock_tb.return_value = mock_bridge

        manager = SessionManager()
        manager.add_session("proj", "/tmp")
        assert manager.send_to_session("proj", "hello") is True
        mock_bridge.send_command.assert_called_once_with("hello")

    def test_send_to_session_not_exists(self):
        manager = SessionManager()
        assert manager.send_to_session("nonexistent", "hello") is False

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_send_to_all(self, mock_cp, mock_tb):
        mock_cp.return_value = ClaudeProvider()
        mock_bridge = MagicMock()
        mock_bridge.send_command.return_value = True
        mock_tb.return_value = mock_bridge

        manager = SessionManager()
        manager.add_session("a", "/tmp/a")
        manager.add_session("b", "/tmp/b")
        result = manager.send_to_all("hello")
        assert result == {"a": True, "b": True}


class TestGetStatus:
    """get_status 測試"""

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_includes_cli_type(self, mock_cp, mock_tb):
        mock_cp.return_value = GeminiProvider()
        mock_bridge = MagicMock()
        mock_bridge.session_exists.return_value = True
        mock_bridge.get_status.return_value = {}
        mock_tb.return_value = mock_bridge

        manager = SessionManager()
        manager.add_session("proj", "/tmp", cli_type="gemini", cli_args="--yolo")

        status = manager.get_status()
        assert "proj" in status
        assert status["proj"]["cli_type"] == "gemini"
        assert status["proj"]["cli_args"] == "--yolo"


class TestKillSession:
    """kill_session / kill_all_sessions 測試"""

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_kill_session(self, mock_cp, mock_tb):
        mock_cp.return_value = ClaudeProvider()
        mock_bridge = MagicMock()
        mock_bridge.kill_session.return_value = True
        mock_tb.return_value = mock_bridge

        manager = SessionManager()
        manager.add_session("proj", "/tmp")
        assert manager.kill_session("proj") is True

    def test_kill_session_not_exists(self):
        manager = SessionManager()
        assert manager.kill_session("nonexistent") is False

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_kill_all(self, mock_cp, mock_tb):
        mock_cp.return_value = ClaudeProvider()
        mock_bridge = MagicMock()
        mock_tb.return_value = mock_bridge

        manager = SessionManager()
        manager.add_session("a", "/tmp/a")
        manager.add_session("b", "/tmp/b")
        manager.kill_all_sessions()
        assert mock_bridge.kill_session.call_count == 2


class TestRestartSession:
    """restart_session 測試"""

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_successful_restart(self, mock_cp, mock_tb):
        mock_cp.return_value = ClaudeProvider()
        mock_bridge = MagicMock()
        mock_bridge.session_exists.return_value = True
        mock_bridge.create_session.return_value = True
        mock_tb.return_value = mock_bridge

        manager = SessionManager()
        manager.add_session("proj", "/tmp")
        assert manager.restart_session("proj") is True
        mock_bridge.kill_session.assert_called_once()
        mock_bridge.create_session.assert_called_once()

    def test_restart_not_exists(self):
        manager = SessionManager()
        assert manager.restart_session("nonexistent") is False

    @patch('session_manager.TmuxBridge')
    @patch('session_manager.create_provider')
    def test_restart_create_fails(self, mock_cp, mock_tb):
        mock_cp.return_value = ClaudeProvider()
        mock_bridge = MagicMock()
        mock_bridge.session_exists.return_value = False
        mock_bridge.create_session.return_value = False
        mock_tb.return_value = mock_bridge

        manager = SessionManager()
        manager.add_session("proj", "/tmp")
        assert manager.restart_session("proj") is False
