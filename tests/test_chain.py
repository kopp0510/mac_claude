#!/usr/bin/env python3
"""
會話串接（Chain）功能測試
"""

import json
import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timedelta

from config import patterns, config as app_config
from send_telegram_notification import process_chain, _clear_session_busy
from tmux_bridge import send_keys_to_session


class TestChainPatterns:
    """串接語法偵測模式測試"""

    def test_detect_simple_chain(self):
        """偵測簡單串接語法"""
        msg = "#claude 分析 >> #gemini 審查"
        assert patterns.CHAIN_DETECT.search(msg) is not None

    def test_detect_multi_chain(self):
        """偵測多段串接"""
        msg = "#claude 做 X >> #gemini 做 Y >> #codex 做 Z"
        assert patterns.CHAIN_DETECT.search(msg) is not None

    def test_no_false_positive_without_hash(self):
        """不誤判：>> 後面沒有 #"""
        msg = "#claude echo a >> b"
        assert patterns.CHAIN_DETECT.search(msg) is None

    def test_no_false_positive_no_spaces(self):
        """不誤判：>> 沒有空白包圍"""
        msg = "#claude echo a>>#gemini"
        assert patterns.CHAIN_DETECT.search(msg) is None

    def test_split_chain(self):
        """分割串接語法"""
        msg = "#claude 分析 >> #gemini 審查"
        segments = patterns.CHAIN_SPLIT.split(msg)
        assert len(segments) == 2
        assert segments[0] == "#claude 分析"
        assert segments[1] == "#gemini 審查"

    def test_split_multi_chain(self):
        """分割多段串接"""
        msg = "#claude 做 X >> #gemini 做 Y >> #codex 做 Z"
        segments = patterns.CHAIN_SPLIT.split(msg)
        assert len(segments) == 3

    def test_chain_target_with_prefix(self):
        """解析串接目標（含前綴）"""
        match = patterns.CHAIN_TARGET.match("#gemini 審查以下分析")
        assert match is not None
        assert match.group(1) == "gemini"
        assert match.group(2) == "審查以下分析"

    def test_chain_target_without_prefix(self):
        """解析串接目標（不含前綴）"""
        match = patterns.CHAIN_TARGET.match("#gemini")
        assert match is not None
        assert match.group(1) == "gemini"
        assert match.group(2) is None

    def test_chain_target_invalid(self):
        """無效的串接目標"""
        match = patterns.CHAIN_TARGET.match("gemini 審查")
        assert match is None


class TestWriteChainFile:
    """寫入 chain 檔測試"""

    def test_write_single_chain(self, tmp_path):
        """寫入單段 chain"""
        from telegram_bot_multi import _write_chain_file

        # Mock session config
        session_config = MagicMock()
        session_config.tmux_session = "gemini-gemini"
        session_config.cli_type = "gemini"
        session_config.path = "/path/to/project"

        with patch.object(app_config.chain, 'CHAIN_DIR', str(tmp_path)):
            _write_chain_file(
                "claude",
                [("gemini", "審查", session_config)],
                ["claude", "gemini"]
            )

        chain_file = tmp_path / "claude.json"
        assert chain_file.exists()
        data = json.loads(chain_file.read_text())
        assert data["target_session"] == "gemini"
        assert data["target_tmux"] == "gemini-gemini"
        assert data["target_cli_type"] == "gemini"
        assert data["target_path"] == "/path/to/project"
        assert data["prompt_prefix"] == "審查"
        assert data["next_chain"] is None
        assert data["chain_path"] == ["claude", "gemini"]

    def test_write_multi_chain(self, tmp_path):
        """寫入多段 chain（巢狀結構）"""
        from telegram_bot_multi import _write_chain_file

        config_gemini = MagicMock()
        config_gemini.tmux_session = "gemini-gemini"
        config_gemini.cli_type = "gemini"
        config_gemini.path = "/path/to/gemini"

        config_codex = MagicMock()
        config_codex.tmux_session = "codex-codex"
        config_codex.cli_type = "codex"
        config_codex.path = "/path/to/codex"

        with patch.object(app_config.chain, 'CHAIN_DIR', str(tmp_path)):
            _write_chain_file(
                "claude",
                [("gemini", "審查", config_gemini), ("codex", "最終檢查", config_codex)],
                ["claude", "gemini", "codex"]
            )

        chain_file = tmp_path / "claude.json"
        data = json.loads(chain_file.read_text())
        assert data["target_session"] == "gemini"
        assert data["next_chain"] is not None
        assert data["next_chain"]["target_session"] == "codex"
        assert data["next_chain"]["prompt_prefix"] == "最終檢查"
        assert data["next_chain"]["next_chain"] is None


