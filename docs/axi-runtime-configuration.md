# Axi Runtime Configuration

Axi separates two choices:

- `AXI_HARNESS`: how Axi runs each agent.
- `AXI_MODEL`: which model the harness should use.

This keeps the setup to one operational choice and one model choice. Users
should not need to set Claude Code's low-level `ANTHROPIC_*` variables for the
standard ChatGPT proxy setup.

## Harness

Set `AXI_HARNESS` in `.env`:

```env
AXI_HARNESS=claude_code
```

Supported values:

| Value | Behavior |
|---|---|
| `claude_code` | Run plain Claude Code sessions. Use this for Claude Code pointed at Claude models or the ChatGPT proxy. |
| `flowcoder` | Run agents through the FlowCoder engine and flowchart layer. |

`claude-code` is accepted as an alias for `claude_code`.

The old `FLOWCODER_ENABLED=0/1` flag is still read for backwards compatibility
when `AXI_HARNESS` is not set, but new configs should use `AXI_HARNESS`.

## Model

Set `AXI_MODEL` in `.env`:

```env
AXI_MODEL=gpt-5.4
```

Supported forms:

| Model value | Behavior |
|---|---|
| `opus`, `sonnet`, `haiku` | Passed to Claude Code as the native Claude model selector. |
| `gpt-*` such as `gpt-5.4` | Routed through the local ChatGPT Anthropic proxy. |

The legacy value `codex` is accepted as an alias for `gpt-5.4`, but new configs
should set the actual model name.

## FlowCoder Wrapper

When `AXI_HARNESS=flowcoder`, Axi can automatically route normal messages
through a FlowCoder command before Claude sees them:

```env
AXI_FC_WRAP=soul
```

Supported values:

| Value | Behavior |
|---|---|
| unset | Default legacy behavior: route through `soul`. |
| `prompt` | Use the bundled pass-through wrapper. Normal messages run as the model prompt with no extra lifecycle steps. |
| `off`, `none`, `0`, `false` | Disable automatic wrapping. Messages go directly to the FlowCoder engine/Claude session. |
| `soul` | Use the legacy `/soul` wrapper for normal messages and `/soul-flow` wrapper for other slash commands. |
| any command name | Route normal messages as `/<command-name> <message>`. Explicit slash commands are not wrapped. |

Explicit flowchart commands, such as `/soul` or `/flowchart`, still work when
automatic wrapping is disabled.

## Effort

Axi passes `AXI_EFFORT` to Claude Code. Supported values are:

```env
AXI_EFFORT=max
```

Valid values are `low`, `medium`, `high`, and `max`. For ChatGPT/Codex models,
the proxy shim maps Claude Code's `max` effort to Codex's `xhigh` reasoning
level. The legacy spelling `xhigh` is accepted in `.env` and normalized to
Claude Code's `max`.

## ChatGPT Proxy Defaults

When `AXI_MODEL` starts with `gpt-`, Axi automatically runs Claude Code with:

```env
ANTHROPIC_BASE_URL=http://127.0.0.1:3000
ANTHROPIC_API_KEY=test
ANTHROPIC_MODEL=<AXI_MODEL>
```

These are injected into the Claude Code process. They do not need to be in
`.env` for normal use.

If the proxy is listening somewhere else, set:

```env
AXI_CHATGPT_PROXY_BASE_URL=http://127.0.0.1:3000
AXI_CHATGPT_PROXY_API_KEY=test
```

## Examples

Plain Claude Code on Claude:

```env
AXI_HARNESS=claude_code
AXI_MODEL=opus
```

Claude Code on ChatGPT 5.4 through the proxy:

```env
AXI_HARNESS=claude_code
AXI_MODEL=gpt-5.4
```

FlowCoder on Claude:

```env
AXI_HARNESS=flowcoder
AXI_MODEL=opus
```

FlowCoder on ChatGPT 5.4 through the proxy:

```env
AXI_HARNESS=flowcoder
AXI_MODEL=gpt-5.4
AXI_FC_WRAP=prompt
```

FlowCoder without automatic wrapper flowcharts:

```env
AXI_HARNESS=flowcoder
AXI_FC_WRAP=off
```

Restart Axi after changing these values.
