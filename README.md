# Clarion Intelligence System

Buffett-style investment research, packaged as installable skills for [Zo Computer](https://docs.zocomputer.com/).

Three things you can do from Zo chat:

1. **Read market regime** — SPY / TLT / RSP color, hurdle rate, what to do about it.
2. **Pull and analyze SEC filings** — single ticker or a watchlist, indexed and queryable in plain English.
3. **Evaluate a single stock** — moat, management, financial trends, kill conditions, position-sizing context.

Built around principles from Berkshire Hathaway and Buffett's annual letters, adapted to a system you can run yourself. Conservative, show-the-math, never fabricates data.

## Install

```
1. In Zo chat: "install the clarion-setup skill"
2. Follow the prompts (one-time: paste a Zo access token from Settings → Advanced)
3. In Zo chat: "install the clarion-regime-check skill"  (and others as you want them)
```

Then ask Zo things like:
- "What's the market regime right now?"
- "Analyze NVDA's most recent 10-K risk factors."
- "Evaluate KO as a long-term holding."

## Skills

**Available now (Phase A):**
- `clarion-setup` — one-time bootstrap (installs library, registers SEC indexer service, creates workspace)
- `clarion-regime-check` — SPY/TLT/RSP regime color and hurdle rate
- `clarion-sec-research` — SEC filing pull, index, query, summarize

**Coming (Phase B):**
- `clarion-single-stock-eval` — Buffett-style evaluation
- `clarion-value-screener` — two-stage S&P 500 screen
- `clarion-thesis-write` — write a thesis in our standard format
- `clarion-thesis-monitor` — health-score active theses, watch kill conditions
- `clarion-expected-return-calc` — equity hurdle rate from regime + risk-free rate
- `clarion-watchlist-update` — append/update watchlists
- `clarion-living-letter-update` — quarterly entry to your investor letter

## Requirements

- A Zo Computer account (free tier works; subscriber tier unlocks higher-quality reasoning models)
- A Zo access token (Settings → Advanced → Access Tokens) — used by the SEC indexer to call models on your behalf, billed against your Zo credits
- ~100 GB workspace headroom is plenty even for a 50-ticker watchlist

No external API keys. No broker accounts. No real-time data feeds.

## Data sources

- Market data: [yfinance](https://github.com/ranaroussi/yfinance) (delayed, free)
- SEC filings: [SEC EDGAR](https://www.sec.gov/edgar) (free, official)
- LLM inference: Zo-hosted models (defaults to free-tier `zo:openai/gpt-5.4-mini` for indexing, configurable)

## License

MIT. See [LICENSE](./LICENSE).

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for design decisions, library layout, and the `/zo/ask` LLM wiring contract.
