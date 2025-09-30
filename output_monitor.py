#!/usr/bin/env python3
"""
輸出監控和過濾模組
監控 Claude Code 的輸出，識別最終回覆並過濾不需要的內容
"""

import re
import time
import threading
import logging
from collections import deque

logger = logging.getLogger(__name__)


class OutputMonitor:
    """輸出監控器"""

    def __init__(self, tmux_bridge, idle_timeout=3.0):
        """
        初始化監控器

        Args:
            tmux_bridge: TmuxBridge 實例
            idle_timeout: 閒置多久後認為輸出完成（秒）
        """
        self.tmux_bridge = tmux_bridge
        self.idle_timeout = idle_timeout

        # 輸出緩衝區
        self.buffer = ""
        self.last_output_time = time.time()

        # 監控狀態
        self.is_monitoring = False
        self.monitor_thread = None

        # 回調函數
        self.on_output_complete = None

    def clean_ansi_codes(self, text):
        """
        清除 ANSI 控制碼

        Args:
            text: 原始文字

        Returns:
            str: 清除後的文字
        """
        # 清除 ANSI 顏色和控制碼
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        text = ansi_escape.sub('', text)

        # 清除其他控制字元（保留換行和 tab）
        text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)

        return text

    def filter_tool_calls(self, text):
        """
        過濾 tool 調用的詳細內容

        Args:
            text: 原始文字

        Returns:
            str: 過濾後的文字
        """
        # 檢測並摺疊 tool 調用的 JSON 內容
        # 保留 tool 名稱，但隱藏詳細參數

        # 匹配類似 <invoke name="..."> ... </invoke> 的內容
        tool_pattern = re.compile(
            r'<invoke name="([^"]+)">.*?</invoke>',
            re.DOTALL
        )

        def replace_tool(match):
            tool_name = match.group(1)
            return f'[調用工具: {tool_name}]'

        text = tool_pattern.sub(replace_tool, text)

        return text

    def filter_thinking_process(self, text):
        """
        過濾 thinking 過程（可選）

        Args:
            text: 原始文字

        Returns:
            str: 過濾後的文字
        """
        # 如果有 thinking 標記，可以選擇過濾
        # 這裡暫時保留，因為某些情況下 thinking 包含有用資訊

        return text

    def is_likely_user_input(self, text):
        """
        判斷是否是用戶輸入或處理過程（而不是 Claude 的最終回覆）

        Args:
            text: 文字內容

        Returns:
            bool: 是否是用戶輸入或處理過程
        """
        # 如果內容太短，可能只是輸入
        if len(text.strip()) < 20:
            return True

        # 如果只包含提示符和簡短文字
        if text.strip().startswith('>') and len(text.strip()) < 50:
            return True

        # 過濾 Claude Code 的處理狀態訊息
        processing_keywords = [
            'Whisking…', 'Wibbling…', 'Thinking…',
            'esc to interrupt', 'Press shift+tab',
            '? for shortcuts', 'Plan Mode'
        ]

        if any(keyword in text for keyword in processing_keywords):
            # 如果大部分內容是處理訊息，而沒有實質回覆
            text_without_processing = text
            for keyword in processing_keywords:
                text_without_processing = text_without_processing.replace(keyword, '')

            # 清理後如果剩餘內容太少，認為是處理過程
            cleaned = text_without_processing.strip()
            if len(cleaned) < 100:
                return True

        # 如果只是重複的短句
        lines = text.strip().split('\n')
        if len(lines) <= 3 and all(len(line.strip()) < 50 for line in lines):
            return True

        return False

    def detect_confirmation_prompt(self, text):
        """
        檢測是否包含確認提示

        Args:
            text: 文字內容

        Returns:
            dict or None: 如果檢測到確認提示，返回 {'type': 類型, 'options': 選項列表}
        """
        # 檢測文件創建確認
        if 'Do you want to create' in text or 'Do you want to' in text:
            # 提取選項
            options = []
            lines = text.split('\n')
            for line in lines:
                # 匹配 "❯ 1. Yes" 或 "2. No" 格式
                if re.match(r'^\s*[❯]?\s*(\d+)\.\s*(.+)', line):
                    match = re.match(r'^\s*[❯]?\s*(\d+)\.\s*(.+)', line)
                    num = match.group(1)
                    option = match.group(2).strip()
                    options.append({'num': num, 'text': option})

            if options:
                return {
                    'type': 'confirmation',
                    'options': options
                }

        return None

    def extract_actual_response(self, text):
        """
        從混雜的輸出中提取 Claude 的實際回覆

        Args:
            text: 原始文字

        Returns:
            str: Claude 的實際回覆內容，如果找不到則返回 None
        """
        # 尋找 ⏺ 符號（記錄符號），這通常標記 Claude 的回覆開始
        if '⏺' in text:
            # 提取 ⏺ 之後的內容
            parts = text.split('⏺')
            if len(parts) > 1:
                response = parts[-1]  # 取最後一個（最新的回覆）

                # 移除後續的處理狀態訊息
                # 找到第一個處理狀態，截斷
                lines = response.split('\n')
                result_lines = []

                for line in lines:
                    # 遇到處理狀態就停止
                    if any(keyword in line for keyword in ['Contemplating', 'Whisking', 'Wibbling', 'Crafting',
                                                            'Thinking', 'esc to interrupt', '? for shortcuts']):
                        break
                    # 跳過分隔線
                    if line.strip() == '─' * len(line.strip()) and len(line.strip()) > 10:
                        continue
                    result_lines.append(line)

                result = '\n'.join(result_lines).strip()
                if result and len(result) > 10:
                    return result

        # 如果沒有找到 ⏺，返回 None 表示沒有提取到
        return None

    def summarize_long_content(self, text):
        """
        簡化冗長的內容

        Args:
            text: 原始文字

        Returns:
            str: 簡化後的文字
        """
        lines = text.split('\n')

        # DEBUG: 打印原始內容前幾行（已關閉）
        # logger.debug(f"summarize_long_content 收到內容（前20行）:")
        # for i, line in enumerate(lines[:20]):
        #     logger.debug(f"  {i}: {repr(line)}")

        # 檢測確認提示框
        if any('Do you want' in line or 'May I proceed' in line or 'proceed' in line for line in lines):
            summary_lines = []

            # 提取工具調用資訊（如 Write(example.txt)）
            for line in lines:
                if '(' in line and ')' in line and any(tool in line for tool in ['Write', 'Edit', 'Read', 'Bash']):
                    summary_lines.append(line.strip())
                    break

            # 提取確認問題和選項
            in_question = False
            for line in lines:
                stripped = line.strip()

                # 跳過框線
                if stripped.startswith('╭') or stripped.startswith('╰'):
                    continue

                # 處理 │ 框線內容
                if '│' in line:
                    content = line.replace('│', '').strip()
                    if content and not content.startswith('╭') and not content.startswith('╰'):
                        # 檢測確認問題
                        if 'Do you want' in content or 'proceed' in content or '是否' in content:
                            summary_lines.append(content)
                            in_question = True
                        # 保留框線內的選項（匹配 ❯ 1. Yes 或 1. Yes 格式）
                        elif in_question:
                            # 檢查是否包含選項模式
                            if '❯' in content or re.search(r'^\d+\.', content.lstrip()):
                                summary_lines.append(content)
                    continue

                # 保留框線外的選項
                if in_question:
                    # 匹配選項格式：❯ 1. xxx 或 1. xxx
                    if stripped.startswith('❯') or (stripped and len(stripped) > 0 and stripped[0].isdigit() and '.' in stripped):
                        summary_lines.append(stripped)

            if summary_lines:
                return '\n'.join(summary_lines)

        # 檢測是否是文件內容預覽（通常很長）
        if len(lines) > 50:
            summary_lines = []

            # 檢測文件創建/編輯提示
            if any('Do you want to' in line for line in lines):
                for i, line in enumerate(lines):
                    if 'Do you want to' in line:
                        # 提取文件名
                        for j in range(max(0, i-5), i):
                            if '.md' in lines[j] or '.py' in lines[j] or '.js' in lines[j] or '.txt' in lines[j]:
                                summary_lines.append(f"📝 文件操作: {lines[j].strip()}")
                                break

                        # 保留確認提示部分
                        summary_lines.extend(lines[i:])
                        break

                if summary_lines:
                    return '\n'.join(summary_lines)

        return text

    def clean_output(self, text):
        """
        清理輸出內容

        Args:
            text: 原始文字

        Returns:
            str: 清理後的文字
        """
        # 1. 清除 ANSI 控制碼
        text = self.clean_ansi_codes(text)

        # 2. 嘗試提取實際回覆
        actual_response = self.extract_actual_response(text)
        if actual_response is not None:
            # 成功提取到回覆，使用提取的內容
            text = actual_response
        else:
            # 沒有找到 ⏺ 標記，使用原始過濾邏輯
            # 過濾可能是用戶輸入的內容
            if self.is_likely_user_input(text):
                return ""

        # 3. 簡化冗長內容
        text = self.summarize_long_content(text)

        # 4. 過濾 tool 調用詳細內容
        text = self.filter_tool_calls(text)

        # 5. 移除分隔線和提示符
        lines = text.split('\n')
        clean_lines = []
        for line in lines:
            # 跳過分隔線
            if line.strip() == '─' * len(line.strip()) and len(line.strip()) > 10:
                continue
            # 跳過純提示符
            if line.strip() in ['>', '? for shortcuts']:
                continue
            # 跳過空的框線
            if re.match(r'^[│╭╰╯├─┤┼]+\s*$', line.strip()):
                continue
            clean_lines.append(line)

        text = '\n'.join(clean_lines)

        # 6. 清理多餘的空行（保留最多 2 個連續空行）
        text = re.sub(r'\n{3,}', '\n\n', text)

        # 7. 清理首尾空白
        text = text.strip()

        # 8. 過濾太短的內容（可能只是輸入回顯）
        if len(text) < 10:
            return ""

        return text

    def is_response_complete(self, text):
        """
        判斷回覆是否完成

        Args:
            text: 當前緩衝區內容

        Returns:
            bool: 是否完成
        """
        # 方法 1: 檢測 Claude Code 的提示符
        # Claude Code 在等待輸入時通常會顯示提示符

        # 方法 2: 檢測閒置時間
        current_time = time.time()
        idle_time = current_time - self.last_output_time

        # 特殊處理：如果包含確認提示但沒有選項，延長等待時間
        if any(keyword in text for keyword in ['Do you want', 'Do you approve', 'May I proceed', 'proceed']):
            # 檢查是否有選項（1. 2. 3. 或 ❯）
            has_options = bool(re.search(r'[❯]?\s*\d+\.\s+', text))
            if not has_options:
                # 沒有選項，等待更長時間（最多15秒）
                if idle_time < 15.0:
                    # logger.debug(f"檢測到確認提示但無選項，繼續等待... ({idle_time:.1f}s)")
                    return False

        if idle_time >= self.idle_timeout:
            # 閒置超過設定時間，認為輸出完成
            return True

        return False

    def start_monitoring(self, callback=None):
        """
        開始監控

        Args:
            callback: 當有完整輸出時調用的回調函數
        """
        if self.is_monitoring:
            print("⚠️  監控已在運行中")
            return

        self.on_output_complete = callback
        self.is_monitoring = True

        # 啟動監控執行緒
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

        print("👁️  開始監控 Claude Code 輸出")

    def _monitor_loop(self):
        """監控循環（在獨立執行緒中運行）"""
        consecutive_empty_reads = 0

        while self.is_monitoring:
            try:
                # 讀取新輸出
                new_output = self.tmux_bridge.read_new_output()

                if new_output:
                    # 有新輸出
                    self.buffer += new_output
                    self.last_output_time = time.time()
                    consecutive_empty_reads = 0

                else:
                    # 沒有新輸出
                    consecutive_empty_reads += 1

                    # 檢查是否完成
                    if self.buffer and self.is_response_complete(self.buffer):
                        # 清理並發送輸出
                        cleaned_output = self.clean_output(self.buffer)

                        if cleaned_output and self.on_output_complete:
                            self.on_output_complete(cleaned_output)

                        # 清空緩衝區
                        self.buffer = ""

                # 等待一段時間再檢查
                time.sleep(0.2)

            except Exception as e:
                print(f"❌ 監控錯誤: {e}")
                time.sleep(1)

    def stop_monitoring(self):
        """停止監控"""
        self.is_monitoring = False

        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)

        print("🛑 停止監控")

    def get_current_buffer(self):
        """
        獲取當前緩衝區內容

        Returns:
            str: 當前緩衝的輸出
        """
        return self.clean_output(self.buffer)


