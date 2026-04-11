"""Egress filter: scrub secrets from text before it reaches Discord.

Targeted at known secret formats to minimize false positives — agent output
frequently contains code blocks, UUIDs, hashes, and base64 content.

Also provides path-based access control for file reads and uploads.
"""

from __future__ import annotations

import fnmatch
import os
import re

# ---------------------------------------------------------------------------
# Secret patterns
# ---------------------------------------------------------------------------

# Discord bot tokens: base64-encoded bot ID.timestamp.HMAC
# Starts with M, N, or O (first char of base64-encoded snowflake IDs)
_DISCORD_TOKEN_RE = re.compile(
    r"[MNO][a-zA-Z\d_-]{23,25}\.[a-zA-Z\d_-]{6}\.[a-zA-Z\d_-]{27,}"
)

# AWS access key IDs (always start with AKIA)
_AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")

# Generic "secret" assignments in config/env style: KEY=<long-high-entropy-value>
# Only matches when preceded by common secret variable name patterns
_ENV_SECRET_RE = re.compile(
    r"(?:DISCORD_TOKEN|SECRET_KEY|API_KEY|API_SECRET|ACCESS_TOKEN|AUTH_TOKEN)"
    r"\s*[=:]\s*\S{20,}",
    re.IGNORECASE,
)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (_DISCORD_TOKEN_RE, "[REDACTED:discord-token]"),
    (_AWS_KEY_RE, "[REDACTED:aws-key]"),
    (_ENV_SECRET_RE, "[REDACTED:secret]"),
]


def scrub_secrets(text: str) -> str:
    """Replace known secret patterns in *text* with redaction markers.

    Designed for low false-positive rate: only matches specific, well-defined
    secret formats. When in doubt, lets content through.
    """
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Path-based access control for sensitive files
# ---------------------------------------------------------------------------

_HOME = os.path.expanduser("~")

# Basename patterns — matched against the final filename component
_BLOCKED_BASENAMES = {".env", "test-config.json"}

# Prefix patterns — resolved path must NOT start with any of these
_BLOCKED_PREFIXES = [
    os.path.join(_HOME, ".ssh") + os.sep,
    os.path.join(_HOME, ".config", "axi") + os.sep,
]

# Glob-style patterns matched against the resolved path
_BLOCKED_GLOBS = [
    "/proc/*/environ",
]

# Exact basename matches for shell history files
_BLOCKED_HISTORY = {".bash_history", ".python_history", ".zsh_history"}


def is_path_blocked(path: str) -> bool:
    """Return True if *path* points to a sensitive file that should not be read or uploaded."""
    resolved = os.path.realpath(os.path.expanduser(path))
    basename = os.path.basename(resolved)

    if basename in _BLOCKED_BASENAMES:
        return True

    if basename in _BLOCKED_HISTORY:
        return True

    for prefix in _BLOCKED_PREFIXES:
        if resolved.startswith(prefix) or resolved == prefix.rstrip(os.sep):
            return True

    for glob_pat in _BLOCKED_GLOBS:
        if fnmatch.fnmatch(resolved, glob_pat):
            return True

    return False
