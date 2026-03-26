#!/usr/bin/env python3
"""
CLI 提供者抽象層
支援 Claude Code 和 Gemini CLI 的差異化配置
"""

import json
import logging
import shlex
import subprocess
from pathlib import Path
from typing import Protocol, Optional

from i18n import t

logger = logging.getLogger(__name__)


class CliProvider(Protocol):
    """CLI 工具提供者介面"""

    @property
    def name(self) -> str:
        """CLI 名稱，如 'claude' 或 'gemini'"""
        ...

    @property
    def command(self) -> str:
        """CLI 執行檔名稱"""
        ...

    @property
    def default_tmux_prefix(self) -> str:
        """tmux 會話名稱預設前綴"""
        ...

    def build_launch_command(self, cli_args: str) -> str:
        """組合啟動命令"""
        ...

    def configure_hooks(self, work_dir: str, session_name: str,
                        hook_script: str) -> bool:
        """在專案目錄中配置 hook"""
        ...

    @property
    def extra_enter(self) -> bool:
        """送出訊息時是否需要額外一次 Enter（Gemini CLI 需要）"""
        ...

    def remove_hooks(self, work_dir: str) -> bool:
        """從專案目錄移除 hook 配置"""
        ...

    def is_installed(self) -> bool:
        """檢查 CLI 是否已安裝"""
        ...


def _remove_hook_key(settings_file: Path, hook_key: str, log_label: str) -> bool:
    """從設定檔移除指定 hook key（保留其他設定）

    Args:
        settings_file: 設定檔路徑
        hook_key: 要移除的 hook 名稱（如 'Stop' 或 'AfterAgent'）
        log_label: 日誌用的識別標籤
    """
    if not settings_file.exists():
        return True

    with open(settings_file, 'r', encoding='utf-8') as f:
        settings = json.load(f)

    if 'hooks' in settings and hook_key in settings['hooks']:
        del settings['hooks'][hook_key]
        # 如果 hooks 為空，移除整個 hooks key
        if not settings['hooks']:
            del settings['hooks']

        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)

    logger.info(t(log_label, name=str(settings_file.parent.parent)))
    return True


class ClaudeProvider:
    """Claude Code CLI 提供者"""

    @property
    def name(self) -> str:
        return "claude"

    @property
    def command(self) -> str:
        return "claude"

    @property
    def default_tmux_prefix(self) -> str:
        return "claude-"

    @property
    def extra_enter(self) -> bool:
        return False

    def build_launch_command(self, cli_args: str) -> str:
        if cli_args:
            return f"claude {cli_args}".strip()
        return "claude"

    def is_installed(self) -> bool:
        try:
            return subprocess.run(
                ['which', 'claude'], capture_output=True, text=True
            ).returncode == 0
        except Exception:
            return False

    def configure_hooks(self, work_dir: str, session_name: str,
                        hook_script: str) -> bool:
        """配置 Claude Code Stop hook，寫入 .claude/settings.local.json"""
        if not work_dir:
            return False

        try:
            hook_command = (
                f"TELEGRAM_SESSION_NAME={shlex.quote(session_name)} "
                f"TELEGRAM_CLI_TYPE=claude "
                f"{shlex.quote(hook_script)}"
            )
            stop_hooks = [{
                "hooks": [{
                    "type": "command",
                    "command": hook_command,
                    "timeout": 30
                }]
            }]

            # 寫入 .claude/settings.local.json
            config_dir = Path(work_dir) / '.claude'
            config_dir.mkdir(exist_ok=True)

            settings_file = config_dir / 'settings.local.json'

            # 讀取現有設定（保留 permissions 等）
            existing_settings = {}
            if settings_file.exists():
                try:
                    with open(settings_file, 'r', encoding='utf-8') as f:
                        existing_settings = json.load(f)
                except Exception as e:
                    logger.warning(t('provider.hooks_read_failed', error=e))

            # 合併 hooks 配置
            if 'hooks' not in existing_settings:
                existing_settings['hooks'] = {}

            existing_settings['hooks']['Stop'] = stop_hooks

            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(existing_settings, f, indent=2, ensure_ascii=False)

            logger.info(t('provider.hooks_configured_claude', name=session_name))
            return True

        except Exception as e:
            logger.warning(t('provider.hooks_config_failed', error=e))
            return False

    def remove_hooks(self, work_dir: str) -> bool:
        """從 .claude/settings.local.json 移除 Stop hook（保留其他設定）"""
        if not work_dir:
            return False
        try:
            settings_file = Path(work_dir) / '.claude' / 'settings.local.json'
            return _remove_hook_key(settings_file, 'Stop', 'provider.hooks_removed_claude')
        except Exception as e:
            logger.warning(t('provider.hooks_remove_failed', error=e))
            return False


