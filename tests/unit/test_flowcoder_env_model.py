"""Tests for proxy-driven Claude Code model selection."""

from claude_agent_sdk import ClaudeAgentOptions

from axi.flowcoder import build_engine_cli_args


def test_proxy_model_does_not_emit_model_flag() -> None:
    args = build_engine_cli_args(ClaudeAgentOptions(model=None))

    assert "--model" not in args
