# ALLOCATION-POLICY.md — Investment Policy Statement

---

## Policy summary

This document defines the target allocation, regime-adaptive bands, rebalancing rules, and risk limits for a CIS-driven portfolio. It is the **constitution** of the portfolio — changes require deliberate review, not reactive adjustment.

The weights in this document are a starting point that has worked well in practice. They are not the only defensible calibration. Adapt to your own situation, risk tolerance, and tax context — but adapt deliberately, not reactively.

---

## Target allocation & bands

| Bucket | Target | Min | Max | Vehicle | Tax treatment |
|---|---|---|---|---|---|
| **Discretionary Value & Quality** | 50% | 40% | 60% | Individual equities, T-bills | Long-term cap gains (>1yr hold target) |
| **Systematic Strategies** | 30% | 20% | 40% | ES/MES futures, ZB/ZN futures, ETFs | 60/40 blended rate (futures Section 1256) |
| **Selective Short Book** | 10% | 0% | 20% | Individual equity shorts, put spreads | Short-term cap gains |
| **Educated YOLO** | 10% | 5% | 15% | Equities, LEAPS, crypto | Mixed (crypto held >1yr for LTCG) |

Total portfolio: 100% deployed across these four buckets. Cash and T-bills within the Value bucket count toward that 50%, not as a separate allocation.

---

## Regime-adaptive allocation

The regime signal from `clarion-regime-check` determines where within the bands the portfolio targets. This is **not market timing** — it's adjusting the portfolio's aggression to the environment.

### Regime → allocation mapping

**Green/Blue regime (favorable)**
```
Value:      55% (lean toward equities over T-bills within the bucket)
Systematic: 30% (full signal following)
Short:       5% (minimal — reduced need for hedging)
YOLO:       10% (normal)
```
Rationale: favorable regime means momentum works, mean-reversion is moderate, the market environment supports risk-taking. Reduce defensive short allocation; deploy that capital into the value book.

**Orange regime (cautious)**
```
Value:      50% (increase T-bill weight within bucket)
Systematic: 30% (follow signals but at 75% sizing)
Short:      10% (normal — begin building watchlist)
YOLO:       10% (hold existing, no new positions)
```
Rationale: mixed signals. Don't panic, but don't press. The systematic book reduces sizing to reflect lower signal conviction. YOLO freezes — this isn't the time for new speculative bets.

**Red regime (defensive)**
```
Value:      45% (heavy T-bill weight, only add at extreme discounts)
Systematic: 25% (follow signals at 50% sizing)
Short:      15% (increase — this is when shorts earn their keep)
YOLO:       10% (hold existing, begin reviewing kill conditions)
Cash/Bills:  5% (explicit cash buffer from reduced systematic)
```
Rationale: defensive posture. The value book shifts to T-bills and only buys at "gift" valuations. Systematic reduces dramatically. Short book expands — structurally impaired businesses get punished fastest in Red regimes.

**Danger state (crisis)**
```
Value:      40% (maximum T-bill weight, equities only at generational discounts)
Systematic: 20% (minimum band, follow only highest-conviction signals)
Short:      20% (maximum — full deployment of short book)
YOLO:        5% (minimum band, review all positions for exit)
Cash/Bills: 15% (explicit cash from reduced systematic + YOLO)
```
Rationale: capital preservation is paramount. The portfolio becomes maximally defensive. The short book is the primary offense. The value book waits for the kind of opportunity that defines a career.

---

## Rebalancing rules

### Trigger-based rebalancing
- **Hard trigger:** any bucket exceeds its band maximum or minimum → rebalance within 5 business days
- **Soft trigger:** any bucket deviates >5% from regime-adjusted target → flag for review at next weekly risk check
- **No trigger:** within bands and within 5% of target → no action needed

### Calendar-based review
- **Monthly:** allocation check (1st of month) — are we within bands?
- **Quarterly:** full rebalance to regime-adjusted targets
- **Annual:** policy review — are the bands, targets, and vehicles still appropriate?

### Rebalancing method
1. Sell overweight positions (prioritize: highest-gain lots for tax loss harvesting if applicable, or most overvalued relative to thesis)
2. Buy underweight positions (prioritize: highest expected return per thesis, best entry relative to fair value)
3. Never force a trade just to hit a number — if there's nothing to buy in an underweight bucket, hold cash in that bucket until opportunity arrives

---

## Risk limits

### Position limits