class GeminiProvider:
    """Gemini CLI 提供者"""

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def command(self) -> str:
        return "gemini"

    @property
    def default_tmux_prefix(self) -> str:
        return "gemini-"

    @property
    def extra_enter(self) -> bool:
        return True

    def build_launch_command(self, cli_args: str) -> str:
        if cli_args:
            return f"gemini {cli_args}".strip()
        return "gemini"

    def is_installed(self) -> bool:
        try:
            return subprocess.run(
                ['which', 'gemini'], capture_output=True, text=True
            ).returncode == 0
        except Exception:
            return False

    def configure_hooks(self, work_dir: str, session_name: str,
                        hook_script: str) -> bool:
        """配置 Gemini CLI AfterAgent hook，寫入 .gemini/settings.json"""
        if not work_dir:
            return False

        try:
            hook_command = (
                f"TELEGRAM_SESSION_NAME={shlex.quote(session_name)} "
                f"TELEGRAM_CLI_TYPE=gemini "
                f"{shlex.quote(hook_script)}"
            )
            # Gemini 格式：hooks.AfterAgent[].hooks[]
            # 超時單位為毫秒（30 秒 = 30000 ms）
            after_agent_hooks = [{
                "matcher": "*",
                "hooks": [{
                    "type": "command",
                    "command": hook_command,
                    "timeout": 30000
                }]
            }]

            # 寫入 .gemini/settings.json
            config_dir = Path(work_dir) / '.gemini'
            config_dir.mkdir(exist_ok=True)

            settings_file = config_dir / 'settings.json'

            # 讀取現有設定
            existing_settings = {}
            if settings_file.exists():
                try:
                    with open(settings_file, 'r', encoding='utf-8') as f:
                        existing_settings = json.load(f)
                except Exception as e:
                    logger.warning(t('provider.hooks_read_failed', error=e))

            # 合併 hooks 配置
            if 'hooks' not in existing_settings:
                existing_settings['hooks'] = {}

            existing_settings['hooks']['AfterAgent'] = after_agent_hooks

            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(existing_settings, f, indent=2, ensure_ascii=False)

            logger.info(t('provider.hooks_configured_gemini', name=session_name))

            # 自動信任專案目錄（否則 Gemini CLI 不會載入 hooks）
            self._trust_folder(work_dir)

            return True

        except Exception as e:
            logger.warning(t('provider.hooks_config_failed', error=e))
            return False

    def remove_hooks(self, work_dir: str) -> bool:
        """從 .gemini/settings.json 移除 AfterAgent hook（保留其他設定）"""
        if not work_dir:
            return False
        try:
            settings_file = Path(work_dir) / '.gemini' / 'settings.json'
            return _remove_hook_key(settings_file, 'AfterAgent', 'provider.hooks_removed_gemini')
        except Exception as e:
            logger.warning(t('provider.hooks_remove_failed', error=e))
            return False

    @staticmethod
    def _trust_folder(work_dir: str) -> None:
        """將目錄加入 ~/.gemini/trustedFolders.json"""
        try:
            trusted_file = Path.home() / '.gemini' / 'trustedFolders.json'
            trusted = {}
            if trusted_file.exists():
                with open(trusted_file, 'r', encoding='utf-8') as f:
                    trusted = json.load(f)

            abs_path = str(Path(work_dir).resolve())
            if trusted.get(abs_path) == "TRUST_FOLDER":
                return  # 已信任

            trusted[abs_path] = "TRUST_FOLDER"
            with open(trusted_file, 'w', encoding='utf-8') as f:
                json.dump(trusted, f, indent=2, ensure_ascii=False)

            logger.info(t('provider.folder_trusted', path=abs_path))
        except Exception as e:
            logger.warning(t('provider.folder_trust_failed', error=e))


# 已註冊的 CLI 提供者
_PROVIDERS = {
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
}


def create_provider(cli_type: str) -> CliProvider:
    """根據 cli_type 建立對應的 Provider"""
    provider_class = _PROVIDERS.get(cli_type)
    if provider_class is None:
        supported = ', '.join(_PROVIDERS.keys())
        raise ValueError(t('provider.unsupported_cli', cli_type=cli_type, supported=supported))
    return provider_class()
