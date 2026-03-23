FROM python:3.13-slim

# 安裝系統依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Node.js 22（Claude Code CLI 依賴）
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# 建立日誌目錄
RUN mkdir -p /root/.claude_bridge/logs

# 設定工作目錄
WORKDIR /app

# 安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式碼
COPY . .
RUN chmod +x bridge.sh notify_telegram.sh

CMD ["python3", "telegram_bot_multi.py"]
