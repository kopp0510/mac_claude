#!/usr/bin/env python3
"""
CLI 提供者抽象層
支援 Claude Code、Gemini CLI 和 OpenAI Codex CLI 的差異化配置
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

    @property
    def pre_enter_delay(self) -> float:
        """送出文字後、按 Enter 前的延遲秒數（Codex ink/React TUI 需要）"""
        ...

    def remove_hooks(self, work_dir: str) -> bool:
        """從專案目錄移除 hook 配置"""
        ...

    def is_installed(self) -> bool:
        """檢查 CLI 是否已安裝"""
        ...


# === 共用 helper ===

def _remove_hook_key(settings_file: Path, hook_key: str, log_label: str) -> bool:
    """從設定檔移除指定 hook key（保留其他設定）"""
    if not settings_file.exists():
        return True

    with open(settings_file, 'r', encoding='utf-8') as f:
        settings = json.load(f)

    if 'hooks' in settings and hook_key in settings['hooks']:
        del settings['hooks'][hook_key]
        if not settings['hooks']:
            del settings['hooks']

        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)

    logger.info(t(log_label, name=str(settings_file.parent.parent)))
    return True


def _configure_hooks_json(work_dir: str, config_subpath: str, hook_key: str,
                          hook_data: list, log_label: str) -> bool:
    """共用的 JSON hook 配置邏輯（讀取 → 合併 → 寫回）

    Args:
        work_dir: 專案目錄
        config_subpath: 設定檔相對路徑（如 '.claude/settings.local.json'）
        hook_key: hook 事件名稱（如 'Stop' 或 'AfterAgent'）
        hook_data: hook 配置資料
        log_label: 成功日誌的 i18n key
    """
    settings_file = Path(work_dir) / config_subpath
    settings_file.parent.mkdir(exist_ok=True)

    existing_settings = {}
    if settings_file.exists():
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                existing_settings = json.load(f)
        except Exception as e:
            logger.warning(t('provider.hooks_read_failed', error=e))

    if 'hooks' not in existing_settings:
        existing_settings['hooks'] = {}

    existing_settings['hooks'][hook_key] = hook_data

    with open(settings_file, 'w', encoding='utf-8') as f:
        json.dump(existing_settings, f, indent=2, ensure_ascii=False)

    return True


def _build_hook_command(session_name: str, cli_type: str, hook_script: str) -> str:
    """組合 hook 命令字串"""
    return (
        f"TELEGRAM_SESSION_NAME={shlex.quote(session_name)} "
        f"TELEGRAM_CLI_TYPE={cli_type} "
        f"{shlex.quote(hook_script)}"
    )


# === 基底類別 ===

class BaseProvider:
    """Provider 共用邏輯基底類別

    子類別需定義：
        _name, _command, _config_subpath, _hook_key, _hook_timeout,
        _hook_needs_matcher, _extra_enter, _pre_enter_delay
    """
    _name: str
    _command: str
    _config_subpath: str  # 如 '.claude/settings.local.json'
    _hook_key: str        # 如 'Stop' 或 'AfterAgent'
    _hook_timeout: int    # 秒或毫秒（依 CLI 而定）
    _hook_needs_matcher: bool = False  # Gemini 需要 matcher: "*"
    _extra_enter: bool = False
    _pre_enter_delay: float = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def command(self) -> str:
        return self._command

    @property
    def default_tmux_prefix(self) -> str:
        return f"{self._name}-"

    @property
    def extra_enter(self) -> bool:
        return self._extra_enter

    @property
    def pre_enter_delay(self) -> float:
        return self._pre_enter_delay

    def build_launch_command(self, cli_args: str) -> str:
        return f"{self._command} {cli_args}".strip() if cli_args else self._command

    def is_installed(self) -> bool:
        try:
            return subprocess.run(
                ['which', self._command], capture_output=True, text=True
            ).returncode == 0
        except Exception:
            return False

    def configure_hooks(self, work_dir: str, session_name: str,
                        hook_script: str) -> bool:
        if not work_dir:
            return False

        try:
            hook_command = _build_hook_command(session_name, self._name, hook_script)
            inner_hook = {
                "type": "command",
                "command": hook_command,
                "timeout": self._hook_timeout
            }
            hook_entry = {"hooks": [inner_hook]}
            if self._hook_needs_matcher:
                hook_entry["matcher"] = "*"

            _configure_hooks_json(
                work_dir, self._config_subpath, self._hook_key,
                [hook_entry], f'provider.hooks_configured_{self._name}'
            )

            logger.info(t(f'provider.hooks_configured_{self._name}', name=session_name))
            self._post_configure_hooks(work_dir)
            return True

        except Exception as e:
            logger.warning(t('provider.hooks_config_failed', error=e))
            return False

    def _post_configure_hooks(self, work_dir: str) -> None:
        """hook 配置後的額外動作（子類別覆寫）"""
        pass

    def remove_hooks(self, work_dir: str) -> bool:
        if not work_dir:
            return False
        try:
            settings_file = Path(work_dir) / self._config_subpath
            return _remove_hook_key(settings_file, self._hook_key,
                                    f'provider.hooks_removed_{self._name}')
        except Exception as e:
            logger.warning(t('provider.hooks_remove_failed', error=e))
            return False


# === 具體 Provider ===

class ClaudeProvider(BaseProvider):
    """Claude Code CLI 提供者"""
    _name = "claude"
    _command = "claude"
    _config_subpath = '.claude/settings.local.json'
    _hook_key = "Stop"
    _hook_timeout = 30


class GeminiProvider(BaseProvider):
    """Gemini CLI 提供者"""
    _name = "gemini"
    _command = "gemini"
    _config_subpath = '.gemini/settings.json'
    _hook_key = "AfterAgent"
    _hook_timeout = 30000  # 毫秒
    _hook_needs_matcher = True
    _extra_enter = True

    def _post_configure_hooks(self, work_dir: str) -> None:
        self._trust_folder(work_dir)

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
                return

            trusted[abs_path] = "TRUST_FOLDER"
            with open(trusted_file, 'w', encoding='utf-8') as f:
                json.dump(trusted, f, indent=2, ensure_ascii=False)

            logger.info(t('provider.folder_trusted', path=abs_path))
        except Exception as e:
            logger.warning(t('provider.folder_trust_failed', error=e))


class CodexProvider(BaseProvider):
    """OpenAI Codex CLI 提供者"""
    _name = "codex"
    _command = "codex"
    _config_subpath = '.codex/hooks.json'
    _hook_key = "Stop"
    _hook_timeout = 30
    _pre_enter_delay = 0.15  # ink/React TUI 需要延遲，避免 Enter 被當成換行

    def _post_configure_hooks(self, work_dir: str) -> None:
        self._enable_hooks_feature_flag()
        self._trust_folder(work_dir)

    @staticmethod
    def _enable_hooks_feature_flag() -> None:
        """在 ~/.codex/config.toml 中啟用 codex_hooks = true"""
        try:
            config_dir = Path.home() / '.codex'
            config_dir.mkdir(exist_ok=True)
            config_file = config_dir / 'config.toml'

            lines = []
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

            feature_section_idx = None
            hook_line_idx = None
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == '[features]':
                    feature_section_idx = i
                if 'codex_hooks' in stripped:
                    hook_line_idx = i

            if hook_line_idx is not None:
                lines[hook_line_idx] = 'codex_hooks = true\n'
            elif feature_section_idx is not None:
                lines.insert(feature_section_idx + 1, 'codex_hooks = true\n')
            else:
                if lines and not lines[-1].endswith('\n'):
                    lines.append('\n')
                lines.append('\n[features]\n')
                lines.append('codex_hooks = true\n')

            with open(config_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            logger.info(t('provider.hooks_feature_enabled', path=str(config_file)))
        except Exception as e:
            logger.warning(t('provider.hooks_feature_enable_failed', error=e))

    @staticmethod
    def _trust_folder(work_dir: str) -> None:
        """在 ~/.codex/config.toml 中將目錄標記為信任"""
        try:
            abs_path = str(Path(work_dir).resolve())
            config_dir = Path.home() / '.codex'
            config_dir.mkdir(exist_ok=True)
            config_file = config_dir / 'config.toml'

            content = ''
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    content = f.read()

            section_header = f'[projects."{abs_path}"]'
            if section_header in content:
                return

            if content and not content.endswith('\n'):
                content += '\n'
            content += f'\n{section_header}\ntrust_level = "trusted"\n'

            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(t('provider.folder_trusted_codex', path=abs_path))
        except Exception as e:
            logger.warning(t('provider.folder_trust_failed', error=e))


# === Provider 註冊 ===

_PROVIDERS = {
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
    "codex": CodexProvider,
}


def create_provider(cli_type: str) -> CliProvider:
    """根據 cli_type 建立對應的 Provider"""
    provider_class = _PROVIDERS.get(cli_type)
    if provider_class is None:
        supported = ', '.join(_PROVIDERS.keys())
        raise ValueError(t('provider.unsupported_cli', cli_type=cli_type, supported=supported))
    return provider_class()
