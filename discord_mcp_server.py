"""Standalone Discord MCP server for Claude Code.

Exposes Discord REST API tools (read messages, send messages, list channels, etc.)
over stdio using the MCP protocol. Uses the discordquery package for HTTP calls.

Reads DISCORD_TOKEN from .env in the same directory.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load .env from same directory as this script
load_dotenv(Path(__file__).parent / ".env")

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
if not DISCORD_TOKEN:
    print("DISCORD_TOKEN not set in .env", file=sys.stderr)
    sys.exit(1)

from discordquery import DiscordClient, resolve_snowflake

_client = DiscordClient(DISCORD_TOKEN)

mcp = FastMCP("discord")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DISCORD_EPOCH_MS = 1420070400000


_EMOJI_PREFIX_RE = re.compile(r"^[^a-z0-9_]+")


def _strip_emoji_prefix(name: str) -> str:
    """Strip leading emoji/status characters from a Discord channel name."""
    return _EMOJI_PREFIX_RE.sub("", name)


def _resolve_channel(channel_arg: str) -> str:
    """Resolve channel ID or guild_id:channel_name to a channel ID."""
    if channel_arg.isdigit():
        return channel_arg
    if ":" in channel_arg:
        guild_id_str, channel_name = channel_arg.split(":", 1)
        if guild_id_str.isdigit():
            channels = _client.get(f"/guilds/{guild_id_str}/channels")
            target = channel_name.lower()
            for ch in channels:
                if ch["type"] in (0, 5):
                    ch_name = ch["name"].lower()
                    if ch_name == target or _strip_emoji_prefix(ch_name) == target:
                        return str(ch["id"])
            raise ValueError(f"No text channel named '{channel_name}' in guild {guild_id_str}")
    raise ValueError(f"'{channel_arg}' is not a valid channel ID or guild_id:channel_name pair")


def _format_messages(messages: list[dict[str, Any]]) -> str:
    lines = []
    for msg in messages:
        author = msg.get("author", {}).get("username", "unknown")
        content = msg.get("content", "")
        timestamp = msg.get("timestamp", "")
        lines.append(f"[{timestamp}] {author}: {content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def discord_list_guilds() -> str:
    """List Discord guilds (servers) the bot is a member of. Returns guild id and name."""
    guilds = _client.list_guilds()
    result = [{"id": str(g["id"]), "name": g["name"]} for g in guilds]
    return json.dumps(result, indent=2)


@mcp.tool()
def discord_list_channels(guild_id: str) -> str:
    """List text channels in a Discord guild/server. Returns channel id, name, and category."""
    text_channels = _client.list_channels(guild_id)
    return json.dumps(text_channels, indent=2)


@mcp.tool()
def discord_read_messages(
    channel_id: str,
    limit: int = 20,
    before: str | None = None,
    after: str | None = None,
) -> str:
    """Read recent messages from a Discord channel. Returns formatted message history.

    Args:
        channel_id: Channel ID, or guild_id:channel_name (e.g. '123456789:general')
        limit: Number of messages to fetch (default 20, max 500)
        before: Fetch messages before this point (Discord snowflake ID or ISO datetime)
        after: Fetch messages after this point (Discord snowflake ID or ISO datetime)
    """
    limit = min(limit, 500)
    resolved = _resolve_channel(channel_id)
    params: dict[str, Any] = {}
    if before:
        params["before"] = resolve_snowflake(before)
    if after:
        params["after"] = resolve_snowflake(after)
    use_after = "after" in params

    all_messages: list[dict[str, Any]] = []
    collected = 0
    while collected < limit:
        batch_size = min(100, limit - collected)
        batch = _client.get_messages(resolved, limit=batch_size, **params)
        if not batch:
            break
        all_messages.extend(batch)
        collected += len(batch)
        if len(batch) < batch_size:
            break
        if use_after:
            params["after"] = batch[-1]["id"]
        else:
            params["before"] = batch[-1]["id"]

    if not use_after:
        all_messages.reverse()
    return _format_messages(all_messages)


@mcp.tool()
def discord_send_message(channel_id: str, content: str) -> str:
    """Send a message to a Discord channel.

    Args:
        channel_id: Channel ID, or guild_id:channel_name (e.g. '123456789:general')
        content: The message content to send
    """
    resolved = _resolve_channel(channel_id)
    resp = _client.post(f"/channels/{resolved}/messages", json={"content": content})
    return f"Message sent (id: {resp['id']})"


@mcp.tool()
def discord_search_messages(
    guild_id: str,
    query: str,
    channel_id: str | None = None,
    author_id: str | None = None,
    limit: int = 25,
    sort_by: str = "timestamp",
    sort_order: str = "desc",
) -> str:
    """Search messages across a Discord guild using Discord's native full-text search.
    Searches the entire guild history, not just recent messages.

    Args:
        guild_id: The Discord guild (server) ID to search
        query: Search text (Discord full-text search)
        channel_id: Limit search to this channel (ID or guild_id:channel_name, optional)
        author_id: Filter by author user ID (optional)
        limit: Max results to return (default 25, max 100)
        sort_by: Sort by "timestamp" or "relevance" (default "timestamp")
        sort_order: Sort order "asc" or "desc" (default "desc")
    """
    limit = min(limit, 100)

    params: dict[str, Any] = {"content": query}
    if channel_id:
        params["channel_id"] = _resolve_channel(channel_id)
    if author_id:
        params["author_id"] = author_id
    if sort_by:
        params["sort_by"] = sort_by
    if sort_order:
        params["sort_order"] = sort_order

    results: list[str] = []
    offset = 0

    while len(results) < limit:
        page_size = min(25, limit - len(results))
        params["limit"] = page_size
        params["offset"] = offset

        data = _client.get(f"/guilds/{guild_id}/messages/search", params)

        message_groups = data.get("messages", [])
        if not message_groups:
            break

        for group in message_groups:
            for msg in group:
                if msg.get("hit"):
                    ts = msg.get("timestamp", "")
                    ch_id = msg.get("channel_id", "")
                    author = msg.get("author", {}).get("username", "unknown")
                    content = msg.get("content", "")
                    results.append(f"[{ts}] #{ch_id} {author}: {content}")
                    break

        total = data.get("total_results", 0)
        offset += page_size
        if offset >= total or offset >= 9975:
            break

    if not results:
        return "No messages found."
    return "\n".join(results[:limit])


if __name__ == "__main__":
    mcp.run()
