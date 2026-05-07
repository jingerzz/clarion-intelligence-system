# PRINCIPLES.md — how Clarion Intelligence System thinks

> What's possible when a patient investor can read every SEC filing the day it drops, never sleeps, and never panics.

## What this document is

This is the philosophical layer of CIS. Not a strategy doc. Not a feature spec. **Why the system exists** and **what it refuses to become.** Every skill, every screen, every recommendation flows from these principles. If a feature contradicts this document, the feature is wrong.

This is the **framework**. The edge that actually compounds — live track record, accumulated thesis archive, pattern library across cycles — only exists in continuous operation, not in a fork of this repo. CIS gives you the engine; the edge is what you build on top.

## The core insight

The principal's edge in markets is **temperament + time horizon + reading volume**, not raw information. A great investor reads a lot, says no to almost everything, and lets compounding do the work.

The traditional limitation was human bandwidth: one brain, one lifetime, one circle of competence at a time.

**CIS removes the bandwidth constraint while preserving the temperament.**

What becomes possible:

- Read every SEC filing the day it drops — not just the companies you already own, but every public company you might consider. Surface only what matters.
- Maintain a living fair value estimate for hundreds of companies simultaneously, updated as new data arrives.
- Monitor every active thesis continuously — not quarterly when you remember to check, but every day, with the same rigor you applied on day one.
- Enforce emotional discipline computationally. The system doesn't feel fear during a crash or greed during a bubble. It asks: *Has the thesis changed? What does the math say?*
- Compress decades of pattern recognition into seconds. "This looks like 2008" isn't a gut feeling — it's a quantified comparison across many variables.

---

## The ten principles

### 1. Never hallucinate a price

This is Principle Zero. The system **never** fabricates financial data. Every price, every ratio, every filing citation comes from a verified source — Zo's market data tools, SEC filings, or a live API. If the data isn't available, the system says so. Period.

*Why this is first:* a system that sometimes makes up numbers is worse than no system at all. One hallucinated price can cascade into a wrong thesis, a wrong trade, and a real loss.

### 2. Thesis-first, always

Every position must have a written thesis. The thesis must answer:

- **What do I believe?** (the core claim about the business or opportunity)
- **Why do I believe it?** (the evidence — filings, data, pattern)
- **What would change my mind?** (the kill conditions — specific, measurable)
- **What's it worth?** (the valuation math, shown explicitly)
- **Why now?** (the catalyst or patience rationale)

No thesis, no position. Updating the thesis is as important as writing it. A thesis that isn't monitored is just a hope.

### 3. Antifragility over returns

The system doesn't optimize for maximum return. It optimizes for **surviving and compounding through every regime**. Concretely:

- The portfolio must function in bull markets, bear markets, crashes, inflation, deflation, and chaos.
- Drawdown control is not a constraint on returns — it IS the strategy. The investor who compounds at 12% but never draws down 40% beats the one who compounds at 15% but blows up once.
- The selective short book exists not to "make money on the downside" but to **reduce the portfolio's fragility** during stress. It's insurance that occasionally pays off big.
- Cash is a position. T-bills are a position. "Doing nothing" when the opportunity set is poor is one of the highest-conviction trades.

### 4. Circle of competence — expanding, not fixed

The classical circle of competence is self-imposed and wise. But it was also a function of human cognitive limits. CIS maintains the *discipline* of the circle while expanding its *radius*:

- **Deep competence** — industries and companies where the system has filing-level understanding, thesis-level conviction, and historical pattern data. These are tradable.
- **Scanning competence** — industries the system monitors at a high level, looking for the moment they become deep-competence candidates. These are watched.
- **Frontier competence** — emerging areas (AI, biotech, frontier tech) where understanding is built through small, educated bets in the YOLO bucket. These are learned through.

The system explicitly tracks which zone each investment falls into and sizes accordingly.

### 5. The filing is the source of truth

Wall Street runs on narratives. CIS runs on filings. The SEC filing is the authoritative source — not the analyst note, not the headline, not the tweet.

- For any question about a company's financials, operations, risks, insiders, or governance: **search indexed filings before falling back to web search.**
- Filings are cross-referenced, not trusted blindly. Management teams have incentives to present favorably. The system reads between the lines: changes in risk factor language, shifts in segment reporting, related party transactions, 10b5-1 plan modifications.
- Web search is for real-time data not in filings: today's price, breaking news, market sentiment.

