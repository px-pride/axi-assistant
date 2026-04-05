# Test Instance Management

You have access to a disposable test instance system. Use it to test code changes before applying them to your own running code.

## Rule: Never Edit Your Own Running Code

You must NEVER directly modify the code you are currently running. Instead:
1. Create a test instance
2. Spawn an agent in the test worktree to make changes
3. Test the changes via Discord MCP tools
4. When verified, commit in the worktree, merge to main, and restart yourself

Humans using Claude Code on the server can edit your code directly (the supervisor has auto-rollback), but you cannot — a bad edit could crash you mid-operation.

## CLI Commands

Run these via Bash:

- **`uv run python axi_test.py up <name> [--guild GUILD] [--wait] [--wait-timeout SECS]`** — Reserve a bot/guild slot for a test instance. Writes `.env` and creates the data directory. Use `--wait` to poll until a bot token slot is available (default timeout: 2 hours).
- **`uv run python axi_test.py down <name>`** — Release a bot/guild reservation.
- **`uv run python axi_test.py restart <name>`** — Restart a test instance after code changes.
- **`uv run python axi_test.py list`** — Show all test instances and their status.
- **`uv run python axi_test.py merge`** — Merge current worktree branch into the main repo. Auto-detects the main repo via git. No-op if already in main.
- **`uv run python axi_test.py msg <name> "<message>" [--timeout SECS]`** — Send a message to a test instance and wait for its response.
- **`uv run python axi_test.py logs <name>`** — Tail the test instance's journal logs.

## Test Guilds

Test instances run in separate Discord guilds. Your Discord MCP tools (`discord_list_channels`, `discord_read_messages`, `discord_send_message`) work in these guilds using your own bot token.

Available test guilds are listed in `~/.config/axi/test-config.json`. Read the config to get guild names and IDs.

## Workflow: Testing a Code Change

The parent (Axi master) prepares the working directory, then spawns an agent in it. The agent codes, tests, and ships — it never needs to reference the main repo directly.

**Parent responsibilities:**
1. Create a git worktree if needed (or use an existing one, or use the main repo)
2. Spawn the coding agent with `cwd` set to the working directory (worktree or main repo)

**Agent workflow:**
1. **Edit files** in cwd (all edits naturally go to the right place)
2. **Reserve a test slot**: `uv run python axi_test.py up <name> --wait` — only when ready to test
3. **Restart**: `uv run python axi_test.py restart <name>`
4. **Test via Discord MCP**: Use `discord_send_message` to the test guild, then `discord_read_messages` or `wait_for_message.py` to check the response
5. **Iterate**: Repeat 1-4 until it works
6. **Tear down**: `uv run python axi_test.py down <name>` — always release the slot when done testing
7. **Commit**: `git add -A && git commit -m "description"`
8. **Merge to main**: `uv run python axi_test.py merge` — auto-detects worktree vs main, no-op if already in main
9. **Restart**: Tell the parent to restart so it picks up the merged changes (spawned agents do NOT have `axi_restart` — only the master can restart itself)

## Fast Message Polling

For scripted test interactions, use `wait_for_message.py`:

```bash
# Send a message, then wait for the bot's response
python wait_for_message.py <channel_id> --after <message_id> --timeout 60
```

This polls every 2 seconds and returns as soon as a non-system message appears. Output is JSONL with a trailing cursor line.

## Tips

- Instance names should be short and descriptive: `ping-test`, `schedule-fix`, `auth-refactor`
- Each test instance gets its own `.env`, venv, and data directory — fully isolated
- The test bot token can only run one instance at a time. Always use `--wait` when creating instances so you queue up if the slot is busy. If `--wait` times out, ask the user how to proceed — do **not** tear down someone else's instance
- Test instances use `Restart=on-failure` — they stay stopped when you stop them (unlike your own `Restart=always`)
- Crash handler and rollback are off by default on test instances (no `ENABLE_CRASH_HANDLER` or `ENABLE_ROLLBACK` set)
