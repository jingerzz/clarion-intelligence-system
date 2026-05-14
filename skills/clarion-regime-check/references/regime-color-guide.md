# Regime color guide

Five colors classify the cross-asset risk environment. Each maps to allocation policy bands and an equity hurdle premium. Color is determined by the **signs of SPY and TLT's 20-day returns** plus a drawdown override; breadth (RSP-SPY 60d spread) is a separate informational flag, never a color override.

> **Semantics revised 2026-05-13.** Historical theses and letters tagged with colors before this date use the previous mapping (old GREEN = SPY↑ TLT↓; old BLUE = both up; old ORANGE = SPY↓ TLT↑). The current system uses the SPY/TLT strat framework from `jingerzz/AI-trading-platform`. The names and hurdle premiums are the same; only the SPY/TLT-quadrant-to-color mapping changed.

## Quick reference

| Color | SPY 20d | TLT 20d | Plain English |
|---|---|---|---|
| **GREEN** | ↑ | ↑ | Both assets up — healthy liquidity tide, cleanest deploy |
| **BLUE** | ↓ | ↑ | Bonds hedging properly — add-on-weakness opportunity |
| **ORANGE** | ↑ | ↓ | Equities rallying despite bond stress — caution |
| **RED** | ↓ ≥ 5% | ↓ | Correlation breakdown / no bond hedge — defensive |
| **DANGER** | (drawdown override) | — | SPY 20%+ below 252d high — max defense |

## GREEN — Both up, "everything works"

**Trigger:** SPY 20d return > 0 AND TLT 20d return > 0.

The healthiest regime. Stocks and bonds both rising on supportive liquidity. The system is functioning as intended; risk assets are bid; the bond market is not signaling stress. This is the cleanest "deploy" environment.

- Allocation tilt: lean equities (55% Value bucket per ALLOCATION-POLICY)
- Hurdle premium: **+4.0%**
- Action: deploy on quality names that clear the hurdle; size full positions

## BLUE — Bonds hedging, system functioning

**Trigger:** SPY 20d return < 0 AND TLT 20d return > 0.

Stocks pulling back while bonds rally — the classic negative correlation working as designed. The bond market is doing its job as a hedge; the equity decline is being absorbed by flight-to-safety bid in Treasuries. From a portfolio standpoint this is a *normal*, functioning market — and on large-move days (SPY < −1%, TLT > +1%), historically a higher-odds buy-the-dip setup.

- Allocation tilt: lean equities (55% Value)
- Hurdle premium: **+4.0%**
- Action: this is the regime to **add to high-conviction positions** when fundamentals haven't changed. The harder the SPY decline with TLT rallying, the stronger the signal.

## ORANGE — Equities up, bonds down

**Trigger:** SPY 20d return > 0 AND TLT 20d return < 0.

Equities rallying while bonds are selling off. Often signals inflation or rate-shock concerns — the market is rising *despite* policy headwinds, not because of supportive liquidity. Less clean than GREEN.

- Allocation: baseline 50/30/10/10
- Hurdle premium: **+6.0%**
- Action: new positions need a clearer margin of safety; consider trimming high-multiple names; don't size up aggressively

## RED — Correlation breakdown

**Trigger:** SPY 20d return < −5% AND TLT 20d return < 0.

The worst non-crash regime: equities selling off *and* bonds aren't catching a bid. Bond-equity correlation has broken. Typically inflation regime, rate shock, or systemic stress. No hedge is working.

- Allocation: defensive 45/25/15/10 (more shorts, less Value)
- Hurdle premium: **+8.0%**
- Action: shift weight to short bucket; trim Value names below conviction; raise cash

The −5% SPY magnitude guard prevents every mild "both down" period from tripping RED. A SPY −2% / TLT −1% week is concerning but not a correlation breakdown — that falls through to ORANGE (default conservative).

## DANGER — Severe drawdown

**Trigger:** SPY drawdown ≤ −20% from 252-day high.

Crash regime. Overrides all quadrant logic. Maximum defense. Capital preservation is paramount.

- Allocation: 40/20/20/5 with explicit cash buffer
- Hurdle premium: **+10.0%**
- Action: no new long entries except deeply discounted forced sales; review every active thesis for kill-condition triggers; preserve liquidity

## Breadth flag (separate signal)

The RSP-SPY 60-day spread is reported alongside the color but **does not change it**.

- **broad** — RSP keeps up with SPY (spread ≥ −5%). Leadership is healthy.
- **narrow** — RSP lags SPY by 5% or more over 60d. A handful of mega-caps are masking weakness in the average stock. Worth noting for position sizing — narrow leadership in a GREEN or BLUE regime is less convicted than broad leadership. Note it; don't let it force a color change.

## Hurdle rate computation

If a 1Y T-bill yield is supplied, the equity hurdle rate equals:

```
hurdle = rf + regime_premium
```

Example: in ORANGE with rf = 4.5%, hurdle = 4.5% + 6.0% = **10.5%**.

A long position must clear this hurdle in expected return to be worth holding. The hurdle rises in worse regimes — we demand more compensation when conditions are less forgiving.
