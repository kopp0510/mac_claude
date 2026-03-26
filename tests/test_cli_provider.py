#!/usr/bin/env python3
"""CLI Provider 模組測試"""

import json
import os
import tempfile
import unittest.mock
from pathlib import Path
import pytest

from cli_provider import (
    ClaudeProvider, GeminiProvider, create_provider
)


class TestClaudeProvider:
    """ClaudeProvider 測試"""

    def setup_method(self):
        self.provider = ClaudeProvider()

    def test_name(self):
        assert self.provider.name == "claude"

    def test_command(self):
        assert self.provider.command == "claude"

    def test_default_tmux_prefix(self):
        assert self.provider.default_tmux_prefix == "claude-"

    def test_build_launch_command_no_args(self):
        assert self.provider.build_launch_command("") == "claude"

    def test_build_launch_command_with_args(self):
        assert self.provider.build_launch_command("--model sonnet") == "claude --model sonnet"

    def test_configure_hooks_creates_settings(self):
        """驗證 Claude hook 配置寫入 .claude/settings.local.json"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.provider.configure_hooks(
                tmpdir, "test-session", "/path/to/notify_telegram.sh"
            )
            assert result is True

            settings_file = os.path.join(tmpdir, '.claude', 'settings.local.json')
            assert os.path.exists(settings_file)

            with open(settings_file, 'r') as f:
                settings = json.load(f)

            assert 'hooks' in settings
            assert 'Stop' in settings['hooks']
            stop_hooks = settings['hooks']['Stop']
            assert len(stop_hooks) == 1
            assert 'hooks' in stop_hooks[0]
            inner = stop_hooks[0]['hooks'][0]
            assert inner['type'] == 'command'
            assert 'TELEGRAM_SESSION_NAME=' in inner['command']
            assert 'test-session' in inner['command']
            assert inner['timeout'] == 30

    def test_configure_hooks_preserves_existing(self):
        """驗證合併而非覆蓋現有設定"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = os.path.join(tmpdir, '.claude')
            os.makedirs(config_dir)
            settings_file = os.path.join(config_dir, 'settings.local.json')
            with open(settings_file, 'w') as f:
                json.dump({"permissions": {"allow": ["read"]}}, f)

            self.provider.configure_hooks(
                tmpdir, "test", "/path/to/script.sh"
            )

            with open(settings_file, 'r') as f:
                settings = json.load(f)

            # 驗證保留原有設定
            assert settings['permissions'] == {"allow": ["read"]}
            assert 'hooks' in settings

    def test_configure_hooks_no_work_dir(self):
        assert self.provider.configure_hooks("", "test", "/path/to/script.sh") is False

    def test_remove_hooks(self):
        """驗證移除 Stop hook 但保留其他設定"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 先配置 hooks
            self.provider.configure_hooks(tmpdir, "test", "/path/to/script.sh")

            settings_file = os.path.join(tmpdir, '.claude', 'settings.local.json')
            # 加入 permissions
            with open(settings_file, 'r') as f:
                settings = json.load(f)
            settings['permissions'] = {"allow": ["read"]}
            with open(settings_file, 'w') as f:
                json.dump(settings, f)

            # 移除 hooks
            assert self.provider.remove_hooks(tmpdir) is True

            with open(settings_file, 'r') as f:
                result = json.load(f)

            # hooks.Stop 已移除
            assert 'Stop' not in result.get('hooks', {})
            # permissions 保留
            assert result['permissions'] == {"allow": ["read"]}

    def test_remove_hooks_no_file(self):
        """驗證檔案不存在時不報錯"""
        with tempfile.TemporaryDirectory() as tmpdir:
            assert self.provider.remove_hooks(tmpdir) is True


class TestGeminiProvider:
    """GeminiProvider 測試"""

    def setup_method(self):
        self.provider = GeminiProvider()

    def test_name(self):
        assert self.provider.name == "gemini"

    def test_command(self):
        assert self.provider.command == "gemini"

    def test_default_tmux_prefix(self):
        assert self.provider.default_tmux_prefix == "gemini-"

    def test_build_launch_command_no_args(self):
        assert self.provider.build_launch_command("") == "gemini"

    def test_build_launch_command_with_args(self):
        assert self.provider.build_launch_command("--yolo") == "gemini --yolo"

    def test_configure_hooks_creates_settings(self):
        """驗證 Gemini hook 配置寫入 .gemini/settings.json"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.provider.configure_hooks(
                tmpdir, "test-session", "/path/to/notify_telegram.sh"
            )
            assert result is True

            settings_file = os.path.join(tmpdir, '.gemini', 'settings.json')
            assert os.path.exists(settings_file)

            with open(settings_file, 'r') as f:
                settings = json.load(f)

            assert 'hooks' in settings
            assert 'AfterAgent' in settings['hooks']
            after_agent = settings['hooks']['AfterAgent']
            assert len(after_agent) == 1
            assert after_agent[0]['matcher'] == '*'
            inner = after_agent[0]['hooks'][0]
            assert inner['type'] == 'command'
            assert 'TELEGRAM_SESSION_NAME=' in inner['command']
            assert 'TELEGRAM_CLI_TYPE=gemini' in inner['command']
            # Gemini 超時單位為毫秒
            assert inner['timeout'] == 30000

    def test_configure_hooks_preserves_existing(self):
        """驗證合併而非覆蓋現有設定"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = os.path.join(tmpdir, '.gemini')
            os.makedirs(config_dir)
            settings_file = os.path.join(config_dir, 'settings.json')
            with open(settings_file, 'w') as f:
                json.dump({"security": {"auth": {"selectedType": "oauth"}}}, f)

            self.provider.configure_hooks(
                tmpdir, "test", "/path/to/script.sh"
            )

            with open(settings_file, 'r') as f:
                settings = json.load(f)

            # 驗證保留原有設定
            assert settings['security'] == {"auth": {"selectedType": "oauth"}}
            assert 'hooks' in settings


    def test_remove_hooks(self):
        """驗證移除 AfterAgent hook 但保留其他設定"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self.provider.configure_hooks(tmpdir, "test", "/path/to/script.sh")

            settings_file = os.path.join(tmpdir, '.gemini', 'settings.json')
            with open(settings_file, 'r') as f:
                settings = json.load(f)
            settings['security'] = {"auth": {"selectedType": "oauth"}}
            with open(settings_file, 'w') as f:
                json.dump(settings, f)

            assert self.provider.remove_hooks(tmpdir) is True

            with open(settings_file, 'r') as f:
                result = json.load(f)

            assert 'AfterAgent' not in result.get('hooks', {})
            assert result['security'] == {"auth": {"selectedType": "oauth"}}


