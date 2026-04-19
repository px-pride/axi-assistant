"""Regression tests for the 2026-04-19 "Query failed" crash.

Before the fix, `_announce_agent_tool_use` and `_upsert_task_status` stored a
single `discord.Message` per tool/task. When the Agent tool's JSON input
streamed past Discord's per-message character limit, the edit path called
`msg.edit(content=...)` without chunking, hit HTTP 400 (error code 50035,
"Invalid Form Body"), and the unhandled HTTPException bubbled all the way up
to `process_message`, aborting the query.

The fix stores a `list[discord.Message]`, chunks on both send and edit via
`split_message`, appends new messages as content grows, blanks trailing
messages (zero-width space) when content shrinks, and swallows Discord
HTTPExceptions so in-band display updates can never kill the query.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_USER_IDS", "1")
os.environ.setdefault("DISCORD_GUILD_ID", "1")

from axi import discord_stream
from axi.discord_stream import (
    _announce_agent_tool_use,
    _StreamCtx,
    _upsert_task_status,
)


class _FakeMessage:
    """Minimal stand-in for discord.Message (supports mutable .content)."""

    _counter = 0

    def __init__(self, content: str) -> None:
        type(self)._counter += 1
        self.id = type(self)._counter
        self.content = content
        self.edit_calls: list[str] = []

    async def edit(self, *, content: str) -> "_FakeMessage":
        self.edit_calls.append(content)
        self.content = content
        return self


class _FakeChannel:
    def __init__(self, *, send_exc: BaseException | None = None) -> None:
        self.id = 12345
        self.name = "test-channel"
        self.sent: list[_FakeMessage] = []
        self._send_exc = send_exc

    async def send(self, content: str) -> _FakeMessage:
        if self._send_exc is not None:
            raise self._send_exc
        msg = _FakeMessage(content)
        self.sent.append(msg)
        return msg


def _http_exc(code: int = 50035, status: int = 400, message: str = "Invalid Form Body") -> discord.HTTPException:
    """Build a discord.HTTPException that looks like a Discord 4xx response."""
    response = SimpleNamespace(status=status, reason=message)
    exc = discord.HTTPException.__new__(discord.HTTPException)
    exc.response = response  # type: ignore[attr-defined]
    exc.status = status  # type: ignore[attr-defined]
    exc.code = code  # type: ignore[attr-defined]
    exc.text = message
    exc.args = (f"{status} {message}",)
    return exc


@pytest.fixture(autouse=True)
def _install_send_long(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a minimal send_long so discord_stream.init() doesn't have to run."""

    async def send_long(channel: _FakeChannel, text: str) -> _FakeMessage | None:  # pragma: no cover
        return await channel.send(text)

    monkeypatch.setattr(discord_stream, "_send_long", send_long)


# ---------------------------------------------------------------------------
# _announce_agent_tool_use
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_announce_agent_tool_use_chunks_on_large_content() -> None:
    """Large tool input must be chunked across multiple messages, not a single edit."""
    ctx = _StreamCtx()
    channel = _FakeChannel()
    huge_prompt = "x" * 3500
    payload = {"description": "d", "subagent_type": "general-purpose", "prompt": huge_prompt}

    await _announce_agent_tool_use(ctx, channel, "tu_1", payload)

    tracked = ctx.agent_announcement_messages["tu_1"]
    assert len(tracked) >= 2, f"Expected multiple chunks, got {len(tracked)}"
    assert all(len(m.content) <= 2000 for m in tracked)
    assert len(channel.sent) == len(tracked)


@pytest.mark.asyncio
async def test_announce_agent_tool_use_appends_message_when_content_grows() -> None:
    """As streaming JSON enriches, we grow the tracked list by appending — not by editing beyond limit."""
    ctx = _StreamCtx()
    channel = _FakeChannel()

    await _announce_agent_tool_use(ctx, channel, "tu_2", {"description": "short"})
    tracked_first = ctx.agent_announcement_messages["tu_2"]
    initial_count = len(tracked_first)

    big = {"description": "short", "prompt": "y" * 3500}
    await _announce_agent_tool_use(ctx, channel, "tu_2", big)

    tracked_second = ctx.agent_announcement_messages["tu_2"]
    assert len(tracked_second) > initial_count, "Expected new message(s) to be appended on growth"
    assert all(len(m.content) <= 2000 for m in tracked_second)


