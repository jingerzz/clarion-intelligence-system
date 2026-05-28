"""Tests for ai_buffett_zo.secrag.tree.

ZoClient is mocked — we control every "LLM" response and verify the tree
shape, prompt content, and chunking decisions.
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Any


from ai_buffett_zo.llm import AskResult, ZoClient
from ai_buffett_zo.secrag import (
    FilingMetadata,
    FilingTree,
    Section,
    TreeBuilder,
)
from ai_buffett_zo.secrag import tree as tree_mod


def _meta() -> FilingMetadata:
    return FilingMetadata(
        cik="0001045810",
        ticker="NVDA",
        company="NVIDIA Corp",
        form="10-K",
        filed=date(2026, 2, 21),
        period=date(2026, 1, 26),
        accession="0001045810-26-000010",
        primary_doc="nvda-20260126.htm",
        primary_doc_url="https://example/nvda-20260126.htm",
    )


def _summary(name: str, severity: int = 2) -> dict[str, Any]:
    return {
        "one_sentence_summary": f"summary of {name}",
        "key_points": [f"{name} point 1", f"{name} point 2"],
        "themes": [f"{name}-theme"],
        "severity": severity,
        "tickers_or_entities": ["NVDA"],
    }


class _MockClient:
    """Stand-in ZoClient that returns scripted responses keyed by prompt fragments."""

    def __init__(self, response_for: dict[str, dict[str, Any]]) -> None:
        self.response_for = response_for
        self.calls: list[str] = []

    def ask(self, input: str, **kwargs: Any) -> AskResult:
        self.calls.append(input)
        for key, payload in self.response_for.items():
            if key in input:
                return AskResult(
                    ok=True, data=payload, raw=payload,
                    elapsed_s=0.01, model=kwargs.get("model", "test"),
                )
        # default empty
        return AskResult(
            ok=True, data=_summary("default"), raw={}, elapsed_s=0.01,
            model=kwargs.get("model", "test"),
        )


def test_build_short_section_no_chunks() -> None:
    section = Section(
        label="risk_factors",
        title="Item 1A. Risk Factors",
        text="Short text about supply chain.",
        char_start=0,
        char_end=29,
    )
    client = _MockClient({"Short text": _summary("risk")})
    builder = TreeBuilder(client)  # type: ignore[arg-type]
    tree = builder.build(_meta(), [section])

    assert isinstance(tree, FilingTree)
    assert len(tree.sections) == 1
    sn = tree.sections[0]
    assert sn.label == "risk_factors"
    assert sn.chunks == []
    assert sn.summary == "summary of risk"
    assert sn.summary_data["severity"] == 2
    # One LLM call for the section
    assert len(client.calls) == 1


def test_build_long_section_chunks_and_synthesizes() -> None:
    # Build text that exceeds the chunk budget. Use 5 paragraphs of 5000 chars each
    # = 25000 chars ≈ 6250 tokens. With max_chunk_tokens=2000, should produce 4-5 chunks.
    para = ("a " * 2500).strip()  # ~5000 chars
    text = "\n\n".join([para] * 5)
    section = Section(
        label="mdna",
        title="Item 7. MD&A",
        text=text,
        char_start=0,
        char_end=len(text),
    )
    client = _MockClient({})
    builder = TreeBuilder(client, max_chunk_tokens=2000)  # type: ignore[arg-type]
    tree = builder.build(_meta(), [section])
    sn = tree.sections[0]
    assert len(sn.chunks) >= 2  # actually chunked
    # One call per chunk + one synthesis call
    assert len(client.calls) == len(sn.chunks) + 1
    assert sn.summary  # synthesis populated something


def test_chunking_groups_paragraphs_under_budget() -> None:
    para = "x " * 100  # ~200 chars ≈ 50 tokens
    text = "\n\n".join([para.strip()] * 20)  # 20 paragraphs
    chunks = tree_mod._chunk_text(text, target_tokens=200)
    # Each chunk should fit ~4 paragraphs (200 tokens / 50 per paragraph)
    assert len(chunks) >= 4
    for c in chunks:
        assert tree_mod._estimate_tokens(c) <= 250  # small slack for fill


def test_chunking_splits_oversized_paragraph_on_sentences() -> None:
    """A single paragraph that exceeds budget should split on sentence boundaries."""
    sentences = [f"Sentence {i} is here. " for i in range(100)]
    big_para = "".join(sentences)
    chunks = tree_mod._chunk_text(big_para, target_tokens=100)
    assert len(chunks) >= 2
    # Each chunk should be roughly bounded
    for c in chunks:
        assert len(c) > 0


def test_estimate_tokens() -> None:
    assert tree_mod._estimate_tokens("") == 0
    assert tree_mod._estimate_tokens("abcd") == 1
    assert tree_mod._estimate_tokens("a" * 4000) == 1000


def test_indexer_model_recorded() -> None:
    section = Section(label="business", title="Item 1", text="brief", char_start=0, char_end=5)
    client = _MockClient({})
    builder = TreeBuilder(client, model="zo:openai/gpt-5.4-mini")  # type: ignore[arg-type]
    tree = builder.build(_meta(), [section])
    assert tree.indexer_model == "zo:openai/gpt-5.4-mini"


def test_real_zo_client_type_compatible() -> None:
    """Sanity: TreeBuilder accepts a real ZoClient by type, even if we never call it."""
    builder = TreeBuilder(ZoClient(token="zo_sk_test"))
    assert builder.client is not None


# ---- bounded parallelism (issue #48) ----------------------------------------


def _sections(n: int) -> list[Section]:
    return [
        Section(label=f"s{i}", title=f"Item {i}", text=f"short text {i}",
                char_start=0, char_end=12)
        for i in range(n)
    ]


def test_max_concurrency_clamped_to_at_least_one() -> None:
    assert TreeBuilder(_MockClient({}), max_concurrency=0).max_concurrency == 1  # type: ignore[arg-type]
    assert TreeBuilder(_MockClient({}), max_concurrency=-5).max_concurrency == 1  # type: ignore[arg-type]


def test_build_runs_leaf_calls_concurrently() -> None:
    """N independent leaf summaries must run in parallel.

    A barrier of size N only releases when N calls are simultaneously in
    flight. Under serial execution the first wait() blocks alone and trips the
    5s timeout (BrokenBarrierError → test failure). Passing proves real
    concurrency, not just correct output.
    """
    n = 4
    barrier = threading.Barrier(n, timeout=5)
    reached = 0
    lock = threading.Lock()

    class _BarrierClient:
        def ask(self, input: str, **kwargs: Any) -> AskResult:
            nonlocal reached
            barrier.wait()
            with lock:
                reached += 1
            return AskResult(ok=True, data=_summary("x"), raw={}, elapsed_s=0.0,
                             model="test")

    builder = TreeBuilder(_BarrierClient(), max_concurrency=n)  # type: ignore[arg-type]
    tree = builder.build(_meta(), _sections(n))

    assert reached == n
    # Order preserved despite concurrent completion.
    assert [s.label for s in tree.sections] == [f"s{i}" for i in range(n)]


def test_parallel_output_identical_to_serial() -> None:
    """max_concurrency=4 must produce the same tree as max_concurrency=1."""
    para = ("a " * 2500).strip()                 # ~5000 chars
    long_text = "\n\n".join([para] * 4)          # forces chunking + synthesis
    sections = [
        Section(label="business", title="Item 1", text="short business",
                char_start=0, char_end=14),
        Section(label="mdna", title="Item 7", text=long_text,
                char_start=0, char_end=len(long_text)),
        Section(label="risk_factors", title="Item 1A", text="short risk",
                char_start=0, char_end=10),
    ]

    def make(concurrency: int) -> FilingTree:
        return TreeBuilder(
            _MockClient({}), max_chunk_tokens=2000, max_concurrency=concurrency,  # type: ignore[arg-type]
        ).build(_meta(), sections)

    serial = make(1)
    parallel = make(4)

    assert [s.label for s in serial.sections] == [s.label for s in parallel.sections]
    for ss, ps in zip(serial.sections, parallel.sections):
        assert ss.summary == ps.summary
        assert [c.chunk_index for c in ps.chunks] == list(range(len(ps.chunks)))
        # Chunk texts assembled in the same order regardless of completion order.
        assert [c.text for c in ss.chunks] == [c.text for c in ps.chunks]
    # The long mdna section actually chunked (otherwise this proves nothing).
    assert len(parallel.sections[1].chunks) >= 2