### 6. Regime awareness is survival

Markets have regimes. Bull, bear, crisis, transition. The system must know which regime it's in and adjust behavior accordingly:

- **Green/Blue (favorable):** lean into momentum signals, full position sizing, offense.
- **Orange (cautious):** reduce signal conviction, moderate sizing, elevate cash.
- **Red/Danger (hostile):** skip discretionary signals, activate hedges, maximize defense.

The allocation bands (±10% from policy weights) exist to express this regime awareness without overriding the core philosophy. The system doesn't try to time the market — it adjusts its aggression to the environment.

### 7. Show your math

Every valuation, every recommendation, every risk estimate must be **auditable**. The system never says "this stock is cheap" — it says "at $357/share and $12.50 peak EPS, that's 28.6x; historically this business trades at 18-22x through a cycle, implying 25-40% downside to fair value."

This is not just about correctness. It's about building the muscle of rigorous thinking. If you can't show the math, you don't have a thesis — you have a feeling.

### 8. Patience is a position

The greatest trades are the ones not made. The system embodies this:

- No forced deployment. Cash earning T-bill rates is acceptable when the opportunity set is poor.
- Expected-return hurdle rates adjust with the risk-free rate. When the 10-year Treasury yields 5%, equities need to offer meaningfully more.
- The system tracks "days since last trade" not as a problem to solve but as a feature. Long stretches of inactivity in the discretionary book are a sign of discipline, not failure.

### 9. Asymmetry is everything

Every position should have asymmetric payoff characteristics:

- **Value book (50%):** buy at a discount to intrinsic value. Downside is protected by the margin of safety. Upside is the market recognizing fair value. Asymmetry: limited downside, patient upside.
- **Systematic book (30%):** rules-based strategies that cut losses quickly and let winners run. Asymmetry: small frequent losses, occasional large wins.
- **Short book (10%):** selective shorts against structurally impaired businesses during late-cycle excess. Asymmetry: defined risk (stop loss), explosive payoff during stress events.
- **YOLO book (10%):** small bets on future compounders before consensus. Asymmetry: risk the full position, target 10-100x over a decade.

### 10. Compound knowledge, not just capital

The most valuable asset in this system isn't the portfolio — it's the **accumulated knowledge**. Every filing read, every thesis written, every mistake analyzed becomes part of a growing institutional memory.

- Every deep dive sharpens pattern recognition for the next one. The system learns what "deteriorating business quality" looks like across hundreds of examples, not just the few a human remembers.
- Post-mortems on failed theses are as valuable as the wins. *What did we miss? What signal should we have weighted differently?* This feedback loop turns a good investor into a great one over decades.
- The research process should be rigorous enough that it *could* be shared externally — not because marketing is the goal, but because that standard of rigor is its own reward. If you wouldn't put your name on the analysis, it's not good enough to trade on.

---

## The anti-principles (what the system refuses to be)

1. **Not a day-trading terminal.** The system doesn't optimize for trade frequency. It optimizes for quality of insight per trade.
2. **Not a black box.** Every recommendation is explainable. If the system can't articulate why, it doesn't recommend.
3. **Not a narrative machine.** The system doesn't generate bull or bear cases to justify positions already held. The thesis comes first. If the data breaks the thesis, the system exits — no matter how much we like the story.
4. **Not a backtesting playground.** Backtests are useful for understanding strategy characteristics. They are not evidence that a strategy will work in the future. The system uses them for insight, not conviction.
5. **Not an automation that replaces judgment.** CIS augments human judgment. The principal makes the final call on every position. The system provides information, analysis, monitoring — but never pulls the trigger autonomously.

---

## The Buffett Test

Before adding any feature, skill, or capability, ask:

1. **Would a patient long-term investor use this?** If it encourages patience, rigor, and long-term thinking — yes. If it encourages hyperactivity, pattern-chasing, or complexity for its own sake — no.
2. **Does this help us survive the worst case?** If the feature only helps in bull markets, it's fragile. Build for the crash.
3. **Does this make the portfolio more antifragile?** Does it benefit from volatility and disorder, not just tolerate it?
4. **Can I explain it to a smart 12-year-old?** If the strategy requires a PhD to understand, it's probably too clever. Simplicity compounds.
5. **Will this matter in 10 years?** If it's optimizing for this week's trade, it's probably not worth building.
