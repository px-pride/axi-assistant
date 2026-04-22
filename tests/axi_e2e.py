from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discord_e2e import DiscordChannel, DiscordE2EClient


@dataclass(slots=True)
class AxiDiscordEntrypoints:
    master: DiscordChannel
    discord: DiscordE2EClient | None = None

    def spawn_agent(
        self,
        *,
        name: str,
        cwd: str,
        prompt: str,
        timeout: float = 180.0,
        resume: str | None = None,
        command: str | None = None,
        command_args: str | None = None,
        packs: list[str] | None = None,
    ) -> list[dict]:
        message = f'Spawn an agent named "{name}" with cwd "{cwd}" and prompt "{prompt}"'
        if resume:
            message += f' and resume="{resume}"'
        if command:
            message += f' and command="{command}"'
        if command_args:
            message += f' and command_args="{command_args}"'
        if packs is not None:
            message += f" and packs={packs!r}"
        return self.master.send_and_wait(message, timeout=timeout)

    def kill_agent(self, name: str, *, timeout: float = 60.0) -> list[dict]:
        return self.master.send_and_wait(f'Kill the agent named "{name}"', timeout=timeout)

    def restart_agent(self, name: str, *, timeout: float = 90.0) -> list[dict]:
        return self.master.send_and_wait(f'Restart the agent named "{name}"', timeout=timeout)

    def send_to_agent(self, name: str, message: str, *, timeout: float = 60.0) -> list[dict]:
        content = f'Send a message to the agent "{name}" saying: "{message}"'
        return self.master.send_and_wait(content, timeout=timeout)

    def send_direct_to_agent(
        self,
        name: str,
        message: str,
        *,
        timeout: float = 60.0,
        channel_timeout: float = 60.0,
        poll_interval: float = 2.0,
        sentinel: str | None = "awaiting input",
    ) -> list[dict]:
        if self.discord is None:
            raise AssertionError("Direct agent-channel messaging requires a Discord client")
        agent = self.discord.wait_for_channel(
            name,
            timeout=channel_timeout,
            poll_interval=poll_interval,
        )
        return agent.send_and_wait(message, timeout=timeout, sentinel=sentinel)
