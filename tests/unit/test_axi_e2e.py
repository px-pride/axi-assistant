from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.axi_e2e import AxiDiscordEntrypoints
from tests.helpers import TEST_SENTINEL


@dataclass
class ChannelStub:
    sent: list[tuple[str, float]]

    def send_and_wait(self, content: str, timeout: float = 120.0):
        self.sent.append((content, timeout))
        return type("Result", (), {"messages": [{"content": "ok"}]})()


@dataclass
class AgentChannelStub:
    sent: list[tuple[str, float, str | None]]

    def send_and_wait(
        self,
        content: str,
        *,
        timeout: float = 120.0,
        sentinel: str | None = TEST_SENTINEL,
    ) -> list[dict[str, str]]:
        self.sent.append((content, timeout, sentinel))
        return [{"content": "agent ok"}]


@dataclass
class DiscordStub:
    agent: AgentChannelStub
    wait_calls: list[tuple[str, float, float]]

    def wait_for_channel(
        self,
        prefix: str,
        *,
        timeout: float = 60.0,
        poll_interval: float = 2.0,
    ) -> AgentChannelStub:
        self.wait_calls.append((prefix, timeout, poll_interval))
        return self.agent


def test_axi_entrypoints_format_spawn_kill_and_message() -> None:
    master = ChannelStub(sent=[])
    axi = AxiDiscordEntrypoints(master=master)  # type: ignore[arg-type]

    axi.spawn_agent(
        name="worker",
        cwd="/tmp/worker",
        prompt="Say exactly: READY",
        command="prompt",
        command_args='"prefix text"',
        resume="sid-1",
        packs=["ext-a"],
        timeout=180.0,
    )
    axi.kill_agent("worker", timeout=60.0)
    axi.restart_agent("worker", timeout=90.0)
    axi.send_to_agent("worker", "Say exactly: LATER", timeout=45.0)

    assert master.sent == [
        (
            'Spawn an agent named "worker" with cwd "/tmp/worker" and prompt "Say exactly: READY" and resume="sid-1" and command="prompt" and command_args="\"prefix text\"" and packs=[\'ext-a\']',
            180.0,
        ),
        ('Kill the agent named "worker"', 60.0),
        ('Restart the agent named "worker"', 90.0),
        ('Send a message to the agent "worker" saying: "Say exactly: LATER"', 45.0),
    ]


def test_axi_entrypoints_send_direct_to_agent_uses_agent_channel() -> None:
    master = ChannelStub(sent=[])
    agent = AgentChannelStub(sent=[])
    discord = DiscordStub(agent=agent, wait_calls=[])
    axi = AxiDiscordEntrypoints(master=master, discord=discord)  # type: ignore[arg-type]

    result = axi.send_direct_to_agent(
        "worker",
        "Say exactly: DIRECT_OK",
        timeout=45.0,
        channel_timeout=15.0,
        poll_interval=0.5,
        sentinel=None,
    )

    assert result == [{"content": "agent ok"}]
    assert master.sent == []
    assert discord.wait_calls == [("worker", 15.0, 0.5)]
    assert agent.sent == [("Say exactly: DIRECT_OK", 45.0, None)]


def test_axi_entrypoints_send_direct_to_agent_requires_discord_client() -> None:
    master = ChannelStub(sent=[])
    axi = AxiDiscordEntrypoints(master=master)  # type: ignore[arg-type]

    with pytest.raises(AssertionError, match="Discord client"):
        axi.send_direct_to_agent("worker", "hi")
