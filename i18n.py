#!/usr/bin/env python3
"""
國際化（i18n）模組
透過 .env 的 LANGUAGE 設定選擇語言
"""

import json
import os
from pathlib import Path

SUPPORTED_LANGUAGES = ['zh-TW', 'en']
DEFAULT_LANGUAGE = 'zh-TW'

_translations: dict = {}
_current_language: str = DEFAULT_LANGUAGE


def init(language: str = None):
    """初始化 i18n"""
    global _translations, _current_language

    lang = language or os.getenv('LANGUAGE', DEFAULT_LANGUAGE)
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE

    _current_language = lang
    locales_dir = Path(__file__).parent / 'locales'
    locale_file = locales_dir / f'{lang}.json'

    with open(locale_file, 'r', encoding='utf-8') as f:
        _translations = json.load(f)


def t(key: str, **kwargs) -> str:
    """翻譯函數

    Args:
        key: 點分隔的翻譯 key，如 'bot.unauthorized'
        **kwargs: 變數替換

    Returns:
        翻譯後的字串，key 不存在時回傳 key 本身
    """
    if not _translations:
        init()

    value = _translations
    for part in key.split('.'):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return key

    if value is None or not isinstance(value, str):
        return key

    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value

    return value


def get_language() -> str:
    """取得當前語言"""
    return _current_language
