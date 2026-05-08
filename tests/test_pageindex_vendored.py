"""Smoke tests for the vendored upstream PageIndex.

Verifies that:
- The vendored module imports cleanly with our patches in place
- count_tokens uses our char/4 heuristic
- llm_completion and llm_acompletion route through ai_buffett_zo.llm.ZoClient
  (we mock ZoClient.ask to assert the call shape)
- ConfigLoader reads our overridden config.yaml with Zo-style model strings

This is the contract tests that hold the upstream-vendor boundary stable.
"""

from __future__ import annotations

import asyncio

import pytest

from ai_buffett_zo.llm import AskResult


def test_pageindex_module_imports() -> None:
    """The patched module loads without litellm / PyPDF2 / pymupdf / dotenv installed."""
    from ai_buffett_zo.secrag import pageindex

    assert hasattr(pageindex, "count_tokens")
    assert hasattr(pageindex, "llm_completion")
    assert hasattr(pageindex, "llm_acompletion")
    assert hasattr(pageindex, "md_to_tree")
    assert hasattr(pageindex, "ConfigLoader")


def test_count_tokens_uses_char4_heuristic() -> None:
    from ai_buffett_zo.secrag.pageindex import count_tokens

    assert count_tokens("") == 0
    assert count_tokens("abcd") == 1
    assert count_tokens("a" * 4000) == 1000
    # model arg ignored (compat)
    assert count_tokens("hello world", model="zo:openai/gpt-5.4-mini") == 2


def test_llm_completion_routes_through_zo_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """When llm_completion is called, it should construct a ZoClient and call .ask."""
    from ai_buffett_zo.secrag.pageindex import utils as pi_utils

    captured: dict = {}

    class FakeClient:
        def __init__(self, default_model=None) -> None:
            captured["init_model"] = default_model

        def ask(self, input: str, model: str | None = None) -> AskResult:
            captured["ask_input"] = input
            captured["ask_model"] = model
            return AskResult(ok=True, data="summary text", raw="summary text", elapsed_s=0.01, model=model or "")

    # llm_completion does a local import; patch the module the import resolves to.
    monkeypatch.setattr("ai_buffett_zo.llm.ZoClient", FakeClient)

    out = pi_utils.llm_completion("zo:openai/gpt-5.4-mini", "describe this section")
    assert out == "summary text"
    assert captured["ask_input"] == "describe this section"
    assert captured["ask_model"] == "zo:openai/gpt-5.4-mini"


def test_llm_completion_strips_litellm_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backward compat: model strings like `litellm/...` get the prefix stripped."""
    from ai_buffett_zo.secrag.pageindex import utils as pi_utils

    captured: dict = {}

    class FakeClient:
        def __init__(self, default_model=None) -> None:
            pass

        def ask(self, input: str, model: str | None = None) -> AskResult:
            captured["model"] = model
            return AskResult(ok=True, data="x", raw="x", elapsed_s=0.0, model=model or "")

    monkeypatch.setattr("ai_buffett_zo.llm.ZoClient", FakeClient)
    pi_utils.llm_completion("litellm/zo:openai/gpt-5.4-mini", "prompt")
    assert captured["model"] == "zo:openai/gpt-5.4-mini"


def test_llm_completion_flattens_chat_history(monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_buffett_zo.secrag.pageindex import utils as pi_utils

    captured: dict = {}

    class FakeClient:
        def __init__(self, default_model=None) -> None:
            pass

        def ask(self, input: str, model: str | None = None) -> AskResult:
            captured["input"] = input
            return AskResult(ok=True, data="ok", raw="ok", elapsed_s=0.0, model="")

    monkeypatch.setattr("ai_buffett_zo.llm.ZoClient", FakeClient)
    pi_utils.llm_completion(
        "zo:openai/gpt-5.4-mini",
        "follow-up",
        chat_history=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "first reply"},
        ],
    )
    assert "first" in captured["input"]
    assert "first reply" in captured["input"]
    assert "follow-up" in captured["input"]
    assert captured["input"].endswith("[user]: follow-up")


def test_llm_completion_returns_finish_reason_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_buffett_zo.secrag.pageindex import utils as pi_utils

    class FakeClient:
        def __init__(self, default_model=None) -> None:
            pass

        def ask(self, input: str, model: str | None = None) -> AskResult:
            return AskResult(ok=True, data="x", raw="x", elapsed_s=0.0, model="")

    monkeypatch.setattr("ai_buffett_zo.llm.ZoClient", FakeClient)
    out, finish = pi_utils.llm_completion(
        "zo:openai/gpt-5.4-mini", "p", return_finish_reason=True
    )
    assert out == "x"
    assert finish == "finished"


def test_llm_completion_returns_empty_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_buffett_zo.secrag.pageindex import utils as pi_utils

    class FakeClient:
        def __init__(self, default_model=None) -> None:
            pass

        def ask(self, input: str, model: str | None = None) -> AskResult:
            return AskResult(ok=False, data=None, raw=None, elapsed_s=0.0, model="", error="boom")

    monkeypatch.setattr("ai_buffett_zo.llm.ZoClient", FakeClient)
    assert pi_utils.llm_completion("m", "p") == ""
    out, finish = pi_utils.llm_completion("m", "p", return_finish_reason=True)
    assert out == ""
    assert finish == "error"


def test_llm_acompletion_runs_in_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Async wrapper schedules the sync ZoClient via asyncio.to_thread."""
    from ai_buffett_zo.secrag.pageindex import utils as pi_utils

    class FakeClient:
        def __init__(self, default_model=None) -> None:
            pass

        def ask(self, input: str, model: str | None = None) -> AskResult:
            return AskResult(ok=True, data="async-result", raw="async-result", elapsed_s=0.01, model="")

    monkeypatch.setattr("ai_buffett_zo.llm.ZoClient", FakeClient)
    out = asyncio.run(pi_utils.llm_acompletion("zo:openai/gpt-5.4-mini", "prompt"))
    assert out == "async-result"


def test_config_loader_reads_zo_model_defaults() -> None:
    """The vendored config.yaml should expose Zo-style model strings as defaults."""
    from ai_buffett_zo.secrag.pageindex import ConfigLoader

    cfg = ConfigLoader().load()
    assert cfg.model.startswith("zo:")
    assert cfg.retrieve_model.startswith("zo:")
    # Sanity on other tunables that should still be present
    assert cfg.toc_check_page_num == 20
    assert cfg.max_token_num_each_node == 20000


def test_md_to_tree_callable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """md_to_tree takes a file path. We write a small markdown file and confirm
    the function returns a tree. Mock LLM since summarization is conditional
    but the if_add_node_summary='no' default avoids it anyway."""
    from ai_buffett_zo.secrag.pageindex import md_to_tree

    class FakeClient:
        def __init__(self, default_model=None) -> None:
            pass

        def ask(self, input: str, model: str | None = None) -> AskResult:
            return AskResult(ok=True, data="summary", raw="summary", elapsed_s=0.0, model=model or "")

    monkeypatch.setattr("ai_buffett_zo.llm.ZoClient", FakeClient)

    md_path = tmp_path / "sample.md"
    md_path.write_text(
        "# Heading One\n\nbody one\n\n## Subheading\n\nbody two\n\n# Heading Two\n\nbody three\n"
    )
    tree = asyncio.run(md_to_tree(str(md_path)))
    assert tree is not None
    assert isinstance(tree, (list, dict))
