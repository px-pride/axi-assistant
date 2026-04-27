# ChatGPT/Codex Anthropic Proxy

This setup lets Axi and Claude Code talk to ChatGPT/Codex models through an
Anthropic-compatible local endpoint. It is useful when you want Axi's existing
Claude Code integration to run against a ChatGPT model such as `gpt-5.4`.

## Security

The proxy listens on `127.0.0.1` and is gated by a per-install bearer token,
auto-generated on first start at `~/.config/axi/proxy-token` (mode `600`). Every
request to the normalizer (port 3000) and the OpenAI shim (port 4057) must
present the token via `x-api-key` or `Authorization: Bearer`. Requests with a
non-localhost `Host:` header are rejected with `403`, and `OPTIONS` preflights
are refused so cross-origin browser fetches cannot bypass the auth check.

- **Token rotation:** delete `~/.config/axi/proxy-token` and restart the proxy.
  Restart Axi too so it re-reads the new token.
- **Override the path** (e.g. for tests): set `AXI_PROXY_TOKEN_FILE` to an
  alternate file before starting both the proxy and Axi. The launcher creates
  the file if it does not exist.
- **Permission check:** if the token file exists with mode wider than `600`,
  the proxy refuses to start. Fix with `chmod 600 ~/.config/axi/proxy-token`.

The runtime path is:

```text
Axi / Claude Code
  -> http://127.0.0.1:3000       anthropic-request-normalizer
  -> http://127.0.0.1:3001       anthropic-proxy-rs
  -> http://127.0.0.1:4057/v1    codex-chatgpt-openai-shim
  -> ChatGPT Codex backend       using ~/.codex/auth.json
```

## What Is In This Repo

The helper scripts live in `scripts/anthropic-codex-proxy/`:

| File | Purpose |
|---|---|
| `install.sh` | Installs the helper scripts and optionally installs `anthropic-proxy-rs` |
| `codex-chatgpt-openai-shim` | Presents an OpenAI chat-completions endpoint backed by Codex CLI ChatGPT auth |
| `anthropic-request-normalizer` | Normalizes Claude Code's Anthropic request shapes before `anthropic-proxy-rs` parses them |
| `anthropic-proxy-codex` | Starts the shim, inner proxy, and normalizer together |
| `anthropic-proxy-codex-service` | Portable `start` / `stop` / `status` wrapper |
| `claude-gpt54` | Convenience wrapper for running `claude` through the proxy |

The Rust proxy is not vendored. The installer pins `anthropic-proxy-rs` to the
revision that this setup was tested with:

```text
bc6cbdf2f7bf1ab00c9894969b47c9344c30d3b0
```

## Prerequisites

- Python 3.12+.
- `curl`.
- Rust/Cargo if `anthropic-proxy` is not already installed.
- Codex CLI logged in with ChatGPT auth, producing `~/.codex/auth.json`.

If `~/.codex/auth.json` contains `OPENAI_API_KEY`, the launcher uses the OpenAI
API directly. Otherwise it starts the local ChatGPT OAuth shim and refreshes the
Codex CLI token as needed.

## Install

From the repo root:

```bash
uv sync
scripts/anthropic-codex-proxy/install.sh
```

This installs the wrapper scripts to `~/.local/bin` and installs
`anthropic-proxy` with Cargo if it is missing.

To skip the Rust install, for example when `anthropic-proxy` is already on
`PATH`:

```bash
scripts/anthropic-codex-proxy/install.sh --skip-rust-proxy
```

To reinstall the pinned Rust proxy revision:

```bash
scripts/anthropic-codex-proxy/install.sh --force-rust-proxy
```

To install and start a user systemd service:

```bash
scripts/anthropic-codex-proxy/install.sh --systemd --start
```

Without systemd, use the portable wrapper:

```bash
anthropic-proxy-codex-service start
anthropic-proxy-codex-service status
```

Logs go to `/tmp/anthropic-proxy-codex.log` by default.

## Configure Axi

Set this value in `.env`:

