"""System prompt construction and extension loading for the Axi bot.

Handles layered .md prompt files, extension system, and per-agent prompt assembly.
"""

from __future__ import annotations

__all__ = [
    "MASTER_SYSTEM_PROMPT",
    "compute_prompt_hash",
    "make_spawned_agent_system_prompt",
    "post_system_prompt_to_channel",
]

import hashlib
import io
import logging
import os
import re
from typing import TYPE_CHECKING

import discord
from discord import TextChannel

from axi import config
from axi.extensions import DEFAULT_EXTENSIONS, extension_prompt_text

if TYPE_CHECKING:
    from claude_agent_sdk.types import SystemPromptPreset

log = logging.getLogger("axi")

# ---------------------------------------------------------------------------
# Prompt hashing
# ---------------------------------------------------------------------------


def compute_prompt_hash(system_prompt: SystemPromptPreset | str | None) -> str | None:
    """Compute a short hash of the system prompt text for change detection.

    Extracts the prompt text (from 'append' for dicts, or the string directly),
    returns the first 16 hex chars of its SHA-256 hash.
    """
    if system_prompt is None:
        return None
    if isinstance(system_prompt, dict):
        text = system_prompt.get("append", "")
    else:
        text = system_prompt
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Prompt file loading
# ---------------------------------------------------------------------------


def _load_prompt_file(path: str, variables: dict[str, str] | None = None) -> str:
    """Load a prompt .md file, optionally expanding %(var)s placeholders."""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if variables:
        content = content % variables
    return content


_PROMPT_VARS = {"axi_user_data": config.AXI_USER_DATA, "bot_dir": config.BOT_DIR}

_SOUL = _load_prompt_file(os.path.join(config.BOT_DIR, "SOUL.md"), _PROMPT_VARS)
_DEV_CONTEXT = _load_prompt_file(os.path.join(config.BOT_DIR, "dev_context.md"), _PROMPT_VARS)

# User profile — loaded from repo root (one level above BOT_DIR/axi-py/)
_PROFILE_DIR = os.path.join(os.path.dirname(config.BOT_DIR), "profile")
_USER_PROFILE = ""
_profile_path = os.path.join(_PROFILE_DIR, "USER_PROFILE.md")
if os.path.isfile(_profile_path):
    _USER_PROFILE = _load_prompt_file(_profile_path)
    # Make ref paths absolute so agents spawned outside the repo can resolve them
    _USER_PROFILE = _USER_PROFILE.replace("profile/refs/", os.path.join(_PROFILE_DIR, "refs") + "/")


# ---------------------------------------------------------------------------
# Extension system: modular prompt fragments loaded from extensions/<name>/
# ---------------------------------------------------------------------------
# Extensions replace the old "packs" system. Each extension has prompt.md,
# meta.json (audience, hooks, prompt_hooks), and optional commands/.
# See axi.extensions for loading logic.


# ---------------------------------------------------------------------------
# System prompt templates
# ---------------------------------------------------------------------------

# Mini system prompt for non-admin spawned agents (keeps context small)
_AGENT_CONTEXT_PROMPT = """\
You are an agent session in the Axi system — a personal assistant for a single user. \
You communicate through a dedicated channel. The user reads your messages there. \
Keep responses concise and well-formatted (markdown, code blocks).

Key context:
- You are one of several agent sessions. The master agent (Axi) coordinates via #axi-master.
- Your working directory is set by whoever spawned you. Files you create/edit stay in that directory.
- The user's timezone is US/Pacific.

Sandbox policy:
- You are authorized to use `dangerouslyDisableSandbox: true` for git operations and for curl/HTTP requests to `localhost:9100` (MinFlow task management API).
- Do NOT disable the sandbox for anything else.

Communication rules:
- Never guess or fabricate answers. If you lack context, say so and look it up.
- Do NOT use Skill or EnterWorktree tools — they are not supported.
- AskUserQuestion IS supported — questions will be posted to the channel and the user's reply will be fed back as answers.
- TodoWrite IS supported — use it to track progress on multi-step tasks. The todo list will be displayed automatically. Do NOT repeat or narrate the todo list contents in your text response — the user already sees it.
- EnterPlanMode and ExitPlanMode ARE supported — use plan mode normally for non-trivial implementation tasks. Your plan will be posted for user approval.\
""".format(**_PROMPT_VARS)


def _is_axi_dev_cwd(cwd: str) -> bool:
    """Check if a working directory is within the axi-assistant codebase."""
    return cwd.startswith(config.BOT_DIR) or bool(config.BOT_WORKTREES_DIR and cwd.startswith(config.BOT_WORKTREES_DIR))


# Master agent: soul + dev context + admin extensions
_master_ext_text = extension_prompt_text(DEFAULT_EXTENSIONS, audience="admin")
MASTER_SYSTEM_PROMPT: SystemPromptPreset = {
    "type": "preset",
    "preset": "claude_code",
    "append": _SOUL + "\n\n" + _DEV_CONTEXT + ("\n\n" + _USER_PROFILE if _USER_PROFILE else "") + ("\n\n" + _master_ext_text if _master_ext_text else ""),
}