| Level | Limit | Rationale |
|---|---|---|
| Single equity position | Max 10% of portfolio | Concentration risk — even the most concentrated value investors rarely run a single position above 15% |
| Single short position | Max 3% of portfolio | Shorts have unlimited theoretical loss — size must be controlled |
| Single YOLO position | Max 3% of portfolio | These are high-variance bets — keep each one survivable |
| Single option position (notional) | Max 5% of portfolio | Options leverage amplifies both directions |
| Single sector (long) | Max 25% of portfolio | Sector concentration creates correlated risk |

### Aggregate risk limits

| Metric | Green | Yellow | Red |
|---|---|---|---|
| Total dollar-at-risk (sum of all position stops) | < 2% of portfolio | 2-3% | > 3% → reduce immediately |
| Gross long exposure | < 120% | 120-150% | > 150% → reduce |
| Net exposure (long − short) | 40-100% | 30-40% or 100-110% | < 30% or > 110% |
| Correlation risk (ES long + stocks long) | acceptable if < 60% portfolio | flag if 60-80% | reduce if > 80% |

### Drawdown rules

| Drawdown from peak | Action |
|---|---|
| -5% | Review all positions. Tighten stops. No new longs. |
| -10% | Reduce systematic sizing to 50%. Increase short allocation. Review all theses. |
| -15% | Reduce to minimum band on all buckets except short. Full thesis review. Consider whether this is a buying opportunity or a thesis-breaking event. |
| -20% | Emergency review. Crash, or regime change? If theses intact, this is the time to deploy — historically the best long-term entries come during drawdowns of this magnitude. |
| -25% | Maximum defensive posture. Only maintain positions with ironclad theses. Consider whether the portfolio structure itself needs to change. |

---

## Expected-return framework

The equity allocation within the Value bucket is governed by a historical expected-return model. This is the simplest and most powerful allocation tool: *why take equity risk for a lower return than you can get risk-free?*

### S&P 500 P/E → 10-year forward return (historical)

| P/E range | Historical 10-year CAGR | Implied action |
|---|---|---|
| < 10 | 12-16% | Aggressive equity allocation (max band) |
| 10-15 | 8-12% | Normal equity allocation |
| 15-20 | 5-8% | Moderate equity allocation |
| 20-25 | 2-5% | Light equity allocation, increase T-bills |
| 25-30 | 0-3% | Minimal equity allocation, heavy T-bills |
| > 30 | Negative to 0% | Maximum T-bills, focus on shorts and quality |

**Current application:** if the 10-year Treasury yields more than the implied equity return, T-bills get priority within the Value bucket. Use the **Shiller CAPE** as the primary lookup; the trailing P/E is a secondary cross-check. If the two diverge meaningfully (>5 P/E points apart), note the divergence in the output.

### Hurdle rate calculation

```
Equity hurdle = Risk-free rate + Regime premium

Where regime premium =
  Green/Blue:  +4%
  Orange:      +6%
  Red:         +8%
  Danger:     +10%

Example (Orange regime, T-bills at 4.5%):
  Hurdle = 4.5% + 6% = 10.5%
  → Only buy equities with >10.5% expected annual return
```

The `clarion-expected-return-calc` skill operationalizes this framework and produces a 5-tier Value-bucket allocation recommendation (Strong Equity / Lean Equity / Neutral / Lean T-bills / Maximum T-bills).

---

## Tax efficiency rules

1. **Hold-period targeting.** Value-bucket positions target >1 year holding period for long-term capital gains rates. Don't sell a position at 11 months unless the thesis is broken.
2. **Futures advantage.** ES/MES and ZB/ZN futures receive Section 1256 treatment (60% long-term / 40% short-term) regardless of holding period. This is why the systematic book uses futures over ETFs.
3. **Tax-loss harvesting.** At year-end and after significant drawdowns, review for tax-loss harvesting opportunities. Harvest losses to offset short-term gains from the short book.
4. **Crypto holding period.** Bitcoin and crypto positions target >1 year hold for LTCG treatment. Only exit early if the thesis is broken.
5. **Wash-sale awareness.** When harvesting losses, wait 31 days before re-establishing a substantially identical position, or substitute with a non-identical alternative.

---

## Policy change process

This document can only be changed through:

1. **Quarterly review** — regular scheduled review of whether bands, limits, and rules remain appropriate.
2. **Regime change event** — a significant market event (e.g., COVID-style crash, GFC-level disruption) that warrants an emergency review.
3. **Thesis evolution** — new information about the investment process itself (e.g., a strategy that consistently underperforms) that warrants structural changes.

Changes are documented with date, rationale, and the specific modification. The previous version is preserved.

**What does NOT justify a policy change:** a bad week, a missed trade, FOMO, a friend's hot tip, or anything that feels urgent in the moment. Urgency is the enemy of good portfolio policy.
