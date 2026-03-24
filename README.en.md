[繁體中文](README.md) | **English**

# Claude Code Telegram Multi-Session Bridge

Interact bidirectionally with multiple running Claude Code instances via Telegram.

## Features

- 🔄 **Bidirectional Communication**: Claude Code output is pushed to Telegram in real-time; Telegram messages are sent back to Claude Code
- 🔀 **Multi-Session Parallel**: Manage multiple Claude Code instances simultaneously, running tasks in parallel
- 🏷️ **Source Tagging**: All replies are tagged with source `📍 project` for clear identification
- 📮 **Smart Routing**: Use `#project` syntax to target specific sessions, or `#all` to broadcast to all
- 🖥️ **Concurrent Access**: Interact with Claude Code from both terminal and Telegram at the same time
- 🤖 **Hook-Based Notifications**: Instant push when Claude finishes responding via Stop hook, latency < 1 second
- 🎯 **Interactive Buttons**: Confirmation prompts are automatically converted to Inline Keyboard buttons
- 📊 **Chunked Messages**: Long messages are automatically split; extra-long content is uploaded as files
- 🔒 **User Authentication**: Only authorized users can access the bot
- ⚡ **Message Queue**: Sequential processing to avoid conflicts

## System Architecture

```
                    Telegram User
                         │
                    #rental message
                    #api message
                    #all message
                         │
                         ▼
                 ┌───────────────┐
                 │ telegram_bot  │
                 │   (router)    │
                 └───────┬───────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │  tmux   │    │  tmux   │    │  tmux   │
    │ rental  │    │   api   │    │  docs   │
    └────┬────┘    └────┬────┘    └────┬────┘
         │              │              │
         ▼              ▼              ▼
    [#rental]       [#api]         [#docs]
         │              │              │
         └──────────────┼──────────────┘
                        ▼
                    Telegram
```

## Quick Start

### 1. Install Dependencies

```bash
# Install tmux
brew install tmux

# Install Python dependencies
pip install -r requirements.txt
```

### 2. Create a Telegram Bot

