"""Regression tests for BUG 2: AssertionError when client is nulled mid-stream.

Before the fix, `_receive_response_safe` asserted `session.client is not None`
and `session.client._query is not None`. If `sleep_agent(force=True)` cleared
the client between the first failed attempt and the retry (e.g. a queued
interrupt arriving during `asyncio.sleep(delay)`), the retry path crashed
with AssertionError instead of bailing cleanly.

Tests:
  * _receive_response_safe returns without yielding when client is None.
  * _receive_response_safe returns without yielding when client._query is None.
  * stream_with_retry bails cleanly (returns False, posts a channel message)
    when the client gets nulled during the retry delay.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_USER_IDS", "1")
os.environ.setdefault("DISCORD_GUILD_ID", "1")

from axi import discord_stream
from axi.axi_types import AgentSession
from axi.discord_stream import _receive_response_safe, stream_with_retry


class FakeChannel:
    def __init__(self) -> None:
        self.id = 12345
        self.send = AsyncMock()


@pytest.mark.asyncio
async def test_receive_response_safe_returns_when_client_none() -> None:
    """Previously: AssertionError. Now: returns without yielding."""
    session = AgentSession(name="test")
    session.client = None

    yielded = [item async for item in _receive_response_safe(session)]

    assert yielded == []


@pytest.mark.asyncio
async def test_receive_response_safe_returns_when_query_none() -> None:
    """Previously: AssertionError on client._query. Now: returns without yielding."""
    session = AgentSession(name="test")
    session.client = SimpleNamespace(_query=None)

    yielded = [item async for item in _receive_response_safe(session)]

    assert yielded == []


@pytest.mark.asyncio
async def test_stream_with_retry_bails_when_client_nulled_during_delay() -> None:
    """Client nulled during retry delay (force-kill race) — must bail, not crash."""
    session = AgentSession(name="test")
    session.client = SimpleNamespace()  # non-None initially
    channel = FakeChannel()

    # First attempt returns an error to trigger the retry loop.
    stream_calls: list[str] = []

    async def fake_stream_response(_session, _channel):
        stream_calls.append("called")
        return "transient_api_error"

    # During the retry delay, simulate force-kill nulling session.client.
    async def fake_sleep(_delay):
        session.client = None

    retry_send = AsyncMock()

    with patch.object(discord_stream, "stream_response_to_channel", fake_stream_response), \
         patch("asyncio.sleep", fake_sleep), \
         patch.object(discord_stream, "_retry_discord_503", retry_send), \
         patch.object(discord_stream, "_tracer") as tracer:
        tracer.start_as_current_span.return_value.__enter__ = lambda self: SimpleNamespace(
            set_attribute=lambda *_a, **_k: None,
            set_status=lambda *_a, **_k: None,
        )
        tracer.start_as_current_span.return_value.__exit__ = lambda self, *_a: None
        result = await stream_with_retry(session, channel)

    # Clean bail-out (not a crash, not True).
    assert result is False

    # Exactly one stream attempt — retry was aborted before calling again.
    assert stream_calls == ["called"]

    # A user-facing kill message was posted.
    sent_messages = [call.args[1] for call in retry_send.call_args_list]
    assert any("killed mid-retry" in m for m in sent_messages), \
        f"Expected kill message in sent_messages={sent_messages}"