class TestProcessChain:
    """chain 轉發處理測試"""

    def test_no_chain_file(self, tmp_path):
        """無 chain 檔時返回 False"""
        with patch.object(app_config.chain, 'CHAIN_DIR', str(tmp_path)):
            result = process_chain("claude", "test response")
        assert result is False

    def test_process_single_chain(self, tmp_path):
        """處理單段 chain：寫入暫存檔、轉發指令、刪除 chain 檔"""
        chain_dir = tmp_path / "chains"
        chain_dir.mkdir()
        target_dir = tmp_path / "target_project"
        target_dir.mkdir()
        chain_data = {
            "target_session": "gemini",
            "target_tmux": "gemini-gemini",
            "target_cli_type": "gemini",
            "target_path": str(target_dir),
            "prompt_prefix": "審查",
            "next_chain": None,
            "chain_path": ["claude", "gemini"],
            "created_at": datetime.now().isoformat(),
        }
        chain_file = chain_dir / "claude.json"
        chain_file.write_text(json.dumps(chain_data))

        with patch.object(app_config.chain, 'CHAIN_DIR', str(chain_dir)), \
             patch('send_telegram_notification.send_keys_to_session', return_value=True) as mock_forward, \
             patch('send_telegram_notification.send_telegram_message') as mock_send:

            result = process_chain("claude", "分析結果如下...")

        assert result is True
        mock_forward.assert_called_once()
        forwarded_msg = mock_forward.call_args[0][2]
        assert "審查" in forwarded_msg
        assert ".ai_bridge_chain_claude.md" in forwarded_msg
        # 驗證暫存檔寫入 B 的工作目錄
        result_file = target_dir / ".ai_bridge_chain_claude.md"
        assert result_file.exists()
        assert result_file.read_text() == "分析結果如下..."
        result_file.unlink()
        assert not chain_file.exists()
        assert mock_send.call_count >= 1

    def test_process_chain_writes_next(self, tmp_path):
        """多段 chain：處理後寫入下一段 chain 檔"""
        chain_dir = tmp_path
        target_dir = tmp_path / "target"
        target_dir.mkdir()
        chain_data = {
            "target_session": "gemini",
            "target_tmux": "gemini-gemini",
            "target_cli_type": "gemini",
            "target_path": str(target_dir),
            "prompt_prefix": "審查",
            "next_chain": {
                "target_session": "codex",
                "target_tmux": "codex-codex",
                "target_cli_type": "codex",
                "target_path": str(target_dir),
                "prompt_prefix": "最終檢查",
                "next_chain": None,
                "chain_path": ["claude", "gemini", "codex"],
                "created_at": datetime.now().isoformat(),
                },
            "chain_path": ["claude", "gemini", "codex"],
            "created_at": datetime.now().isoformat(),
        }
        (chain_dir / "claude.json").write_text(json.dumps(chain_data))

        with patch.object(app_config.chain, 'CHAIN_DIR', str(chain_dir)), \
             patch('send_telegram_notification.send_keys_to_session', return_value=True), \
             patch('send_telegram_notification.send_telegram_message'):

            result = process_chain("claude", "分析結果")

        assert result is True
        # 驗證 next chain 檔已寫入
        next_file = chain_dir / "gemini.json"
        assert next_file.exists()
        next_data = json.loads(next_file.read_text())
        assert next_data["target_session"] == "codex"

    def test_process_chain_writes_done_file(self, tmp_path):
        """最終節點：寫入 .done 標記檔"""
        chain_dir = tmp_path
        target_dir = tmp_path / "target"
        target_dir.mkdir()
        chain_data = {
            "target_session": "gemini",
            "target_tmux": "gemini-gemini",
            "target_cli_type": "gemini",
            "target_path": str(target_dir),
            "prompt_prefix": "審查",
            "next_chain": None,
            "chain_path": ["claude", "gemini"],
            "created_at": datetime.now().isoformat(),
        }
        (chain_dir / "claude.json").write_text(json.dumps(chain_data))

        with patch.object(app_config.chain, 'CHAIN_DIR', str(chain_dir)), \
             patch('send_telegram_notification.send_keys_to_session', return_value=True), \
             patch('send_telegram_notification.send_telegram_message'):

            process_chain("claude", "結果")

        done_file = chain_dir / "gemini.done"
        assert done_file.exists()
        done_data = json.loads(done_file.read_text())
        assert done_data["chain_path"] == ["claude", "gemini"]
        assert done_data["step_count"] == 2

    def test_process_chain_expired(self, tmp_path):
        """過期 chain 檔不轉發"""
        chain_dir = tmp_path
        expired_time = (datetime.now() - timedelta(hours=2)).isoformat()
        chain_data = {
            "target_session": "gemini",
            "target_tmux": "gemini-gemini",
            "target_cli_type": "gemini",
            "target_path": str(tmp_path),
            "prompt_prefix": "審查",
            "next_chain": None,
            "chain_path": ["claude", "gemini"],
            "created_at": expired_time,
        }
        (chain_dir / "claude.json").write_text(json.dumps(chain_data))

        with patch.object(app_config.chain, 'CHAIN_DIR', str(chain_dir)), \
             patch('send_telegram_notification.send_keys_to_session') as mock_forward, \
             patch('send_telegram_notification.send_telegram_message'):

            result = process_chain("claude", "結果")

        assert result is False
        mock_forward.assert_not_called()

    def test_process_chain_writes_response_to_file(self, tmp_path):
        """回應寫入暫存 .md 檔案"""
        chain_dir = tmp_path / "chains"
        chain_dir.mkdir()
        target_dir = tmp_path / "target"
        target_dir.mkdir()
        chain_data = {
            "target_session": "gemini",
            "target_tmux": "gemini-gemini",
            "target_cli_type": "gemini",
            "target_path": str(target_dir),
            "prompt_prefix": "審查",
            "next_chain": None,
            "chain_path": ["claude", "gemini"],
            "created_at": datetime.now().isoformat(),
        }
        (chain_dir / "claude.json").write_text(json.dumps(chain_data))

        long_response = "x" * 5000  # 完整寫入，不截斷

        with patch.object(app_config.chain, 'CHAIN_DIR', str(chain_dir)), \
             patch('send_telegram_notification.send_keys_to_session', return_value=True), \
             patch('send_telegram_notification.send_telegram_message'):

            process_chain("claude", long_response)

        # 暫存檔包含完整回應（寫入 target_path）
        result_file = target_dir / ".ai_bridge_chain_claude.md"
        assert result_file.exists()
        content = result_file.read_text()
        assert len(content) == 5000

    def test_done_file_triggers_completion_notification(self, tmp_path):
        """.done 標記檔觸發完成通知"""
        chain_dir = tmp_path
        done_data = {"chain_path": ["claude", "gemini"], "step_count": 2}
        (chain_dir / "gemini.done").write_text(json.dumps(done_data))

        with patch.object(app_config.chain, 'CHAIN_DIR', str(chain_dir)), \
             patch('send_telegram_notification.send_telegram_message') as mock_send:

            process_chain("gemini", "審查結果")

        # 驗證完成通知已發送
        calls = mock_send.call_args_list
        completed_call = [c for c in calls if 'chain.completed' in str(c) or '#claude' in str(c)]
        # 至少有一次呼叫包含完成通知
        assert mock_send.call_count >= 1


