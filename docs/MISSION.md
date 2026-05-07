# MISSION.md — what CIS is and why it exists

---

## The one-sentence mission

**An AI-native investment engine that compounds wealth antifragily across all market regimes, with the analytical bandwidth of a 20-person team and the emotional discipline of a machine.**

---

## The problem CIS solves

Family offices between $10M and $100M AUM occupy an awkward middle ground. They're too large for retail tools but too small for institutional infrastructure. They can't afford a team of 20 analysts, a Bloomberg terminal on every desk, and a dedicated risk management department. So they typically:

1. **Outsource to wealth managers** who charge 1%+ and deliver index-hugging mediocrity, or
2. **DIY with retail tools** that can't handle multi-asset, multi-strategy portfolios, or
3. **Hire a small team** that's overworked, under-resourced, and can't cover the full opportunity set.

CIS is option four: **a force multiplier that gives a single investment principal the analytical bandwidth of a 20-person team**, the emotional discipline of a rules-based system, and the pattern recognition of 100 years of market history.

---

## What you get from this repo, and what you don't

CIS is the **framework and the engine**. You get:

- The four-bucket portfolio architecture (Value / Systematic / Short / YOLO)
- The decision cascade (regime → thesis → valuation → sizing → risk → human approval)
- The information hierarchy (filings > verified external > supplementary)
- The Buffett Question Bank operationalized against indexed filings
- The expected-return framework and hurdle-rate math
- A working SEC EDGAR fetcher, indexer, and search layer
- Skills you can install on Zo Computer and run from chat

What you don't get from a fork of this repo:

- **The live track record** — a real portfolio operated through real cycles
- **The accumulated thesis archive** — every active thesis, kill conditions, and historical outcomes
- **The pattern library** — what "deteriorating business quality" looks like across hundreds of names
- **The institutional memory** — post-mortems on failed theses, lessons from drawdowns, relationships with how the system has been used

The framework is the engine. The edge is what you compound on top of it through continuous operation.

---

## Who CIS serves

### Phase 1 — the principal (now)

A solo investment principal who wants:

- Morning briefings that surface what matters
- Deep dives that rival institutional research
- Thesis monitoring that never sleeps
- Risk visibility across all four strategy buckets
- Screening pipelines that cover the full equity universe, not just a handful of names

The system should feel like a brilliant, tireless analyst partner who has read everything, remembers everything, and never panics.

### Phase 2 — the family office (next)

A small family office ($10M–$100M) with 1–3 investment professionals. The system adds:

- Multi-user access with role-based views (principal, analyst, compliance)
- Formal reporting (quarterly letters, performance attribution, tax-lot tracking)
- Compliance guardrails (concentration limits, restricted lists, audit trails)
- Client-facing materials generated from the same research engine

### Phase 3 — the platform (eventually)

The architecture, skills, and investment process — battle-tested through Phase 1 and 2 — become a product that other family offices can adopt. The live track record serves as proof of concept.

---

## The asset universe

CIS is multi-asset by design. Each asset class serves a specific portfolio function:

**Equities** — the primary return engine. Long (value compounders) and short (structural-impairment hedges). Includes individual stocks across all market caps.

**Fixed income** — the stability anchor. T-bills as the risk-free alternative when equity expected returns are poor. Treasury futures (ZB/ZN) for tactical duration exposure and equity hedging.

**Precious metals** — the chaos hedge. Gold and silver as portfolio insurance against monetary regime change, inflation surprises, and geopolitical tail risks. Small, persistent allocation.

**Crypto** — the frontier allocation. Bitcoin as digital gold / monetary hedge. Select altcoins only in the YOLO bucket with explicit thesis and kill conditions. The most speculative corner; sized accordingly.

---

## The four strategy buckets

### 1. Discretionary Value & Quality (50% target, 40-60% band)
*The Buffett core.*

Long-term holdings in high-quality businesses purchased at reasonable prices. T-bills when equity expected returns (as a function of S&P 500 P/E) don't meet hurdle rates.

Capabilities: custom screener for quality + value + catalyst, SEC filing analysis at scale, living fair-value models updated with each filing, thesis health monitoring with automatic kill-condition checks, historical expected-return calculator.

### 2. Systematic Strategies (30% target, 20-40% band)
*The machine edge.*

Rules-based strategies executed through tax-efficient vehicles (ES/MES futures, ZB/ZN for bonds). Anchored by SPY/TLT regime signals with room for additional systematic overlays.

Capabilities: SPY/TLT/RSP regime signals, ES/MES execution framework with session-aware levels, bond-equity correlation monitoring, backtest analysis and signal performance tracking.

### 3. Selective Short Book (10% target, 0-20% band)
*The antifragility engine.*

Not a bearish bet on the market — a surgical selection of structurally impaired businesses overvalued relative to deteriorating fundamentals. The goal is asymmetric payoff during market stress.

Capabilities: short-specific screener (declining margins, rising debt, insider selling, accounting red flags), filing analysis focused on risk-factor changes, position sizing calibrated for short-specific risk, regime-dependent activation.

### 4. Educated YOLO (10% target, 5-15% band)
*The moonshot book.*

Small positions in potential future compounders. Names with huge optionality the market hasn't yet recognized.

Capabilities: scenario modeling (what's this worth if the bull case plays out in 10 years?), TAM analysis and market-share modeling, pattern matching against historical multi-baggers, network-effect and moat analysis. Position sizing: small enough to lose 100%, large enough to matter if it 10x's.

---

## What success looks like

### Year 1
- All four strategy buckets operational with at least basic skill coverage
- Morning briefing and risk dashboard running daily
- Thesis documents written and monitored for every active position
- Portfolio return attribution by bucket
- First version of the custom screener pipeline

### Year 3
- Track record long enough to be meaningful (3yr CAGR, max drawdown, Sharpe)
- Multi-strategy portfolio has survived at least one significant drawdown event
- Research archive deep enough to inform pattern recognition across sectors
- Architecture stable enough to onboard a second user
- At least one YOLO position has demonstrated the thesis (2x+)

### Year 10
- Demonstrated ability to compound through multiple regime changes
- Accumulated knowledge base spanning hundreds of companies and multiple market cycles
- Platform architecture ready for external family office adoption
- The institutional memory itself becomes a durable competitive advantage

---

## The competitive moat

CIS's moat compounds over time across three dimensions:

1. **Knowledge moat.** Every filing read, every thesis written, every trade journaled builds institutional memory. The system gets smarter with every cycle — pattern recognition improves as the archive of analyzed companies grows.
2. **Process moat.** The skill architecture — once refined through real-world use — embodies investment wisdom that took decades to accumulate. It's the difference between having read about value investing and having operationalized it.
3. **Track record moat.** Real returns through real market regimes. No backtest can substitute for a live track record that includes drawdowns, mistakes, and recoveries. Time in the market is the one edge that can't be shortcut.
