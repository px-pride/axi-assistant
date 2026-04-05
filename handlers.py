"""Agent handlers - polymorphic handlers for different agent types.

Each handler manages the lifecycle and message processing for a specific agent type.
State lives in AgentSession; handlers are stateless orchestrators.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from claude_agent_sdk import ClaudeSDKClient

if TYPE_CHECKING:
    from bot import AgentSession

log = logging.getLogger("__main__")  # Use bot.py's logger for consistent log output


class AgentHandler(ABC):
    """Base class for agent type handlers.

    Handlers orchestrate agent operations without owning state.
    All state lives in AgentSession.
    """

    @abstractmethod
    def is_awake(self, session: AgentSession) -> bool:
        """Check if agent is ready to process messages."""
        pass

    @abstractmethod
    def is_processing(self, session: AgentSession) -> bool:
        """Check if agent has active work."""
        pass

    @abstractmethod
    async def wake(self, session: AgentSession) -> None:
        """Activate/initialize the agent. May raise ConcurrencyLimitError or other exceptions."""
        pass

    @abstractmethod
    async def sleep(self, session: AgentSession) -> None:
        """Deactivate/cleanup the agent."""
        pass

    @abstractmethod
    async def process_message(
        self,
        session: AgentSession,
        content: str | list,
        channel: discord.TextChannel,
    ) -> None:
        """Process a user message. Raise RuntimeError if unable."""
        pass


class ClaudeCodeHandler(AgentHandler):
    """Handler for interactive Claude Code agents with wake/sleep lifecycle."""

    def is_awake(self, session: AgentSession) -> bool:
        """Agent is awake if it has a client."""
        return session.client is not None

    def is_processing(self, session: AgentSession) -> bool:
        """Agent is processing if query lock is held."""
        return session.query_lock.locked()

    async def wake(self, session: AgentSession) -> None:
        """Create ClaudeSDKClient and connect to it.

        May raise:
            ConcurrencyLimitError: If all awake slots are in use
            Exception: If client creation/connection fails
        """
        if self.is_awake(session):
            return

        log.debug("Waking Claude Code agent '%s'", session.name)

        # Import here to avoid circular dependency
        from bot import (
            _make_agent_options,
            _get_subprocess_pid,
            _ensure_process_dead,
            _create_transport,
        )

        options = _make_agent_options(session, session.session_id)

        # Create transport (bridge or direct)
        # If session_id is set, we're reconnecting/resuming an existing CLI
        is_reconnecting = session.session_id is not None
        transport = await _create_transport(session, reconnecting=is_reconnecting)

        # Create and connect client
        session.client = ClaudeSDKClient(options=options, transport=transport)
        try:
            await session.client.__aenter__()
        except Exception:
            session.client = None
            raise

        log.info("Claude Code agent '%s' awake", session.name)
        if session._log:
            session._log.info("SESSION_WAKE")

        # Create FlowCoderSession wrapping the SDK client
        from bot import _create_flowcoder_session
        _create_flowcoder_session(session)

    async def sleep(self, session: AgentSession) -> None:
        """Disconnect ClaudeSDKClient via _disconnect_client."""
        if not self.is_awake(session):
            return

        log.debug("Sleeping Claude Code agent '%s'", session.name)

        from bot import _disconnect_client

        await _disconnect_client(session.client, session.name)
        session.client = None
        session._bridge_busy = False

        log.info("Claude Code agent '%s' sleeping", session.name)
        if session._log:
            session._log.info("SESSION_SLEEP")

    async def process_message(
        self,
        session: AgentSession,
        content: str | list,
        channel: discord.TextChannel,
    ) -> None:
        """Run a query through Claude Code.

        Raises:
            RuntimeError: If agent is not awake
        """
        if not self.is_awake(session):
            raise RuntimeError(f"Claude Code agent '{session.name}' not awake")

        # Import here to avoid circular dependency
        from bot import (
            _as_stream,
            drain_stderr,
            drain_sdk_buffer,
            _stream_with_retry,
            _content_summary,
            send_system,
            ActivityState,
        )

        session.last_activity = datetime.now(timezone.utc)
        session.last_idle_notified = None
        session.idle_reminder_count = 0
        session._bridge_busy = False

        drain_stderr(session)
        drained = drain_sdk_buffer(session)

        if session._log:
            session._log.info("USER: %s", _content_summary(content))

        log.info("HANDLER[%s] process_message: drained=%d, calling query+stream", session.name, drained)

        from bot import _is_flowcoder_command, _execute_flowcoder_command, send_long, _strip_ts
        from bot import (
            _resolve_extension_hooks, _resolve_prompt_hooks,
            DEFAULT_EXTENSIONS, _is_axi_dev_cwd,
        )

        raw_text = _strip_ts(content) if isinstance(content, str) else ""

        if isinstance(content, str) and raw_text.startswith("/") and session.flowcoder is None:
            await send_long(channel, "*FlowCoder:* FlowCoderSession not initialized — cannot check slash commands. Falling back to Claude.")
            log.error("FlowCoderSession not initialized for agent '%s'", session.name)

        is_raw = raw_text.startswith("//raw")
        is_fc = _is_flowcoder_command(content, session)
        has_soul = session.flowcoder and session.flowcoder.storage_service.command_exists("soul")
        has_soul_flow = session.flowcoder and session.flowcoder.storage_service.command_exists("soul-flow")

        # Route FlowCoder slash commands:
        # - soul/soul-flow: execute directly (they ARE the wrappers)
        # - other commands: wrap in /soul-flow if available, else execute directly
        if is_fc and not is_raw:
            fc_parts = raw_text[1:].strip().split(None, 1)
            fc_cmd_name = fc_parts[0] if fc_parts else ""
            fc_args = fc_parts[1] if len(fc_parts) > 1 else ""

            if fc_cmd_name in ("soul", "soul-flow") or not has_soul_flow:
                await _execute_flowcoder_command(session, content, channel)
            else:
                audience = "admin" if _is_axi_dev_cwd(session.cwd) else "general"
                hooks = _resolve_extension_hooks(DEFAULT_EXTENSIONS, audience)
                pre_task = hooks.get("pre_task", "")
                post_task = hooks.get("post_task", "")
                prompt_hooks = _resolve_prompt_hooks(DEFAULT_EXTENSIONS, audience)
                report_records_text = prompt_hooks.get("report_records", "")

                # Double-quote: fc_args goes through TWO shlex.split levels
                # (soul-flow parse + wrapped command parse). Parse once here,
                # then re-quote each token so the second split reconstructs
                # the original token list.
                try:
                    tokens = shlex.split(fc_args) if fc_args.strip() else []
                except ValueError:
                    tokens = [fc_args]  # fallback: treat as single token
                inner_quoted = ' '.join(shlex.quote(t) for t in tokens)
                soul_flow_cmd = (
                    f'/soul-flow "{pre_task}" "{post_task}"'
                    f' {shlex.quote(report_records_text)}'
                    f' {shlex.quote(fc_cmd_name)}'
                    f' {shlex.quote(inner_quoted)}'
                )
                log.info("HANDLER[%s] wrapping /%s in /soul-flow (hooks: pre=%s post=%s)",
                         session.name, fc_cmd_name, pre_task, post_task)
                await _execute_flowcoder_command(session, soul_flow_cmd, channel)
            return

        # Route non-flowchart messages through /soul
        if not is_raw and has_soul:
            audience = "admin" if _is_axi_dev_cwd(session.cwd) else "general"
            hooks = _resolve_extension_hooks(DEFAULT_EXTENSIONS, audience)
            pre_task = hooks.get("pre_task", "")
            execute = hooks.get("execute", "")
            post_task = hooks.get("post_task", "")
            post_respond = hooks.get("post_respond", "")

            prompt_hooks = _resolve_prompt_hooks(DEFAULT_EXTENSIONS, audience)
            report_records_text = prompt_hooks.get("report_records", "")

            sanitized = raw_text.replace("\\", "\u2216").replace("'", "\u2019").replace('"', "\u201C")

            soul_cmd = (
                f'/soul "{pre_task}" "{execute}" "{post_task}" "{post_respond}"'
                f' {shlex.quote(sanitized)}'
                f' {shlex.quote(report_records_text)}'
            )
            log.info("HANDLER[%s] routing through /soul (hooks: pre=%s exec=%s post=%s respond=%s)",
                     session.name, pre_task, execute, post_task, post_respond)
            await _execute_flowcoder_command(session, soul_cmd, channel)
            return

        # Direct to Claude (//raw bypass or no /soul command)
        if is_raw:
            # Strip //raw prefix
            content = raw_text[5:].lstrip() if len(raw_text) > 5 else raw_text
            log.info("HANDLER[%s] //raw bypass, sending directly to Claude", session.name)

        try:
            log.info("HANDLER[%s] calling client.query()", session.name)
            await session.client.query(_as_stream(content))
            log.info("HANDLER[%s] query() returned, calling _stream_with_retry()", session.name)
            await _stream_with_retry(session, channel)
        except Exception:
            log.exception("Error querying Claude Code agent '%s'", session.name)
            raise RuntimeError(
                f"Query failed for agent '{session.name}'"
            ) from None


_claude_code_handler = ClaudeCodeHandler()


def get_handler() -> AgentHandler:
    """Get the agent handler."""
    return _claude_code_handler
