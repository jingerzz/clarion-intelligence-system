"""Tests for ai_buffett_zo.secrag.loader.

HTTP is monkeypatched at the module-level seams (`_get_json`, `_get_text`).
"""

from __future__ import annotations

from datetime import date

import pytest

from ai_buffett_zo.secrag import FilingNotFound, fetch_filing
from ai_buffett_zo.secrag import loader


_TICKERS_RESP = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA Corp"},
}

_SUBMISSIONS_RESP = {
    "filings": {
        "recent": {
            "form": ["10-Q", "10-K", "8-K", "10-K", "4", "DEF 14A"],
            "accessionNumber": [
                "0001045810-26-000045",
                "0001045810-26-000010",
                "0001045810-26-000005",
                "0001045810-25-000099",
                "0001045810-26-000099",
                "0001045810-26-000150",
            ],
            "filingDate": [
                "2026-04-30",
                "2026-02-21",
                "2026-02-01",
                "2025-02-22",
                "2026-03-24",
                "2026-04-15",
            ],
            "reportDate": [
                "2026-03-31",
                "2026-01-26",
                "",
                "2025-01-28",
                "2026-03-20",
                "",
            ],
            "primaryDocument": [
                "form10q.htm",
                "nvda-20260126.htm",
                "form8k.htm",
                "nvda-20250128.htm",
                # Form 4: SEC's submissions feed reports an XSLT-rendered path
                "xslF345X06/wk-form4_1774386816.xml",
                "nvda-2026-proxy.htm",
            ],
        }
    }
}


def _patch_http(
    monkeypatch: pytest.MonkeyPatch, *, html: str = "<html>filing body</html>"
) -> dict[str, object]:
    """Install fakes for _get_json + _get_text. Returns a dict capturing call args."""
    captured: dict[str, object] = {"json_urls": [], "text_urls": [], "user_agents": []}

    def fake_get_json(url: str, *, user_agent: str, timeout: int = 30) -> dict:
        captured["json_urls"].append(url)
        captured["user_agents"].append(user_agent)
        if "company_tickers" in url:
            return _TICKERS_RESP
        if "submissions" in url:
            return _SUBMISSIONS_RESP
        raise AssertionError(f"unexpected URL: {url}")

    def fake_get_text(url: str, *, user_agent: str, timeout: int = 60) -> str:
        captured["text_urls"].append(url)
        return html

    monkeypatch.setattr(loader, "_get_json", fake_get_json)
    monkeypatch.setattr(loader, "_get_text", fake_get_text)
    return captured


def test_fetch_latest_10k(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_http(monkeypatch)
    metadata, html = fetch_filing("NVDA", form="10-K")
    assert metadata.ticker == "NVDA"
    assert metadata.cik == "0001045810"
    assert metadata.form == "10-K"
    assert metadata.accession == "0001045810-26-000010"  # the most recent 10-K
    assert metadata.filed == date(2026, 2, 21)
    assert metadata.period == date(2026, 1, 26)
    assert metadata.primary_doc == "nvda-20260126.htm"
    assert metadata.primary_doc_url.endswith("nvda-20260126.htm")
    assert "1045810" in metadata.primary_doc_url
    assert "html" in html or "body" in html
    assert any("submissions" in u for u in captured["json_urls"])  # type: ignore[operator]


def test_fetch_10q(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch)
    metadata, _ = fetch_filing("NVDA", form="10-Q")
    assert metadata.form == "10-Q"
    assert metadata.accession == "0001045810-26-000045"
    assert metadata.filed == date(2026, 4, 30)


def test_fetch_unknown_ticker_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch)
    with pytest.raises(FilingNotFound):
        fetch_filing("FAKEFAKE")


def test_fetch_missing_form_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch)
    with pytest.raises(FilingNotFound):
        fetch_filing("NVDA", form="20-F")