```env
AXI_HARNESS=claude_code
AXI_MODEL=gpt-5.4
```

Axi sets the required `ANTHROPIC_*` variables internally when `AXI_MODEL` starts
with `gpt-`, routing Claude Code through the local proxy and setting the proxy
model to the value of `AXI_MODEL`.

The OpenAI-compatible shim also normalizes effort for the ChatGPT/Codex backend:
Claude Code `max` becomes Codex `xhigh`, while `low`, `medium`, and `high` pass
through. The shim defaults to `xhigh`; override with `CODEX_REASONING_EFFORT`
if needed.

See [axi-runtime-configuration.md](axi-runtime-configuration.md) for the
general `AXI_HARNESS` and `AXI_MODEL` rules.

Restart Axi after editing `.env`.

## Smoke Tests

The proxy requires the bearer token on every request. The examples below load
it from the default token file; override `AXI_PROXY_TOKEN_FILE` if you keep
the token somewhere else.

Liveness probe (no auth required):

```bash
curl -sS http://127.0.0.1:3000/health
```

List models:

```bash
curl -sS http://127.0.0.1:3000/v1/models \
  -H "x-api-key: $(cat ~/.config/axi/proxy-token)"
```

Send a basic Anthropic Messages request:

```bash
curl -sS http://127.0.0.1:3000/v1/messages \
  -H 'content-type: application/json' \
  -H "x-api-key: $(cat ~/.config/axi/proxy-token)" \
  -H 'anthropic-version: 2023-06-01' \
  --data '{"model":"claude-opus-4-1-20250805","max_tokens":32,"messages":[{"role":"user","content":"Reply with pong."}]}'
```

Test the request shape that Claude Code sends for tool results:

```bash
curl -sS 'http://127.0.0.1:3000/v1/messages?beta=true' \
  -H 'content-type: application/json' \
  -H "x-api-key: $(cat ~/.config/axi/proxy-token)" \
  -H 'anthropic-version: 2023-06-01' \
  --data '{"model":"claude-opus-4-1-20250805","max_tokens":64,"messages":[{"role":"user","content":"use tool"},{"role":"assistant","content":[{"type":"tool_use","id":"toolu_1","name":"foo","input":{}}]},{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_1","content":[{"type":"text","text":"tool output"}]}]}],"tools":[{"name":"foo","input_schema":{"type":"object","properties":{}}}]}'
```

A successful response means the normalizer is handling Claude Code's richer
Anthropic request blocks before they reach `anthropic-proxy-rs`.

## Operations

Portable wrapper:

```bash
anthropic-proxy-codex-service start
anthropic-proxy-codex-service stop
anthropic-proxy-codex-service status
```

Systemd service:

```bash
systemctl --user status anthropic-proxy-codex.service
journalctl --user -u anthropic-proxy-codex.service -f
```

Useful environment overrides:

| Variable | Default | Purpose |
|---|---|---|
| `CODEX_AUTH_JSON` | `~/.codex/auth.json` | Codex CLI auth file |
| `CODEX_CHATGPT_SHIM_PORT` | `4057` | OpenAI-compatible ChatGPT shim port |
| `ANTHROPIC_PROXY_INTERNAL_PORT` | public port + 1 | Internal `anthropic-proxy-rs` port |
| `PORT` | `3000` | Public Anthropic-compatible port for the wrapper service |
| `COMPLETION_MODEL` | `gpt-5.4` | Model override for non-thinking requests |
| `REASONING_MODEL` | `gpt-5.4` | Model override for thinking requests |
| `ANTHROPIC_PROXY_CODEX_LOG` | `/tmp/anthropic-proxy-codex.log` | Portable wrapper log file |

## Limitations

This is a compatibility bridge, not a full Anthropic API implementation. The
normalizer preserves the request shapes Axi and Claude Code currently use, and
the shim maps chat-completions-style requests onto the Codex Responses endpoint.
If Claude Code adds new Anthropic block types, extend
`anthropic-request-normalizer` before routing those requests to
`anthropic-proxy-rs`.