class TestGeminiTrustFolder:
    """GeminiProvider 自動信任目錄測試"""

    def setup_method(self):
        self.provider = GeminiProvider()

    def test_configure_hooks_trusts_folder(self):
        """configure_hooks 後目錄被加入 trustedFolders.json"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 模擬 ~/.gemini/trustedFolders.json
            with unittest.mock.patch.object(
                GeminiProvider, '_trust_folder', wraps=self.provider._trust_folder
            ):
                # 建立假的 trustedFolders.json
                gemini_home = os.path.join(tmpdir, 'fake_home', '.gemini')
                os.makedirs(gemini_home, exist_ok=True)
                trusted_file = os.path.join(gemini_home, 'trustedFolders.json')
                with open(trusted_file, 'w') as f:
                    json.dump({}, f)

                # 用 patch 將 Path.home() 指向假目錄
                with unittest.mock.patch('cli_provider.Path.home',
                                          return_value=Path(tmpdir) / 'fake_home'):
                    work_dir = os.path.join(tmpdir, 'project')
                    os.makedirs(work_dir)
                    self.provider.configure_hooks(
                        work_dir, "test", "/path/to/script.sh"
                    )

                with open(trusted_file, 'r') as f:
                    trusted = json.load(f)

                abs_path = str(Path(work_dir).resolve())
                assert trusted.get(abs_path) == "TRUST_FOLDER"

    def test_trust_preserves_existing_entries(self):
        """信任不覆蓋已有條目"""
        with tempfile.TemporaryDirectory() as tmpdir:
            gemini_home = os.path.join(tmpdir, 'fake_home', '.gemini')
            os.makedirs(gemini_home, exist_ok=True)
            trusted_file = os.path.join(gemini_home, 'trustedFolders.json')
            with open(trusted_file, 'w') as f:
                json.dump({"/other/project": "DO_NOT_TRUST"}, f)

            with unittest.mock.patch('cli_provider.Path.home',
                                      return_value=Path(tmpdir) / 'fake_home'):
                work_dir = os.path.join(tmpdir, 'project')
                os.makedirs(work_dir)
                GeminiProvider._trust_folder(work_dir)

            with open(trusted_file, 'r') as f:
                trusted = json.load(f)

            assert trusted.get("/other/project") == "DO_NOT_TRUST"
            abs_path = str(Path(work_dir).resolve())
            assert trusted.get(abs_path) == "TRUST_FOLDER"


class TestCreateProvider:
    """create_provider 工廠函數測試"""

    def test_create_claude(self):
        provider = create_provider("claude")
        assert isinstance(provider, ClaudeProvider)

    def test_create_gemini(self):
        provider = create_provider("gemini")
        assert isinstance(provider, GeminiProvider)

    def test_unsupported_type(self):
        with pytest.raises(ValueError, match="不支援的 CLI 類型"):
            create_provider("unknown")