1. Find [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` to create a bot
3. Save the Bot Token

### 3. Get Your User ID

1. Find [@userinfobot](https://t.me/userinfobot) on Telegram
2. Send `/start`
3. Note your User ID

### 4. Configuration

**Create .env file:**

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
ALLOWED_USER_IDS=your_user_id
```

**Create sessions.yaml configuration:**

```yaml
sessions:
  - name: rental
    path: /Users/your_username/project/rental-management
    tmux: claude-rental

  - name: api
    path: /Users/your_username/project/api-server
    tmux: claude-api
```

### 5. Launch

```bash
./bridge.sh start
./bridge.sh status
./bridge.sh stop
```

## Usage

### Message Routing Syntax

Send messages in Telegram:

```
#rental check current path           → Send to rental session
#api run tests                       → Send to api session
#all generate docs                   → Send to all sessions
```

**Note**: You must use the `#` prefix to specify a target session. Messages without a prefix will return an error with a list of available sessions.

### Reply Format

All replies are tagged with their source (Hook-driven, instant push):

```
📍 rental

This is a rent management system...

📍 api

Tests complete! All tests passed.
```

### Telegram Commands

- `/start` - Show help and session list
- `/status` - View all session status
- `/sessions` - View session list
- `/restart #session` - Restart a specific session
- `/reload` - Reload sessions.yaml configuration (no bot restart needed)

### Interactive Buttons

When Claude asks for confirmation, buttons are displayed automatically:

```
[#rental]
Do you want to proceed with editing these 3 files?
  1. Yes, proceed with edits
  2. No, cancel

[✅ 1. Yes]  [❌ 2. No]  ← Click buttons to auto-reply
```

### Management Commands

```bash
./bridge.sh start          # Start bot in background
./bridge.sh stop           # Stop bot and clean up tmux sessions
./bridge.sh restart        # Restart bot
./bridge.sh status         # View bot and session status
./bridge.sh logs           # View bot main log
./bridge.sh logs rental    # View specific session log
./bridge.sh validate       # Validate configuration
```

### Connect to Terminal

You can attach to tmux sessions at any time for direct access:

```bash
# List all sessions
tmux ls

# Attach to a specific session (tmux name from sessions.yaml)
tmux attach -t <tmux_session_name>

# Detach without terminating (key combo)
Ctrl+B, then press D
```

## Configuration

### sessions.yaml Format

```yaml
sessions:
  - name: session_name          # Used for #name routing
    path: project_path          # Claude Code working directory
    tmux: tmux_session_name     # tmux session name (optional, defaults to claude-{name})
    claude_args: "launch args"  # Claude CLI arguments (optional, e.g. --model sonnet)
```

**Example:**

```yaml
sessions:
  - name: rental
    path: /path/to/rental-management
    tmux: claude-rental

  - name: api
    path: /path/to/api-server
    tmux: claude-api

  - name: docs
    path: /path/to/documentation
    # tmux session name defaults to claude-docs

  - name: sandbox
    path: /path/to/sandbox
    claude_args: "--dangerously-skip-permissions --model sonnet"
```

### .env Configuration

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
ALLOWED_USER_IDS=user_id_1,user_id_2
```

**Variables:**
- `TELEGRAM_BOT_TOKEN` - Required, obtained from BotFather
- `ALLOWED_USER_IDS` - Required, comma-separated user IDs (bot refuses to start if empty)

## How It Works

### Instant Notifications (Hook-Driven)

1. Claude Code triggers the Stop hook when it finishes responding
2. `notify_telegram.sh` reads `last_assistant_message` from hook stdin
3. `send_telegram_notification.py` pushes instantly via Telegram Bot API
4. Latency < 1 second, event-driven, clean reply content without ANSI codes

### Message Routing

1. `MessageRouter` parses `#project` syntax
2. `SessionManager` routes messages to the corresponding session
3. Uses `tmux send-keys` to inject into Claude Code
4. Supports `#all` to broadcast to all sessions

### Parallel Execution

- All sessions run independently without interference
- Each session has its own Hook notification
- Replies are pushed instantly in completion order, tagged with source

## File Description

**Main Program:**
- `telegram_bot_multi.py` - Telegram Bot main program

**Core Modules:**
- `session_manager.py` - Session manager
- `message_router.py` - Message router
- `tmux_bridge.py` - Tmux bridge module
- `config.py` - Centralized configuration management

**Hook Notifications:**
- `notify_telegram.sh` - Claude Code Stop hook script
- `send_telegram_notification.py` - Telegram API sender

**Launch & Configuration:**
- `bridge.sh` - Unified management tool (start/stop/restart/status/logs/validate)
- `sessions.yaml` - Session configuration
- `.env` - Environment variables
- `requirements.txt` - Python dependencies

## Security

1. **User Restriction**: `ALLOWED_USER_IDS` is required; bot refuses to start if not set
2. **Config Protection**: `.env` is in `.gitignore`; never commit sensitive information
3. **Working Directory Permissions**: Ensure project directory permissions are correct
4. **Network Security**: Uses Polling mode, no public URL required
5. **Shell Injection Protection**: `shlex.quote()` is used for pipe-pane paths and hook commands
6. **Rate Limiting**: Maximum 3 messages per user per 5 seconds
7. **Pinned Dependencies**: Exact versions locked to prevent supply chain attacks

## Troubleshooting

### Session Cannot Be Created

```bash
# Check tmux
which tmux

# Manual test
tmux new -s test
```

### Cannot Receive Output

```bash
# Check log files
ls -la ~/.claude_bridge/logs/claude_*.log

# View logs
tail -f ~/.claude_bridge/logs/claude_rental.log
```

### Bot Cannot Start

```bash
# Check configuration
cat .env
cat sessions.yaml

# Check Python modules
python3 -c "import telegram; import yaml; import requests"
```

### Hook Notifications Not Triggering

```bash
# Check hook config (must be in settings.local.json, not config.json)
cat /path/to/project/.claude/settings.local.json

# Check hook script permissions
ls -la notify_telegram.sh send_telegram_notification.py

# View hook debug logs
cat ~/.claude_bridge/logs/hook_debug_*.log

# View bot logs
./bridge.sh logs
```

### Messages Not Delivered

```bash
# Check tmux sessions
tmux ls

# Check status in Telegram
/status
```

## FAQ

**Q: Why use tmux?**
A: tmux provides session management and logging, forming the foundation for bidirectional communication.

**Q: Can it be used on a remote server?**
A: Yes! As long as the server can connect to the Telegram API.

**Q: How to stop the bridge?**
A: Use the management tool for one-click shutdown (automatically cleans up all tmux sessions):
```bash
./bridge.sh stop
```

**Q: How to add a new project?**
A: Add a new configuration in `sessions.yaml`, then use the `/reload` command to hot-reload without restarting the bot.

**Q: How to restart a problematic session?**
A: Use the `/restart #session` command to restart a specific session, e.g., `/restart #rental`. This terminates the old tmux session and creates a new one.

**Q: Do I need to restart the bot after changing configuration?**
A: No! Use the `/reload` command to hot-reload `sessions.yaml`. The system automatically adds new sessions, removes old ones, and keeps existing sessions running.

## License

MIT License

## Related Links

- [Claude Code Documentation](https://docs.claude.com/claude-code)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [python-telegram-bot](https://python-telegram-bot.readthedocs.io/)
- [tmux](https://github.com/tmux/tmux/wiki)
