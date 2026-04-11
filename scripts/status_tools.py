"""MCP tool for setting the user to-do type emoji on a channel.

Each agent gets its own MCP server instance with its identity captured via
closures (same pattern as schedule_tools).

The tool renames the agent's Discord channel to ``{emoji}{base_name}`` so
the user's to-do type is visible at a glance in the sidebar.

Rename state (cooldown, pending queue) is shared between the MCP tool and
the auto-hourglass path in bot.py via ChannelStatusState instances stored
in a module-level registry.

Exports:
    make_status_mcp_server  — factory returning a per-agent McpSdkServerConfig
    strip_status_emoji      — strip emoji prefix from a channel name
    set_agent_status        — set status from outside the MCP tool (e.g. auto-hourglass)
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Awaitable, Callable

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Minimum seconds between channel renames (Discord allows 2 per 10 min).
RENAME_COOLDOWN_SECONDS = 300  # 5 minutes

#: Regex matching leading emoji characters (including ZWJ sequences, skin tones,
#: flags, keycap sequences, etc.).  Used to strip existing prefixes.
_EMOJI_PREFIX_RE = re.compile(
    r"^("
    r"[\U0001F1E0-\U0001F1FF]{2}"           # regional indicator flags
    r"|[\U0001F3FB-\U0001F3FF]"              # skin tone modifiers
    r"|[\U0001F000-\U0001FAFF]"              # misc symbols/emoji block
    r"|[\U00002300-\U000023FF]"              # misc technical (⏳, ⏰, ⌚, etc.)
    r"|[\U00002600-\U000027BF]"              # dingbats
    r"|[\U00002B00-\U00002BFF]"              # misc symbols and arrows (⭐, etc.)
    r"|[\U0000FE00-\U0000FE0F]"              # variation selectors
    r"|[\U0000200D]"                         # ZWJ
    r"|[\U000020E3]"                         # combining enclosing keycap
    r"|[\U00000023\U0000002A\U00000030-\U00000039]\U0000FE0F?\U000020E3"  # keycap
    r")+"
)

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def strip_status_emoji(channel_name: str) -> str:
    """Remove any leading emoji prefix from a channel name."""
    return _EMOJI_PREFIX_RE.sub("", channel_name)


# ---------------------------------------------------------------------------
# Emoji validation
# ---------------------------------------------------------------------------

#: Broad pattern that matches a single emoji (possibly multi-codepoint).
_SINGLE_EMOJI_RE = re.compile(
    r"^("
    r"[\U0001F1E0-\U0001F1FF]{2}"           # flag
    r"|[\U00000023\U0000002A\U00000030-\U00000039]\U0000FE0F?\U000020E3"  # keycap
    r"|[\U0001F000-\U0001FAFF]"
    r"[\U0000FE0F]?"
    r"(?:\U0000200D[\U0001F000-\U0001FAFF][\U0000FE0F]?)*"  # ZWJ seq
    r"[\U0001F3FB-\U0001F3FF]?"              # optional skin tone
    r"|[\U00002300-\U000023FF][\U0000FE0F]?" # misc technical (⏳, ⏰, etc.)
    r"|[\U00002600-\U000027BF][\U0000FE0F]?" # dingbats
    r"|[\U00002B00-\U00002BFF][\U0000FE0F]?" # misc symbols and arrows
    r")$"
)


def _is_single_emoji(text: str) -> bool:
    return bool(_SINGLE_EMOJI_RE.match(text))


# ---------------------------------------------------------------------------
# MCP response helpers
# ---------------------------------------------------------------------------


def _text(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}]}


def _error(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}


def _normalize_channel_name(name: str) -> str:
    """Normalize an agent name to a valid Discord channel name (matches bot.py)."""
    name = name.lower().replace(" ", "-")
    name = re.sub(r"[^a-z0-9\-_]", "", name)
    return name[:100]


# ---------------------------------------------------------------------------
# Shared per-agent state
# ---------------------------------------------------------------------------

#: Registry of per-agent status state, keyed by agent_name.
_status_states: dict[str, ChannelStatusState] = {}


class ChannelStatusState:
    """Per-agent rename state shared between the MCP tool and auto-hourglass."""

    def __init__(
        self,
        base_name: str,
        get_channel_id: Callable[[], int | None],
        discord_request: Callable[..., Awaitable[Any]],
    ):
        self.base_name = base_name
        self.get_channel_id = get_channel_id
        self.discord_request = discord_request
        self.last_rename_at: float = 0.0
        self.pending_emoji: str | None = None
        self.flush_task: asyncio.Task | None = None

    async def _apply_rename(self, emoji: str) -> None:
        """Actually rename the channel. Updates last_rename_at on success."""
        channel_id = self.get_channel_id()
        if not channel_id:
            return
        new_name = f"{emoji}{self.base_name}" if emoji else self.base_name
        try:
            await self.discord_request(
                "PATCH",
                f"/channels/{channel_id}",
                json={"name": new_name},
            )
            self.last_rename_at = time.monotonic()
        except Exception:
            pass  # Best-effort

    async def _flush_pending(self) -> None:
        """Wait for cooldown to expire, then apply the most recent pending emoji."""
        elapsed = time.monotonic() - self.last_rename_at
        wait = RENAME_COOLDOWN_SECONDS - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        emoji = self.pending_emoji
        self.pending_emoji = None
        self.flush_task = None
        if emoji is not None:
            await self._apply_rename(emoji)

    async def set_status(self, emoji: str) -> tuple[str, bool]:
        """Set user to-do type emoji with cooldown and clobber queue.

        Returns (message, is_error).
        """
        now = time.monotonic()
        if not self.last_rename_at or (now - self.last_rename_at) >= RENAME_COOLDOWN_SECONDS:
            await self._apply_rename(emoji)
            if emoji:
                return f"User to-do type set to {emoji}", False
            return "User to-do type cleared.", False

        # Cooldown active — queue (clobbers any previous pending)
        self.pending_emoji = emoji
        if self.flush_task is None or self.flush_task.done():
            self.flush_task = asyncio.create_task(self._flush_pending())
        remaining = int(RENAME_COOLDOWN_SECONDS - (now - self.last_rename_at))
        if emoji:
            return f"User to-do type {emoji} queued, will apply in ~{remaining}s.", False
        return f"User to-do type clear queued, will apply in ~{remaining}s.", False


# ---------------------------------------------------------------------------
# Public API for bot.py (auto-hourglass, etc.)
# ---------------------------------------------------------------------------


async def set_agent_status(agent_name: str, emoji: str) -> None:
    """Set user to-do type for an agent from outside the MCP tool.

    Uses the same cooldown/clobber queue as the MCP tool. No-op if the
    agent has no registered status state (e.g. hasn't been wired up yet).
    """
    state = _status_states.get(agent_name)
    if state:
        await state.set_status(emoji)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_status_mcp_server(
    agent_name: str,
    get_channel_id: Callable[[], int | None],
    discord_request: Callable[..., Awaitable[Any]],
):
    """Create a per-agent MCP server with the user to-do type tool.

    Also registers the agent's status state in the module-level registry
    so bot.py can call set_agent_status() for auto-hourglass.

    Parameters
    ----------
    agent_name:
        The agent's name (captured in closure).
    get_channel_id:
        Callable returning the agent's Discord channel ID, or None.
    discord_request:
        ``async (method, path, **kwargs) -> httpx.Response`` for Discord REST.
    """

    base_name = _normalize_channel_name(agent_name)
    state = ChannelStatusState(base_name, get_channel_id, discord_request)
    _status_states[agent_name] = state

    async def handle_set_status(args: dict) -> dict[str, Any]:
        emoji = args.get("emoji", "").strip()

        # Empty string = clear status
        if emoji:
            if not _is_single_emoji(emoji):
                return _error(
                    f"Invalid emoji: {emoji!r}. Provide a single emoji character."
                )

        channel_id = get_channel_id()
        if not channel_id:
            return _error("No Discord channel found for this agent.")

        msg, is_err = await state.set_status(emoji)
        if is_err:
            return _error(msg)
        return _text(msg)

    # -- Build tool -----------------------------------------------------------

    set_status_tool = SdkMcpTool(
        name="set_channel_status",
        description=(
            "Set the user's to-do type emoji on your Discord channel name. "
            "The emoji represents what type of action the user needs to take next. "
            "Pass an empty string to clear."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "emoji": {
                    "type": "string",
                    "description": (
                        "A single emoji representing the user's to-do type. "
                        "Examples: ❓ (awaiting direction), "
                        "💬 (user should respond), 📚 (user should read), "
                        "🔬 (user should test). Never use ✅ (checkmark). "
                        "Pass empty string to clear."
                    ),
                },
            },
            "required": ["emoji"],
        },
        handler=handle_set_status,
    )

    return create_sdk_mcp_server(
        name="status",
        version="1.0.0",
        tools=[set_status_tool],
    )
