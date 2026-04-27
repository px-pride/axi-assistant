"""Shared auth helpers for the Anthropic-compatible Codex proxy.

The local proxy exposes three TCP listeners on 127.0.0.1 (anthropic-request-
normalizer, anthropic-proxy-rs, codex-chatgpt-openai-shim). Without auth, any
local process can burn the user's ChatGPT quota by talking to them. This module
provides the per-install bearer-token auth + Host-header allowlist that the
normalizer and shim share.

The token is stored in a file (default $HOME/.config/axi/proxy-token, override
via AXI_PROXY_TOKEN_FILE). The launcher generates it on first start with mode
600. Both servers read the file once at startup; rotation requires restart.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler

DEFAULT_TOKEN_PATH = Path.home() / ".config" / "axi" / "proxy-token"
TOKEN_HEX_LEN = 64  # secrets.token_hex(32) -> 64 hex chars


def token_path_from_env() -> Path:
    """Resolve the token file path, honoring AXI_PROXY_TOKEN_FILE."""
    env = os.environ.get("AXI_PROXY_TOKEN_FILE", "").strip()
    if env:
        return Path(env).expanduser()
    return DEFAULT_TOKEN_PATH


def _check_mode(path: Path) -> None:
    """Refuse to use a token file with group/other-readable mode."""
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise SystemExit(
            f"proxy-token file {path} has insecure mode {oct(mode)} "
            f"(expected 600). Fix with: chmod 600 {path}"
        )


def load_or_create_token(path: Path | None = None) -> str:
    """Read the proxy token from *path*, generating it on first call.

    Generated tokens are 32 random bytes hex-encoded (64 chars), written
    atomically with mode 600. Existing files are validated for length and mode.
    """
    if path is None:
        path = token_path_from_env()
    path = Path(path)

    if path.exists():
        _check_mode(path)
        token = path.read_text().strip()
        if len(token) != TOKEN_HEX_LEN or not all(c in "0123456789abcdef" for c in token):
            raise SystemExit(
                f"proxy-token file {path} is malformed "
                f"(expected {TOKEN_HEX_LEN}-char lowercase hex). "
                f"Delete the file and restart the proxy to regenerate."
            )
        return token

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = secrets.token_hex(32)

    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, (token + "\n").encode("ascii"))
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return token


def load_token(path: Path | None = None) -> str:
    """Read an existing token. Raises SystemExit if missing or malformed."""
    if path is None:
        path = token_path_from_env()
    path = Path(path)
    if not path.exists():
        raise SystemExit(
            f"proxy-token file {path} not found. "
            f"Start the proxy via anthropic-proxy-codex to auto-generate it."
        )
    _check_mode(path)
    token = path.read_text().strip()
    if len(token) != TOKEN_HEX_LEN:
        raise SystemExit(
            f"proxy-token file {path} is malformed "
            f"(expected {TOKEN_HEX_LEN}-char lowercase hex)."
        )
    return token


def allowed_host_values(port: int) -> set[str]:
    """Hosts the listener accepts on the given port (exact match, lowercase)."""
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


def _send_json_error(handler: BaseHTTPRequestHandler, status: int, code: str, message: str) -> None:
    payload = json.dumps({"error": {"type": code, "message": message}}, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(payload)))
    handler.send_header("connection", "close")
    handler.end_headers()
    handler.wfile.write(payload)


def check_host_header(handler: BaseHTTPRequestHandler, allowed_hosts: set[str]) -> bool:
    """Return True if the request's Host header is in *allowed_hosts*.

    Sends 403 and returns False otherwise. Done before token check so DNS-
    rebinding probes never get a chance to leak token-comparison timing.
    """
    host = (handler.headers.get("host") or "").strip().lower()
    if host in allowed_hosts:
        return True
    _send_json_error(
        handler,
        403,
        "host_header_rejected",
        "Host header not allowlisted (only 127.0.0.1 and localhost accepted)",
    )
    return False


def check_token(handler: BaseHTTPRequestHandler, expected_token: str) -> bool:
    """Return True if the request carries a valid x-api-key or Bearer token.

    Sends 401 and returns False otherwise. Both header forms are accepted; the
    comparison uses hmac.compare_digest for constant-time semantics.
    """
    expected = expected_token.encode("ascii")

    incoming_x = (handler.headers.get("x-api-key") or "").strip()
    auth_header = (handler.headers.get("authorization") or "").strip()
    incoming_bearer = ""
    if auth_header.lower().startswith("bearer "):
        incoming_bearer = auth_header[7:].strip()

    matched = False
    if incoming_x:
        if hmac.compare_digest(incoming_x.encode("utf-8"), expected):
            matched = True
    if not matched and incoming_bearer:
        if hmac.compare_digest(incoming_bearer.encode("utf-8"), expected):
            matched = True

    if matched:
        return True

    _send_json_error(
        handler,
        401,
        "unauthorized",
        "Missing or invalid proxy auth token (set x-api-key or Authorization: Bearer)",
    )
    return False


def reject_options(handler: BaseHTTPRequestHandler) -> None:
    """Always reject OPTIONS preflights with 403.

    Defaults to 501 in BaseHTTPRequestHandler; explicit 403 with no CORS
    headers communicates the policy clearly to browser callers.
    """
    _send_json_error(
        handler,
        403,
        "options_disabled",
        "OPTIONS preflight is not supported on this proxy",
    )