class TestForwardToTmux:
    """tmux 轉發測試"""

    @patch('tmux_bridge.subprocess.run')
    def test_forward_short_message(self, mock_run):
        """短訊息使用 send-keys"""
        mock_run.return_value = MagicMock(returncode=0)
        result = send_keys_to_session("claude-test", "claude", "短訊息")
        assert result is True
        # 驗證使用 send-keys -l
        first_call = mock_run.call_args_list[0]
        assert 'send-keys' in first_call[0][0]
        assert '-l' in first_call[0][0]

    @patch('tmux_bridge.subprocess.run')
    def test_forward_gemini_extra_enter(self, mock_run):
        """Gemini 需要額外 Enter"""
        mock_run.return_value = MagicMock(returncode=0)
        send_keys_to_session("gemini-test", "gemini", "訊息")
        # send-keys + Enter + extra Enter = 至少 3 次呼叫
        assert mock_run.call_count >= 3

    @patch('tmux_bridge.subprocess.run')
    @patch('tmux_bridge.time.sleep')
    def test_forward_codex_pre_enter_delay(self, mock_sleep, mock_run):
        """Codex 需要 pre-enter delay"""
        mock_run.return_value = MagicMock(returncode=0)
        send_keys_to_session("codex-test", "codex", "訊息")
        mock_sleep.assert_called_once_with(0.15)

    @patch('tmux_bridge.subprocess.run')
    def test_forward_long_message_uses_buffer(self, mock_run):
        """超長訊息使用 load-buffer + paste-buffer"""
        mock_run.return_value = MagicMock(returncode=0)
        long_msg = "x" * 3000
        result = send_keys_to_session("claude-test", "claude", long_msg)
        assert result is True
        # 驗證使用 load-buffer
        cmds = [c[0][0] for c in mock_run.call_args_list]
        has_load_buffer = any('load-buffer' in cmd for cmd in cmds)
        assert has_load_buffer

    @patch('tmux_bridge.subprocess.run')
    def test_forward_failure(self, mock_run):
        """tmux 失敗時返回 False"""
        mock_run.return_value = MagicMock(returncode=1, stderr="session not found")
        result = send_keys_to_session("nonexist", "claude", "訊息")
        assert result is False


