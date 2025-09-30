#!/usr/bin/env python3
"""
Message Router - 訊息路由器
解析 #project 語法並路由到對應的會話
"""

import re
from typing import List, Tuple, Optional


class MessageRouter:
    """訊息路由器"""

    def __init__(self, session_manager):
        self.session_manager = session_manager

    def parse_message(self, message: str) -> List[Tuple[str, str]]:
        """
        解析訊息，提取目標會話和實際內容

        Args:
            message: 原始訊息

        Returns:
            List of (session_name, actual_message)

        範例:
            "#rental 查詢路徑" -> [('rental', '查詢路徑')]
            "#all 執行測試" -> [('rental', '執行測試'), ('api', '執行測試')]
            "查詢路徑" -> [('rental', '查詢路徑')]  # 預設第一個
        """
        # 檢測 #all
        if message.startswith('#all '):
            actual_message = message[5:].strip()
            sessions = self.session_manager.get_all_sessions()
            return [(name, actual_message) for name in sessions]

        # 檢測 #session_name（允許下劃線）
        match = re.match(r'^#([\w]+)\s+(.+)$', message, re.DOTALL)
        if match:
            session_name = match.group(1)
            actual_message = match.group(2).strip()

            # 檢查會話是否存在
            if self.session_manager.get_session(session_name):
                return [(session_name, actual_message)]
            else:
                # 會話不存在，返回錯誤標記
                return [('__error__', f'會話不存在: {session_name}')]

        # 沒有指定會話，使用第一個（預設）
        sessions = self.session_manager.get_all_sessions()
        if sessions:
            return [(sessions[0], message)]

        return [('__error__', '沒有可用的會話')]

    def format_session_list(self) -> str:
        """
        格式化會話列表

        Returns:
            str: 格式化的會話列表
        """
        sessions = self.session_manager.get_all_sessions()

        if not sessions:
            return "目前沒有配置任何會話"

        lines = ["📋 可用的會話：\n"]
        for i, name in enumerate(sessions, 1):
            config = self.session_manager.get_session(name)
            lines.append(f"{i}. #{name}")
            lines.append(f"   路徑: {config.path}")
            lines.append(f"   tmux: {config.tmux_session}\n")

        lines.append("\n💡 使用方式：")
        lines.append("• #rental 你的訊息  → 發送給 rental 會話")
        lines.append("• #all 你的訊息     → 發送給所有會話")
        lines.append("• 你的訊息          → 發送給預設會話（第一個）")

        return '\n'.join(lines)


if __name__ == '__main__':
    # 測試代碼
    from session_manager import SessionManager

    manager = SessionManager()
    manager.add_session('rental', '/path/to/rental')
    manager.add_session('api', '/path/to/api')

    router = MessageRouter(manager)

    # 測試解析
    tests = [
        "#rental 查詢路徑",
        "#all 執行測試",
        "普通訊息",
        "#notexist 測試"
    ]

    for test in tests:
        result = router.parse_message(test)
        print(f"\n輸入: {test}")
        print(f"輸出: {result}")

    print("\n" + router.format_session_list())