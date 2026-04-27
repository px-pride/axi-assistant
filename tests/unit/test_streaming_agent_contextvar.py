"""Unit test for the streaming-agent ContextVar used by SDK MCP tools.

Verifies that two concurrent ``stream_response_to_channel``-shaped tasks see
their own agent name via ``get_streaming_agent`` — not whatever the other
task happens to have set.  This is the property the buggy
``channel_to_agent.items()`` + ``query_lock.locked()`` heuristic was
violating before the fix in card ``mohejqitrl4m51r2xa9``.
"""

from __future__ import annotations

import asyncio

import pytest

from axi.discord_stream import _streaming_agent, get_streaming_agent


@pytest.mark.asyncio
async def test_concurrent_streams_see_own_agent_name() -> None:
    """Two concurrent tasks each set the ContextVar to a different value.

    Each task must observe its OWN value when it reads back, never the
    other task's value, even when the reads are interleaved with awaits.
    """
    barrier = asyncio.Event()
    observed: dict[str, list[str | None]] = {"a": [], "b": []}

    async def streamer(name: str, key: str) -> None:
        token = _streaming_agent.set(name)
        try:
            # Read once before yielding — must see our own value.
            observed[key].append(get_streaming_agent())
            # Wait until both tasks have set their values, then read again.
            barrier.set()
            await asyncio.sleep(0)
            # Yield to the other coroutine a few times to ensure interleaving.
            for _ in range(5):
                await asyncio.sleep(0)
                observed[key].append(get_streaming_agent())
        finally:
            _streaming_agent.reset(token)

    # Run both streamers concurrently.
    await asyncio.gather(
        streamer("agent-alpha", "a"),
        streamer("agent-beta", "b"),
    )

    # Each task must only ever have observed its own name.
    assert all(v == "agent-alpha" for v in observed["a"]), observed
    assert all(v == "agent-beta" for v in observed["b"]), observed


@pytest.mark.asyncio
async def test_streaming_agent_default_is_none() -> None:
    """Outside of any stream, ``get_streaming_agent()`` returns None."""
    assert get_streaming_agent() is None


@pytest.mark.asyncio
async def test_set_resets_via_token() -> None:
    """After resetting via the token, the outer scope sees the prior value."""
    assert get_streaming_agent() is None
    outer_token = _streaming_agent.set("outer-agent")
    try:
        assert get_streaming_agent() == "outer-agent"
        inner_token = _streaming_agent.set("inner-agent")
        try:
            assert get_streaming_agent() == "inner-agent"
        finally:
            _streaming_agent.reset(inner_token)
        assert get_streaming_agent() == "outer-agent"
    finally:
        _streaming_agent.reset(outer_token)
    assert get_streaming_agent() is None


@pytest.mark.asyncio
async def test_child_task_inherits_streaming_agent() -> None:
    """A task spawned via ``asyncio.create_task`` inherits the current value."""
    token = _streaming_agent.set("parent-agent")
    try:
        observed: list[str | None] = []

        async def child() -> None:
            observed.append(get_streaming_agent())

        task = asyncio.create_task(child())
        await task
        assert observed == ["parent-agent"]
    finally:
        _streaming_agent.reset(token)


@pytest.mark.asyncio
async def test_grandchild_task_inherits_streaming_agent() -> None:
    """Tasks spawned by spawned tasks still see the original value.

    Mirrors the SDK pattern: ``query.start()`` runs ``_tg.start_soon
    (_read_messages)``; ``_read_messages`` later runs ``_tg.start_soon
    (_handle_control_request)``.  The tool dispatch (grandchild) must see
    the value set before ``query.start()`` ran (parent).
    """
    observed: list[str | None] = []

    async def tool_dispatch() -> None:
        observed.append(get_streaming_agent())

    async def read_messages_loop() -> None:
        # The SDK's _read_messages spawns _handle_control_request.
        task = asyncio.create_task(tool_dispatch())
        await task

    token = _streaming_agent.set("agent-x")
    try:
        # Simulates query.start() spawning _read_messages.
        loop_task = asyncio.create_task(read_messages_loop())
    finally:
        # Reset BEFORE awaiting — the calling task's context goes back, but
        # the spawned task's snapshot already has "agent-x".
        _streaming_agent.reset(token)

    await loop_task
    assert observed == ["agent-x"], observed


@pytest.mark.asyncio
async def test_two_clients_with_different_agents() -> None:
    """Two concurrent ``client.__aenter__()``-shaped scopes capture the right name.

    Set agent A, spawn its read-loop, reset.  Set agent B, spawn its
    read-loop, reset.  Each loop's tool-dispatch task observes its OWN
    agent name — proving the per-client snapshot pattern works.
    """
    observed: dict[str, list[str | None]] = {"a": [], "b": []}

    async def tool_dispatch(key: str) -> None:
        observed[key].append(get_streaming_agent())

    async def read_messages_loop(key: str) -> None:
        task = asyncio.create_task(tool_dispatch(key))
        await task

    # Simulates _create_client for agent A.
    token_a = _streaming_agent.set("agent-A")
    try:
        loop_a = asyncio.create_task(read_messages_loop("a"))
    finally:
        _streaming_agent.reset(token_a)

    # Simulates _create_client for agent B (after A's snapshot was taken).
    token_b = _streaming_agent.set("agent-B")
    try:
        loop_b = asyncio.create_task(read_messages_loop("b"))
    finally:
        _streaming_agent.reset(token_b)

    await asyncio.gather(loop_a, loop_b)

    assert observed == {"a": ["agent-A"], "b": ["agent-B"]}, observed