@pytest.mark.asyncio
async def test_announce_agent_tool_use_swallows_400_on_edit() -> None:
    """A Discord 4xx on the edit path must NOT propagate — the query must continue."""
    ctx = _StreamCtx()
    channel = _FakeChannel()

    await _announce_agent_tool_use(ctx, channel, "tu_3", {"description": "initial"})
    tracked = ctx.agent_announcement_messages["tu_3"]
    assert len(tracked) == 1

    tracked[0].edit = AsyncMock(side_effect=_http_exc())

    await _announce_agent_tool_use(
        ctx,
        channel,
        "tu_3",
        {"description": "initial", "prompt": "z" * 3500},
    )


@pytest.mark.asyncio
async def test_announce_agent_tool_use_swallows_400_on_send() -> None:
    """A Discord 4xx on the initial send path must NOT propagate either."""
    ctx = _StreamCtx()
    channel = _FakeChannel(send_exc=_http_exc())

    await _announce_agent_tool_use(ctx, channel, "tu_4", {"description": "x"})

    tracked = ctx.agent_announcement_messages["tu_4"]
    assert tracked == []


@pytest.mark.asyncio
async def test_announce_agent_tool_use_shrink_blanks_trailing() -> None:
    """When content shrinks, trailing messages are blanked, not deleted."""
    ctx = _StreamCtx()
    channel = _FakeChannel()

    big = {"description": "d", "prompt": "q" * 3500}
    await _announce_agent_tool_use(ctx, channel, "tu_5", big)
    tracked_before = list(ctx.agent_announcement_messages["tu_5"])
    assert len(tracked_before) >= 2

    trailing_ids = [m.id for m in tracked_before[1:]]

    ctx.agent_announcement_messages["tu_5"] = tracked_before
    ctx.agent_announcement_messages["tu_5"][0].content = "different label so update fires"

    await _announce_agent_tool_use(ctx, channel, "tu_5", {"description": "d"})

    tracked_after = ctx.agent_announcement_messages["tu_5"]
    assert [m.id for m in tracked_after[1:]] == trailing_ids, "trailing messages must not be replaced"
    for m in tracked_after[1:]:
        assert m.content == "\u200b", f"trailing message should be blanked, got {m.content!r}"


# ---------------------------------------------------------------------------
# _upsert_task_status (mirror tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_task_status_chunks_on_large_content() -> None:
    """Large task status content must be chunked across multiple messages."""
    ctx = _StreamCtx()
    channel = _FakeChannel()
    huge = "a" * 3500

    await _upsert_task_status(ctx, channel, "task_1", huge)

    tracked = ctx.task_status_messages["task_1"]
    assert len(tracked) >= 2
    assert all(len(m.content) <= 2000 for m in tracked)


@pytest.mark.asyncio
async def test_upsert_task_status_appends_message_when_content_grows() -> None:
    """Growing status content must append new messages, not edit beyond limit."""
    ctx = _StreamCtx()
    channel = _FakeChannel()

    await _upsert_task_status(ctx, channel, "task_2", "small")
    initial_count = len(ctx.task_status_messages["task_2"])

    await _upsert_task_status(ctx, channel, "task_2", "b" * 3500)

    tracked = ctx.task_status_messages["task_2"]
    assert len(tracked) > initial_count
    assert all(len(m.content) <= 2000 for m in tracked)


@pytest.mark.asyncio
async def test_upsert_task_status_swallows_400_on_edit() -> None:
    """4xx HTTPException during edit must not abort the caller."""
    ctx = _StreamCtx()
    channel = _FakeChannel()

    await _upsert_task_status(ctx, channel, "task_3", "v1")
    tracked = ctx.task_status_messages["task_3"]
    tracked[0].edit = AsyncMock(side_effect=_http_exc())

    await _upsert_task_status(ctx, channel, "task_3", "v2 which is different")


@pytest.mark.asyncio
async def test_upsert_task_status_swallows_400_on_send() -> None:
    """4xx HTTPException during initial send must not abort the caller."""
    ctx = _StreamCtx()
    channel = _FakeChannel(send_exc=_http_exc())

    await _upsert_task_status(ctx, channel, "task_4", "hello")

    assert ctx.task_status_messages["task_4"] == []