class MessageFormatter:
    """訊息格式化器"""

    MAX_SINGLE_MESSAGE_LENGTH = 4000  # Telegram 單條訊息最大長度
    MAX_TOTAL_LENGTH = 12000  # 超過這個長度就上傳為文件

    @staticmethod
    def format_for_telegram(text):
        """
        格式化文字以便在 Telegram 中發送

        Args:
            text: 要發送的文字

        Returns:
            list: 訊息列表（可能分段）或 dict: {'type': 'file', 'content': ...}
        """
        if not text:
            return []

        length = len(text)

        # 情況 1: 短訊息，直接發送
        if length <= MessageFormatter.MAX_SINGLE_MESSAGE_LENGTH:
            return [text]

        # 情況 2: 中等長度，分段發送
        if length <= MessageFormatter.MAX_TOTAL_LENGTH:
            return MessageFormatter._split_message(text)

        # 情況 3: 超長訊息，上傳為文件
        return [{
            'type': 'file',
            'content': text,
            'filename': f'claude_output_{int(time.time())}.txt'
        }]

    @staticmethod
    def _split_message(text):
        """
        將長訊息分段

        Args:
            text: 要分段的文字

        Returns:
            list: 分段後的訊息列表
        """
        segments = []
        current_segment = ""

        # 按行分割
        lines = text.split('\n')

        for line in lines:
            # 如果加上這行後超過限制，就開始新段
            if len(current_segment) + len(line) + 1 > MessageFormatter.MAX_SINGLE_MESSAGE_LENGTH:
                if current_segment:
                    segments.append(current_segment)
                    current_segment = line
                else:
                    # 單行就超過限制，強制分割
                    segments.append(line[:MessageFormatter.MAX_SINGLE_MESSAGE_LENGTH])
                    current_segment = line[MessageFormatter.MAX_SINGLE_MESSAGE_LENGTH:]
            else:
                if current_segment:
                    current_segment += '\n' + line
                else:
                    current_segment = line

        # 加入最後一段
        if current_segment:
            segments.append(current_segment)

        # 添加分段標記
        total_segments = len(segments)
        if total_segments > 1:
            formatted_segments = []
            for i, segment in enumerate(segments, 1):
                formatted_segments.append(f"[{i}/{total_segments}]\n\n{segment}")
            return formatted_segments

        return segments


if __name__ == '__main__':
    # 測試代碼
    test_text = "\x1b[32m這是綠色文字\x1b[0m\n\n\n\n包含很多空行\n\n\n正常文字"
    monitor = OutputMonitor(None)
    cleaned = monitor.clean_output(test_text)
    print("清理後:")
    print(cleaned)