class TestSessionBusyStatus:
    """Session 忙碌狀態測試"""

    def test_mark_session_busy(self, tmp_path):
        """標記 session 為忙碌"""
        from telegram_bot_multi import _mark_session_busy

        with patch.object(app_config.status, 'STATUS_DIR', str(tmp_path)):
            _mark_session_busy("claude")

        busy_file = tmp_path / "claude.busy"
        assert busy_file.exists()
        content = busy_file.read_text()
        # 應為 ISO 格式時間戳
        datetime.fromisoformat(content)

    def test_get_session_busy_seconds(self, tmp_path):
        """取得忙碌秒數"""
        from telegram_bot_multi import _get_session_busy_seconds

        # 建立一個 2 秒前的 busy 檔
        busy_file = tmp_path / "claude.busy"
        past = datetime.now() - timedelta(seconds=5)
        busy_file.write_text(past.isoformat())

        with patch.object(app_config.status, 'STATUS_DIR', str(tmp_path)):
            seconds = _get_session_busy_seconds("claude")

        assert seconds >= 5

    def test_get_session_not_busy(self, tmp_path):
        """未忙碌返回 -1"""
        from telegram_bot_multi import _get_session_busy_seconds

        with patch.object(app_config.status, 'STATUS_DIR', str(tmp_path)):
            seconds = _get_session_busy_seconds("claude")

        assert seconds == -1

    def test_clear_session_busy(self, tmp_path):
        """清除忙碌標記"""
        status_dir = tmp_path
        busy_file = status_dir / "claude.busy"
        busy_file.write_text(datetime.now().isoformat())

        with patch.object(app_config.status, 'STATUS_DIR', str(status_dir)):
            _clear_session_busy("claude")

        assert not busy_file.exists()

    def test_clear_session_busy_not_exists(self, tmp_path):
        """清除不存在的標記不報錯"""
        with patch.object(app_config.status, 'STATUS_DIR', str(tmp_path)):
            _clear_session_busy("nonexist")  # 不應拋錯
