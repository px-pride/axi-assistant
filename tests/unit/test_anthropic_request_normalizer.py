"""Tests for the ChatGPT/Codex Anthropic request normalizer script."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def load_normalizer() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "anthropic-codex-proxy" / "anthropic-request-normalizer"
    loader = SourceFileLoader("anthropic_request_normalizer", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_tool_result_content_blocks_are_flattened() -> None:
    normalizer = load_normalizer()
    body = {
        "messages": [
            {"role": "user", "content": "use tool"},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": [{"type": "text", "text": "tool output"}],
                    }
                ],
            },
        ]
    }

    normalized = normalizer.normalize_anthropic_request(body)

    assert normalized["messages"][1]["content"][0]["content"] == "tool output"


def test_unknown_blocks_are_converted_to_text_blocks() -> None:
    normalizer = load_normalizer()
    body = {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "document", "title": "Spec"}],
            }
        ]
    }

    normalized = normalizer.normalize_anthropic_request(body)

    assert normalized["messages"][0]["content"][0]["type"] == "text"
    assert '"document"' in normalized["messages"][0]["content"][0]["text"]