def test_default_user_agent_used(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_http(monkeypatch)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    fetch_filing("NVDA", form="10-K")
    uas: list[str] = captured["user_agents"]  # type: ignore[assignment]
    assert all(loader.DEFAULT_USER_AGENT in ua for ua in uas)


def test_explicit_user_agent_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_http(monkeypatch)
    fetch_filing("NVDA", form="10-K", user_agent="My App (me@example.com)")
    assert all("My App" in ua for ua in captured["user_agents"])  # type: ignore[union-attr]


def test_env_user_agent_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_http(monkeypatch)
    monkeypatch.setenv("SEC_USER_AGENT", "Env UA (env@example.com)")
    fetch_filing("NVDA", form="10-K")
    assert all("Env UA" in ua for ua in captured["user_agents"])  # type: ignore[union-attr]


def test_period_falls_back_to_filed_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 8-K in the fixture has empty reportDate; if requested, period == filed."""
    _patch_http(monkeypatch)
    metadata, _ = fetch_filing("NVDA", form="8-K")
    assert metadata.period == metadata.filed


# ---- XSLT prefix stripping (Form 3/4/5) ----------------------------------


def test_strip_xslt_prefix_removes_xsl_path() -> None:
    """SEC reports primaryDocument as `xslF345X06/wk-form4_xxx.xml` for Forms
    3/4/5. Fetching that URL gets HTML; we want raw XML, which is at the same
    path with the xsl prefix removed."""
    assert (
        loader._strip_xslt_prefix("xslF345X06/wk-form4_1774386816.xml")
        == "wk-form4_1774386816.xml"
    )
    # Other XSLT renderer prefixes (Forms 3, 5 use different ones)
    assert loader._strip_xslt_prefix("xslATS-N_X01/foo.xml") == "foo.xml"
    assert loader._strip_xslt_prefix("xsl1234/bar.xml") == "bar.xml"


def test_strip_xslt_prefix_passthrough_for_normal_paths() -> None:
    """10-K/10-Q primary docs don't have the prefix; leave them alone."""
    assert loader._strip_xslt_prefix("nvda-20260126.htm") == "nvda-20260126.htm"
    assert loader._strip_xslt_prefix("form10q.htm") == "form10q.htm"
    assert loader._strip_xslt_prefix("") == ""


def test_fetch_form_4_uses_raw_xml_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Form 4 metadata + URL should point at the raw XML, not the XSLT
    rendering path. Otherwise the XML parser fails on HTML and the indexer
    silently produces empty sections."""
    captured = _patch_http(monkeypatch)
    metadata, _ = fetch_filing("NVDA", form="4")
    assert metadata.form == "4"
    # primary_doc field is stripped clean
    assert metadata.primary_doc == "wk-form4_1774386816.xml"
    assert "xslF345X06" not in metadata.primary_doc
    # URL points at the raw XML, not the XSLT-rendered HTML
    assert metadata.primary_doc_url.endswith("/wk-form4_1774386816.xml")
    assert "xslF345X06" not in metadata.primary_doc_url
    # And the actual fetch hits the raw XML URL
    text_urls: list[str] = captured["text_urls"]  # type: ignore[assignment]
    assert any(u.endswith("/wk-form4_1774386816.xml") for u in text_urls)
    assert not any("xslF345X06" in u for u in text_urls)


# ---- Form name matching (whitespace + case insensitive) -------------------


def test_fetch_form_with_canonical_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """`DEF 14A` (the canonical EDGAR spelling, with a space) matches."""
    _patch_http(monkeypatch)
    metadata, _ = fetch_filing("NVDA", form="DEF 14A")
    assert metadata.accession == "0001045810-26-000150"


def test_fetch_form_without_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """`DEF14A` (no space) matches the stored `DEF 14A`. This is the bug
    surfaced in the Tier 3 stress test on 2026-05-08: the agent passed
    `DEF14A` and exact-string matching failed, even though EDGAR has the
    filing right there in the submissions feed."""
    _patch_http(monkeypatch)
    metadata, _ = fetch_filing("NVDA", form="DEF14A")
    assert metadata.accession == "0001045810-26-000150"


def test_fetch_form_lowercase_with_space(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lowercase `def 14a` matches — case-insensitive."""
    _patch_http(monkeypatch)
    metadata, _ = fetch_filing("NVDA", form="def 14a")
    assert metadata.accession == "0001045810-26-000150"


def test_fetch_form_lowercase_no_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """`def14a` (no space, all lowercase) matches too."""
    _patch_http(monkeypatch)
    metadata, _ = fetch_filing("NVDA", form="def14a")
    assert metadata.accession == "0001045810-26-000150"


def test_fetch_10k_lowercase(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even 10-K should match its lowercase variant."""
    _patch_http(monkeypatch)
    metadata, _ = fetch_filing("NVDA", form="10-k")
    assert metadata.accession == "0001045810-26-000010"


def test_fetch_form_does_not_match_amendment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Match must NOT strip `/A` — `10-K` and `10-K/A` are genuinely
    different filings (the amendment is filed later with corrections),
    so a request for `10-K` shouldn't silently return the amendment."""
    fixture = {
        "filings": {
            "recent": {
                "form": ["10-K/A", "10-Q"],
                "accessionNumber": ["acc-amend", "acc-10q"],
                "filingDate": ["2026-03-01", "2026-04-30"],
                "reportDate": ["2026-01-26", "2026-03-31"],
                "primaryDocument": ["amend.htm", "form10q.htm"],
            }
        }
    }

    def fake_json(url: str, *, user_agent: str, timeout: int = 30) -> dict:
        if "company_tickers" in url:
            return _TICKERS_RESP
        return fixture

    monkeypatch.setattr(loader, "_get_json", fake_json)
    monkeypatch.setattr(loader, "_get_text", lambda *_a, **_kw: "<html></html>")

    # Asking for 10-K should NOT match 10-K/A.
    with pytest.raises(FilingNotFound):
        fetch_filing("NVDA", form="10-K")

    # But asking for 10-K/A directly should work.
    metadata, _ = fetch_filing("NVDA", form="10-K/A")
    assert metadata.accession == "acc-amend"


def test_normalize_form_match_unit() -> None:
    """Direct unit test of the normalizer."""
    assert loader._normalize_form_match("DEF 14A") == "DEF14A"
    assert loader._normalize_form_match("DEF14A") == "DEF14A"
    assert loader._normalize_form_match("def 14a") == "DEF14A"
    assert loader._normalize_form_match("10-K") == "10-K"
    assert loader._normalize_form_match("10-k") == "10-K"
    # Embedded whitespace stripped from anywhere in the string
    assert loader._normalize_form_match("PRE 14A") == "PRE14A"
    # /A suffix preserved (amendments are different filings)
    assert loader._normalize_form_match("10-K/A") == "10-K/A"


# ---- list_recent_filings -------------------------------------------------


def test_list_recent_filings_no_filter_returns_all_newest_first(monkeypatch):
    _patch_http(monkeypatch)
    filings = loader.list_recent_filings("NVDA")
    # All 6 entries in the fixture come back, newest filed-date first.
    assert [f.form for f in filings] == [
        "10-Q",       # 2026-04-30
        "DEF 14A",    # 2026-04-15
        "4",          # 2026-03-24
        "10-K",       # 2026-02-21
        "8-K",        # 2026-02-01
        "10-K",       # 2025-02-22
    ]


def test_list_recent_filings_form_filter(monkeypatch):
    _patch_http(monkeypatch)
    only_10k = loader.list_recent_filings("NVDA", form="10-K")
    assert [f.accession for f in only_10k] == [
        "0001045810-26-000010",
        "0001045810-25-000099",
    ]


def test_list_recent_filings_since_days_window(monkeypatch):
    """A 60-day window from a fixed asof drops anything older."""
    _patch_http(monkeypatch)
    filings = loader.list_recent_filings(
        "NVDA", since_days=60, asof=date(2026, 4, 30)
    )
    # 60-day window from 2026-04-30 → cutoff 2026-03-01. Drops 8-K (2026-02-01),
    # 10-K (2026-02-21), and the older 10-K (2025-02-22).
    forms_filed = [(f.form, f.filed.isoformat()) for f in filings]
    assert forms_filed == [
        ("10-Q", "2026-04-30"),
        ("DEF 14A", "2026-04-15"),
        ("4", "2026-03-24"),
    ]


def test_list_recent_filings_limit_caps_results(monkeypatch):
    _patch_http(monkeypatch)
    filings = loader.list_recent_filings("NVDA", form="10-K", limit=1)
    assert len(filings) == 1
    assert filings[0].accession == "0001045810-26-000010"


def test_list_recent_filings_form_and_since_compose(monkeypatch):
    """Form filter AND since_days window apply as AND."""
    _patch_http(monkeypatch)
    filings = loader.list_recent_filings(
        "NVDA", form="10-K", since_days=180, asof=date(2026, 5, 1)
    )
    # 180-day window from 2026-05-01 → cutoff 2025-11-02. Older 10-K (2025-02-22) drops.
    assert [f.accession for f in filings] == ["0001045810-26-000010"]


def test_list_recent_filings_unknown_form_returns_empty(monkeypatch):
    _patch_http(monkeypatch)
    assert loader.list_recent_filings("NVDA", form="N-CSR") == []


# ---- fetch_filing_by_accession ------------------------------------------


def test_fetch_filing_by_accession_returns_specific_filing(monkeypatch):
    _patch_http(monkeypatch)
    metadata, html = loader.fetch_filing_by_accession(
        "NVDA", "0001045810-25-000099"
    )
    assert metadata.accession == "0001045810-25-000099"
    assert metadata.form == "10-K"
    assert metadata.filed == date(2025, 2, 22)
    assert html.startswith("<html")


def test_fetch_filing_by_accession_unknown_raises(monkeypatch):
    _patch_http(monkeypatch)
    with pytest.raises(FilingNotFound, match="not in recent submissions"):
        loader.fetch_filing_by_accession("NVDA", "0000000000-00-000000")


def test_fetch_filing_by_accession_strips_xslt_prefix(monkeypatch):
    """Form 4 primary_doc has 'xslF345X06/' prefix in the feed; canonical raw
    XML lives at the path with that prefix stripped."""
    _patch_http(monkeypatch)
    metadata, _ = loader.fetch_filing_by_accession(
        "NVDA", "0001045810-26-000099"
    )
    assert metadata.primary_doc == "wk-form4_1774386816.xml"
    assert "xslF345X06" not in metadata.primary_doc_url
