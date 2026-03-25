#!/usr/bin/env python3
"""
Message Router - 訊息路由器
解析 #project 語法並路由到對應的會話
"""

from typing import List, Tuple

from config import patterns
from i18n import t


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
            "#webapp 查詢路徑" -> [('webapp', '查詢路徑')]
            "#all 執行測試" -> [('webapp', '執行測試'), ('api', '執行測試')]
            "查詢路徑" -> [('__error__', '請使用 #project 指定目標會話')]
        """
        # 檢測 #all
        if message.startswith('#all '):
            actual_message = message[5:].strip()
            sessions = self.session_manager.get_all_sessions()
            return [(name, actual_message) for name in sessions]

        # 檢測 #session_name（允許字母數字、底線、連字號）
        match = patterns.MESSAGE_ROUTE.match(message)
        if match:
            session_name = match.group(1)
            actual_message = match.group(2).strip()

            # 檢查會話是否存在
            if self.session_manager.get_session(session_name):
                return [(session_name, actual_message)]
            else:
                # 會話不存在，返回錯誤標記
                return [('__error__', t('router.session_not_found', name=session_name))]

        # 沒有指定會話，返回錯誤提示
        sessions = self.session_manager.get_all_sessions()
        if not sessions:
            return [('__error__', t('router.no_sessions'))]

        # 生成可用會話列表
        session_list = t('router.separator').join([f'#{name}' for name in sessions])
        return [('__error__', t('router.no_target', session_list=session_list, example=sessions[0]))]

    def format_session_list(self) -> str:
        """
        格式化會話列表

        Returns:
            str: 格式化的會話列表
        """
        sessions = self.session_manager.get_all_sessions()

        if not sessions:
            return t('router.no_sessions_configured')

        lines = [t('router.available_sessions') + "\n"]
        for i, name in enumerate(sessions, 1):
            config = self.session_manager.get_session(name)
            lines.append(f"{i}. #{name}")
            lines.append(f"   {t('router.path_label')}: {config.path}")
            lines.append(f"   tmux: {config.tmux_session}\n")

        example_name = sessions[0]
        lines.append(t('router.usage_header'))
        lines.append(t('router.usage_single', name=example_name))
        lines.append(t('router.usage_all'))

        return '\n'.join(lines)


if __name__ == '__main__':
    # 測試代碼
    from session_manager import SessionManager

    manager = SessionManager()
    manager.add_session('webapp', '/path/to/webapp')
    manager.add_session('api', '/path/to/api')

    router = MessageRouter(manager)

    # 測試解析
    tests = [
        "#webapp 查詢路徑",
        "#all 執行測試",
        "普通訊息",
        "#notexist 測試"
    ]

    for test in tests:
        result = router.parse_message(test)
        print(f"\n輸入: {test}")
        print(f"輸出: {result}")

    print("\n" + router.format_session_list())