_CWD_PROMPT_FILENAME = "SYSTEM_PROMPT.md"


_CWD_MODE_RE = re.compile(r"<!--\s*mode:\s*(overwrite|append)\s*-->")


def _load_cwd_prompt(cwd: str) -> tuple[str, str] | None:
    """Load SYSTEM_PROMPT.md from the agent's working directory, if it exists.

    Returns (content, mode) where mode is "append" (default) or "overwrite".
    Mode is detected from an HTML comment directive: ``<!-- mode: overwrite -->``.
    The directive is stripped from the returned content.
    """
    path = os.path.join(cwd, _CWD_PROMPT_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return None
        mode = "append"
        m = _CWD_MODE_RE.search(content)
        if m:
            mode = m.group(1)
            content = (content[: m.start()] + content[m.end() :]).strip()
        log.info("Loaded CWD system prompt from %s (%d chars, mode=%s)", path, len(content), mode)
        return (content, mode)
    except FileNotFoundError:
        return None
    except Exception:
        log.exception("Failed to load CWD system prompt from %s", path)
        return None


def make_spawned_agent_system_prompt(
    cwd: str,
    packs: list[str] | None = None,
    compact_instructions: str | None = None,
) -> SystemPromptPreset:
    """Build system prompt for a spawned agent based on its working directory.

    packs: explicit list of extension names to include, or None for DEFAULT_EXTENSIONS.
           Pass [] to disable extensions entirely. (Parameter named 'packs' for
           backward compatibility with callers in agents.py and tool schemas.)
    compact_instructions: if provided, appended as a compaction guidance section.

    If SYSTEM_PROMPT.md exists in the agent's CWD, its contents are appended
    after the base prompt and extensions (default). If the file contains
    ``<!-- mode: overwrite -->``, it replaces the base prompt entirely
    (compact_instructions are still appended).
    """
    is_admin = _is_axi_dev_cwd(cwd)
    if is_admin:
        # Admin agent — full soul + dev context
        append = _SOUL + "\n\n" + _DEV_CONTEXT + ("\n\n" + _USER_PROFILE if _USER_PROFILE else "")
    else:
        # Non-admin agent — mini context prompt
        append = _AGENT_CONTEXT_PROMPT + ("\n\n" + _USER_PROFILE if _USER_PROFILE else "")
    audience = "admin" if is_admin else "general"
    ext_names = list(packs if packs is not None else DEFAULT_EXTENSIONS)
    ext_text = extension_prompt_text(ext_names, audience)
    if ext_text:
        append += "\n\n" + ext_text

    # Auto-load SYSTEM_PROMPT.md from agent CWD
    cwd_result = _load_cwd_prompt(cwd)
    if cwd_result:
        cwd_prompt, cwd_mode = cwd_result
        if cwd_mode == "overwrite":
            # Overwrite mode: replaces soul/extensions/dev-context entirely
            append = cwd_prompt
        else:
            # Append mode (default): added after base prompt + extensions
            append += "\n\n" + cwd_prompt

    if compact_instructions:
        append += (
            "\n\n# Context Compaction Instructions\n"
            "When summarizing/compacting this conversation, prioritize preserving:\n"
            f"- {compact_instructions}"
        )
    return {
        "type": "preset",
        "preset": "claude_code",
        "append": append,
    }


# ---------------------------------------------------------------------------
# Discord visibility for system prompts
# ---------------------------------------------------------------------------


async def post_system_prompt_to_channel(
    channel: TextChannel,
    system_prompt: SystemPromptPreset | str | None,
    *,
    is_resume: bool = False,
    prompt_changed: bool = False,
    session_id: str | None = None,
) -> None:
    """Post the system prompt as a file attachment to the agent's Discord channel.

    On resume with no prompt change, posts a brief note.
    On resume with prompt change, posts the full updated prompt.
    On new sessions, posts the appended system prompt as an .md file attachment.
    """
    if is_resume and not prompt_changed:
        sid_display = f"`{session_id[:8]}…`" if session_id else "unknown"
        await channel.send(f"*System:* 📋 Resumed session {sid_display}")
        return

    if isinstance(system_prompt, dict):
        prompt_text = system_prompt.get("append", "")
        label = "claude_code preset + appended instructions"
    elif isinstance(system_prompt, str):
        prompt_text = system_prompt
        label = "custom system prompt (full replacement)"
    else:
        return

    line_count = len(prompt_text.splitlines())
    file = discord.File(
        io.BytesIO(prompt_text.encode("utf-8")),
        filename="system-prompt.md",
    )
    sid_suffix = f" — session `{session_id[:8]}…`" if session_id else ""
    if prompt_changed:
        await channel.send(f"*System:* 📋 **System prompt updated** — {label} ({line_count} lines){sid_suffix}", file=file)
    else:
        await channel.send(f"*System:* 📋 {label} ({line_count} lines){sid_suffix}", file=file)
