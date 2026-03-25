#!/usr/bin/env python3
"""
i18n 模組測試
"""

import json
import pytest
from pathlib import Path

import i18n
from i18n import t, get_language


class TestI18nInit:
    """初始化測試"""

    def test_default_language(self):
        """測試預設語言為 zh-TW"""
        i18n.init()
        assert get_language() == 'zh-TW'

    def test_set_english(self):
        """測試設定英文"""
        i18n.init('en')
        assert get_language() == 'en'

    def test_unsupported_language_fallback(self):
        """測試不支援的語言 fallback 到 zh-TW"""
        i18n.init('ja')
        assert get_language() == 'zh-TW'

    def test_init_from_env(self, monkeypatch):
        """測試從環境變數讀取語言"""
        monkeypatch.setenv('LANGUAGE', 'en')
        i18n.init()
        assert get_language() == 'en'


class TestTranslation:
    """翻譯函數測試"""

    def setup_method(self):
        i18n.init('zh-TW')

    def test_simple_key(self):
        """測試簡單 key 查找"""
        result = t('bot.unauthorized')
        assert '未授權' in result

    def test_nested_key(self):
        """測試巢狀 key"""
        result = t('status_cmd.title')
        assert '會話狀態' in result

    def test_variable_substitution(self):
        """測試變數替換"""
        result = t('session.not_found', name='webapp')
        assert 'webapp' in result

    def test_multiple_variables(self):
        """測試多個變數替換"""
        result = t('session.added', name='test', path='/tmp', cli_type='claude')
        assert 'test' in result
        assert '/tmp' in result
        assert 'claude' in result

    def test_missing_key_returns_key(self):
        """測試不存在的 key 回傳 key 本身"""
        assert t('nonexistent.key') == 'nonexistent.key'

    def test_missing_kwargs_no_crash(self):
        """測試缺少 kwargs 時不崩潰"""
        result = t('session.not_found')
        assert isinstance(result, str)

    def test_english_translation(self):
        """測試英文翻譯"""
        i18n.init('en')
        result = t('bot.unauthorized')
        assert 'Unauthorized' in result


class TestLocaleCompleteness:
    """翻譯檔完整性測試"""

    @staticmethod
    def _flatten_keys(d, prefix=''):
        """將巢狀 dict 展平為 dot-separated key 集合"""
        keys = set()
        for k, v in d.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys.update(TestLocaleCompleteness._flatten_keys(v, full_key))
            else:
                keys.add(full_key)
        return keys

    def test_en_covers_all_zh_tw_keys(self):
        """確保 en.json 涵蓋 zh-TW.json 所有 key"""
        locales_dir = Path(__file__).parent.parent / 'locales'

        with open(locales_dir / 'zh-TW.json', 'r', encoding='utf-8') as f:
            zh_data = json.load(f)
        with open(locales_dir / 'en.json', 'r', encoding='utf-8') as f:
            en_data = json.load(f)

        zh_keys = self._flatten_keys(zh_data)
        en_keys = self._flatten_keys(en_data)

        missing = zh_keys - en_keys
        assert not missing, f"en.json 缺少 key: {missing}"

    def test_no_empty_values_in_zh_tw(self):
        """確保 zh-TW.json 沒有空值"""
        locales_dir = Path(__file__).parent.parent / 'locales'
        with open(locales_dir / 'zh-TW.json', 'r', encoding='utf-8') as f:
            data = json.load(f)

        zh_keys = self._flatten_keys(data)
        for key in zh_keys:
            i18n.init('zh-TW')
            value = t(key)
            assert value != key, f"zh-TW.json key '{key}' 回傳了 key 本身（可能未定義）"

    def test_no_empty_values_in_en(self):
        """確保 en.json 沒有空值"""
        locales_dir = Path(__file__).parent.parent / 'locales'
        with open(locales_dir / 'en.json', 'r', encoding='utf-8') as f:
            data = json.load(f)

        en_keys = self._flatten_keys(data)
        for key in en_keys:
            i18n.init('en')
            value = t(key)
            assert value != key, f"en.json key '{key}' 回傳了 key 本身（可能未定義）"
