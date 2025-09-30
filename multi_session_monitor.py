#!/usr/bin/env python3
"""
Multi-Session Monitor - 多會話監控器
同時監控多個 Claude Code 會話的輸出
"""

import logging
import threading
from output_monitor import OutputMonitor

logger = logging.getLogger(__name__)


class MultiSessionMonitor:
    """多會話監控器"""

    def __init__(self, session_manager, idle_timeout=8.0):
        """
        初始化

        Args:
            session_manager: SessionManager 實例
            idle_timeout: 閒置超時時間（秒）
        """
        self.session_manager = session_manager
        self.idle_timeout = idle_timeout
        self.monitors = {}  # {session_name: OutputMonitor}
        self.on_output_callback = None

    def setup_monitors(self, callback):
        """
        設置所有會話的監控器

        Args:
            callback: 回調函數，參數為 (session_name, output)
        """
        self.on_output_callback = callback

        for session_name in self.session_manager.get_all_sessions():
            bridge = self.session_manager.get_bridge(session_name)

            # 創建監控器
            monitor = OutputMonitor(bridge, idle_timeout=self.idle_timeout)

            # 包裝回調函數，添加會話名稱
            def make_callback(name):
                return lambda output: self._handle_output(name, output)

            # 啟動監控
            monitor.start_monitoring(callback=make_callback(session_name))

            self.monitors[session_name] = monitor

            logger.info(f"👁️  啟動監控: {session_name}")

    def _handle_output(self, session_name: str, output: str):
        """
        處理輸出

        Args:
            session_name: 會話名稱
            output: 輸出內容
        """
        if self.on_output_callback:
            self.on_output_callback(session_name, output)

    def stop_all(self):
        """停止所有監控"""
        for session_name, monitor in self.monitors.items():
            monitor.stop_monitoring()
            logger.info(f"🛑 停止監控: {session_name}")

    def get_buffer(self, session_name: str) -> str:
        """
        獲取指定會話的當前緩衝區

        Args:
            session_name: 會話名稱

        Returns:
            str: 緩衝區內容
        """
        monitor = self.monitors.get(session_name)
        if monitor:
            return monitor.get_current_buffer()
        return ""

    def clear_buffer(self, session_name: str):
        """清空指定會話的緩衝區"""
        monitor = self.monitors.get(session_name)
        if monitor:
            monitor.buffer = ""

    def detect_confirmation(self, session_name: str, output: str):
        """
        檢測確認提示

        Args:
            session_name: 會話名稱
            output: 輸出內容

        Returns:
            dict or None: 確認資訊
        """
        monitor = self.monitors.get(session_name)
        if monitor:
            return monitor.detect_confirmation_prompt(output)
        return None

    def add_monitor(self, session_name: str, session_manager, callback):
        """
        添加新會話的監控器

        Args:
            session_name: 會話名稱
            session_manager: SessionManager 實例
            callback: 回調函數
        """
        if session_name in self.monitors:
            logger.warning(f"⚠️  監控器已存在: {session_name}")
            return

        bridge = session_manager.get_bridge(session_name)
        if not bridge:
            logger.error(f"❌ 找不到 bridge: {session_name}")
            return

        # 創建監控器
        monitor = OutputMonitor(bridge, idle_timeout=self.idle_timeout)

        # 包裝回調函數
        def wrapped_callback(output):
            if self.on_output_callback:
                self.on_output_callback(session_name, output)

        # 啟動監控
        monitor.start_monitoring(callback=wrapped_callback)
        self.monitors[session_name] = monitor

        logger.info(f"👁️  新增監控: {session_name}")

    def stop_monitor(self, session_name: str):
        """
        停止指定會話的監控

        Args:
            session_name: 會話名稱
        """
        monitor = self.monitors.get(session_name)
        if monitor:
            monitor.stop_monitoring()
            del self.monitors[session_name]
            logger.info(f"🛑 停止監控: {session_name}")


if __name__ == '__main__':
    # 測試代碼
    from session_manager import SessionManager

    # 設置日誌
    logging.basicConfig(level=logging.INFO)

    manager = SessionManager()
    manager.add_session('test1', '/tmp/test1')
    manager.add_session('test2', '/tmp/test2')

    def output_callback(session_name, output):
        print(f"\n[{session_name}] 收到輸出: {output[:100]}...")

    monitor = MultiSessionMonitor(manager)
    monitor.setup_monitors(output_callback)

    print("✅ 多會話監控已啟動")
    print("按 Ctrl+C 停止...")

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 停止監控...")
        monitor.stop_all()