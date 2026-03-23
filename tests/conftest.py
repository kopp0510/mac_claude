#!/usr/bin/env python3
"""
Pytest 配置和共用 fixtures
"""

import os
import sys
import pytest
import tempfile

# 添加專案根目錄到 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def temp_dir():
    """建立臨時目錄"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_env(monkeypatch):
    """模擬環境變數"""
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test_token_12345')
    monkeypatch.setenv('ALLOWED_USER_IDS', '123456,789012')
    monkeypatch.setenv('SESSIONS_CONFIG_FILE', 'sessions.yaml')


@pytest.fixture
def sample_transcript():
    """範例 transcript 數據"""
    return {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Hello"}]
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi there! How can I help you?"}]
            }
        ]
    }


@pytest.fixture
def sample_sessions_config():
    """範例會話配置"""
    return {
        "sessions": [
            {"name": "test1", "path": "/tmp/test1"},
            {"name": "test2", "path": "/tmp/test2", "tmux": "claude-test2"}
        ]
    }
