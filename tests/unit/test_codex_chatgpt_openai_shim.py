"""Tests for the ChatGPT OpenAI-compatible shim."""

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType


def load_shim() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "anthropic-codex-proxy" / "codex-chatgpt-openai-shim"
    loader = SourceFileLoader("codex_chatgpt_openai_shim", str(path))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_max_effort_maps_to_codex_xhigh() -> None:
    shim = load_shim()

    payload = shim.chat_to_responses(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hello"}],
            "reasoning_effort": "max",
        }
    )

    assert payload["reasoning"] == {"effort": "xhigh"}


def test_regular_effort_passes_through() -> None:
    shim = load_shim()

    payload = shim.chat_to_responses(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hello"}],
            "reasoning": {"effort": "high"},
        }
    )

    assert payload["reasoning"] == {"effort": "high"}


def test_default_effort_is_xhigh() -> None:
    shim = load_shim()

    payload = shim.chat_to_responses(
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hello"}],
        }
    )

    assert payload["reasoning"] == {"effort": "xhigh"}
