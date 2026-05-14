# Phase 2 candidate-signal backtest — generated 2026-05-14

Out-of-band backtest validating two candidate signals from `jingerzz/AI-trading-platform/packages/spy-tlt-strat` against SPY buy-and-hold and all-T-bill baselines, ahead of a possible Phase 2 port into Clarion's `regime/color.py`. Risk-free rate fixed at **4.0%** annualized.

## Headline result

| Configuration (full period) | CAGR | Max DD | Sharpe | vs B&H CAGR | vs B&H DD |
|---|---|---|---|---|---|
| SPY buy-and-hold (baseline) | +10.77% | -55.19% | 0.43 | +0.00% | +0.00% |
| All T-bills (baseline) | +3.99% | +0.00% | 0.06 | -6.77% | +55.19% |
| combined @ 1d hold (max-Sharpe) | +8.91% | -13.61% | 0.65 | -1.86% | +41.58% |
| combined @ 2d hold (best CAGR w/ contained DD) | +9.66% | -16.85% | 0.60 | -1.11% | +38.34% |
| big_blue_day @ 1d hold (signal in isolation) | +7.21% | -16.26% | 0.55 | -3.56% | +38.93% |
| capitulation @ 1d hold (most defensive) | +5.65% | -6.98% | 0.35 | -5.12% | +48.20% |

**Top configuration: `combined` signal, 1-day hold.** Sharpe 0.65 vs SPY B&H 0.43 — a +51% improvement in risk-adjusted return. CAGR gives up 1.86pp of return relative to buy-and-hold, but cuts the worst-case drawdown by 42pp (from -55.2% to -13.6%).

**OOS robustness (2002-07 to 2015-12, includes GFC):** combined@1d beats buy-and-hold on *both* CAGR (+9.25% vs +8.34%) *and* drawdown (-13.61% vs -55.19%) — the dominance is genuine, not an artifact of the post-2016 bull run.

## What this means for Clarion Phase 2

The signals carry real empirical edge — at short holds (1-2 trading days), the `combined` strategy beats buy-and-hold on Sharpe and dramatically reduces worst-case drawdown. Per-fire win rates are 60-73% across configurations, and a large fraction of fires sit in (or near) the bottoms of historical sell-offs.

**Recommended port shape: observability flags, not a rotation strategy.** The literal cash → SPY → cash rotation is dominated by 1-2 day holds, which is too short-horizon for Clarion's Buffett-style operating model. But the underlying *signal* — "the market just sold off hard while bonds held / volume spiked" — is exactly the moment a long-horizon investor wants to be paying attention to add capital. Surface as flags on `RegimeSnapshot`; let the operator decide whether and how much to deploy. The strategy backtest here is the empirical proof that the signals identify high-value windows; it's not the proposed implementation.

**On longer holds:** the user's bar was "better returns without compromising drawdown protection." The sweep shows a clear DD wall between 2- and 3-day holds — CAGR creeps up at 5d/10d/21d holds, but drawdown jumps from ~-17% (2d) to ~-35% (3d) to ~-48% (21d). No long-hold configuration cleanly beats 1-2 day on the user's stated criterion.

## Methodology

- **Data**: Vendored SPY + TLT daily history (adjusted close + volume) from `spy-tlt-strat/data/`. Common trading dates: 2002-07-30 → 2026-03-18 (5,947 bars).
- **Period splits**: Full (entire series); OOS (start → 2015-12-31, pre-tuning); IS (2016-01-04 → end, the spy-tlt-strat tuning window).
- **Signals** (Tier 1 in spy-tlt-strat):
  - `big_blue_day` — SPY 1d return < -1% AND TLT 1d return > +1%
  - `capitulation` — SPY 1d return < -1% AND TLT 1d return < 0 (Red day) AND SPY volume > 1.5× its trailing 20d average
  - `combined` — either of the above fires
- **Strategy**: 100% T-bills earning 4.0% by default. On a fire, rotate 100% to SPY for `hold_days` trading days. Re-fire during a hold resets the clock. No leverage, no costs, no slippage.
- **Metrics**: CAGR, max drawdown, Sharpe (rf-net, 252-day annualization), # fires (independent trades only — re-fires extend existing trades), win rate (% of fires whose SPY return beats T-bills over the hold), avg per-fire SPY return, time-in-market, delta vs. SPY buy-and-hold.

## Baselines (full period)

| Strategy | CAGR | Max DD | Sharpe |
|---|---|---|---|
| SPY buy-and-hold | +10.77% | -55.19% | 0.43 |
| All T-bills | +3.99% | +0.00% | 0.06 |

## Sweep — Full period

_SPY B&H reference: CAGR +10.77%, Max DD -55.19%, Sharpe 0.43_

### Signal: `big_blue_day`

| Hold (d) | CAGR | Max DD | Sharpe | # trades | Win % | Avg/trade | Time in mkt | vs B&H CAGR | vs B&H DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | +7.21% | -16.26% | 0.55 | 216 | +58.80% | +0.36% | +3.83% | -3.56% | +38.93% |
| 2 | +7.98% | -18.74% | 0.51 | 194 | +65.46% | +0.52% | +7.47% | -2.78% | +36.44% |
| 3 | +7.40% | -34.93% | 0.38 | 177 | +66.10% | +0.55% | +10.73% | -3.37% | +20.26% |
| 5 | +9.67% | -31.05% | 0.49 | 146 | +71.23% | +1.02% | +16.41% | -1.10% | +24.14% |
| 10 | +9.71% | -34.57% | 0.44 | 112 | +67.86% | +1.44% | +27.43% | -1.06% | +20.62% |
| 21 | +7.86% | -47.71% | 0.31 | 68 | +69.12% | +2.06% | +44.16% | -2.91% | +7.48% |
| 63 | +10.11% | -55.19% | 0.41 | 20 | +90.00% | +10.74% | +72.37% | -0.66% | +0.00% |
| 126 | +9.99% | -55.19% | 0.40 | 8 | +100.00% | +33.14% | +86.19% | -0.78% | -0.00% |
| 252 | +10.70% | -55.19% | 0.43 | 2 | +100.00% | +316.36% | +96.28% | -0.07% | +0.00% |

### Signal: `capitulation`

| Hold (d) | CAGR | Max DD | Sharpe | # trades | Win % | Avg/trade | Time in mkt | vs B&H CAGR | vs B&H DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | +5.65% | -6.98% | 0.35 | 63 | +65.08% | +0.65% | +1.13% | -5.12% | +48.20% |
| 2 | +5.83% | -9.24% | 0.35 | 56 | +67.86% | +0.80% | +2.19% | -4.94% | +45.95% |
| 3 | +5.79% | -11.18% | 0.31 | 54 | +66.67% | +0.85% | +3.13% | -4.98% | +44.01% |
| 5 | +5.42% | -13.72% | 0.23 | 49 | +65.31% | +0.79% | +4.88% | -5.35% | +41.47% |
| 10 | +5.48% | -14.42% | 0.22 | 48 | +60.42% | +0.95% | +8.96% | -5.29% | +40.77% |
| 21 | +6.72% | -17.17% | 0.31 | 44 | +70.45% | +1.90% | +17.71% | -4.05% | +38.02% |
| 63 | +7.14% | -42.94% | 0.28 | 27 | +70.37% | +4.68% | +41.84% | -3.63% | +12.25% |
| 126 | +7.99% | -51.48% | 0.32 | 16 | +81.25% | +10.59% | +62.50% | -2.78% | +3.71% |
| 252 | +10.43% | -55.19% | 0.45 | 7 | +85.71% | +41.11% | +83.10% | -0.34% | -0.00% |

### Signal: `combined`

| Hold (d) | CAGR | Max DD | Sharpe | # trades | Win % | Avg/trade | Time in mkt | vs B&H CAGR | vs B&H DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | +8.91% | -13.61% | 0.65 | 274 | +60.95% | +0.44% | +4.96% | -1.86% | +41.58% |
| 2 | +9.66% | -16.85% | 0.60 | 236 | +66.10% | +0.59% | +9.57% | -1.11% | +38.34% |
| 3 | +9.18% | -35.46% | 0.49 | 214 | +67.29% | +0.65% | +13.54% | -1.59% | +19.73% |
| 5 | +9.83% | -35.81% | 0.48 | 174 | +70.69% | +0.91% | +20.36% | -0.94% | +19.38% |
| 10 | +10.50% | -41.09% | 0.48 | 130 | +69.23% | +1.43% | +33.31% | -0.27% | +14.10% |
| 21 | +9.64% | -47.88% | 0.40 | 78 | +73.08% | +2.41% | +53.29% | -1.13% | +7.31% |
| 63 | +10.12% | -55.19% | 0.40 | 19 | +89.47% | +12.24% | +83.15% | -0.65% | +0.00% |
| 126 | +10.26% | -55.19% | 0.41 | 6 | +100.00% | +50.97% | +93.69% | -0.51% | -0.00% |
| 252 | +11.16% | -55.19% | 0.45 | 2 | +100.00% | +356.87% | +99.61% | +0.39% | +0.00% |

## Sweep — OOS slice (pre-2016)

_SPY B&H reference: CAGR +8.34%, Max DD -55.19%, Sharpe 0.31_

### Signal: `big_blue_day`

| Hold (d) | CAGR | Max DD | Sharpe | # trades | Win % | Avg/trade | Time in mkt | vs B&H CAGR | vs B&H DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | +7.35% | -16.26% | 0.57 | 142 | +59.86% | +0.33% | +4.44% | -0.99% | +38.93% |
| 2 | +8.26% | -18.74% | 0.51 | 125 | +61.60% | +0.50% | +8.64% | -0.08% | +36.44% |
| 3 | +7.00% | -34.93% | 0.33 | 112 | +65.18% | +0.44% | +12.33% | -1.33% | +20.26% |
| 5 | +10.55% | -30.16% | 0.54 | 93 | +70.97% | +1.04% | +18.60% | +2.21% | +25.03% |
| 10 | +9.24% | -34.57% | 0.40 | 68 | +66.18% | +1.30% | +30.61% | +0.90% | +20.62% |
| 21 | +6.87% | -47.71% | 0.24 | 41 | +65.85% | +1.73% | +47.97% | -1.47% | +7.48% |
| 63 | +8.93% | -55.19% | 0.34 | 10 | +90.00% | +10.78% | +75.48% | +0.59% | +0.00% |
| 126 | +8.17% | -55.19% | 0.30 | 4 | +100.00% | +30.62% | +86.25% | -0.16% | -0.00% |
| 252 | +8.22% | -55.19% | 0.30 | 2 | +100.00% | +67.26% | +93.46% | -0.12% | +0.00% |

### Signal: `capitulation`

| Hold (d) | CAGR | Max DD | Sharpe | # trades | Win % | Avg/trade | Time in mkt | vs B&H CAGR | vs B&H DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | +5.84% | -6.98% | 0.37 | 30 | +63.33% | +0.85% | +0.92% | -2.50% | +48.20% |
| 2 | +5.95% | -9.24% | 0.37 | 27 | +77.78% | +0.98% | +1.80% | -2.39% | +45.95% |
| 3 | +5.30% | -11.18% | 0.23 | 26 | +61.54% | +0.73% | +2.60% | -3.03% | +44.01% |
| 5 | +4.93% | -11.18% | 0.17 | 25 | +60.00% | +0.59% | +4.11% | -3.41% | +44.01% |
| 10 | +4.86% | -14.12% | 0.14 | 24 | +58.33% | +0.69% | +7.75% | -3.47% | +41.07% |
| 21 | +4.92% | -17.17% | 0.14 | 22 | +63.64% | +0.97% | +15.44% | -3.42% | +38.02% |
| 63 | +5.33% | -42.94% | 0.16 | 16 | +68.75% | +2.85% | +37.80% | -3.01% | +12.25% |
| 126 | +5.48% | -51.48% | 0.17 | 9 | +77.78% | +6.77% | +58.71% | -2.85% | +3.71% |
| 252 | +8.47% | -55.19% | 0.33 | 5 | +80.00% | +22.58% | +79.56% | +0.13% | -0.00% |

### Signal: `combined`

| Hold (d) | CAGR | Max DD | Sharpe | # trades | Win % | Avg/trade | Time in mkt | vs B&H CAGR | vs B&H DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | +9.25% | -13.61% | 0.67 | 169 | +61.54% | +0.43% | +5.35% | +0.91% | +41.58% |
| 2 | +9.83% | -16.85% | 0.59 | 145 | +63.45% | +0.57% | +10.35% | +1.49% | +38.34% |
| 3 | +8.61% | -35.46% | 0.43 | 129 | +64.34% | +0.54% | +14.64% | +0.28% | +19.73% |
| 5 | +10.08% | -35.81% | 0.49 | 106 | +70.75% | +0.89% | +21.89% | +1.75% | +19.38% |
| 10 | +8.99% | -41.09% | 0.38 | 75 | +65.33% | +1.19% | +35.49% | +0.66% | +14.10% |
| 21 | +6.46% | -47.88% | 0.22 | 45 | +66.67% | +1.56% | +55.16% | -1.88% | +7.31% |
| 63 | +8.24% | -55.19% | 0.30 | 11 | +90.91% | +9.38% | +84.06% | -0.10% | +0.00% |
| 126 | +8.28% | -55.19% | 0.31 | 3 | +100.00% | +43.63% | +93.55% | -0.06% | -0.00% |
| 252 | +9.01% | -55.19% | 0.34 | 2 | +100.00% | +78.97% | +99.32% | +0.67% | +0.00% |

## Sweep — IS slice (2016-present)

_SPY B&H reference: CAGR +14.22%, Max DD -33.72%, Sharpe 0.62_

### Signal: `big_blue_day`

| Hold (d) | CAGR | Max DD | Sharpe | # trades | Win % | Avg/trade | Time in mkt | vs B&H CAGR | vs B&H DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | +7.03% | -9.33% | 0.53 | 74 | +56.76% | +0.43% | +3.04% | -7.19% | +24.38% |
| 2 | +7.63% | -14.43% | 0.51 | 69 | +72.46% | +0.57% | +5.92% | -6.59% | +19.29% |
| 3 | +7.93% | -24.77% | 0.43 | 65 | +67.69% | +0.73% | +8.61% | -6.30% | +8.94% |
| 5 | +8.54% | -31.05% | 0.42 | 53 | +71.70% | +0.98% | +13.52% | -5.69% | +2.67% |
| 10 | +10.49% | -30.44% | 0.52 | 44 | +72.73% | +1.70% | +23.19% | -3.73% | +3.27% |
| 21 | +9.46% | -33.72% | 0.42 | 28 | +75.00% | +2.56% | +39.01% | -4.76% | -0.00% |
| 63 | +11.97% | -33.72% | 0.53 | 11 | +90.91% | +9.93% | +68.16% | -2.26% | -0.00% |
| 126 | +12.71% | -33.72% | 0.55 | 5 | +100.00% | +27.11% | +86.01% | -1.51% | +0.00% |
| 252 | +14.35% | -33.72% | 0.62 | 1 | +100.00% | +292.52% | +99.88% | +0.13% | +0.00% |

### Signal: `capitulation`

| Hold (d) | CAGR | Max DD | Sharpe | # trades | Win % | Avg/trade | Time in mkt | vs B&H CAGR | vs B&H DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | +5.40% | -6.04% | 0.33 | 33 | +66.67% | +0.46% | +1.40% | -8.82% | +27.68% |
| 2 | +5.67% | -9.04% | 0.31 | 29 | +58.62% | +0.63% | +2.69% | -8.55% | +24.68% |
| 3 | +6.44% | -8.97% | 0.41 | 28 | +71.43% | +0.95% | +3.82% | -7.79% | +24.74% |
| 5 | +6.08% | -13.72% | 0.32 | 24 | +70.83% | +1.00% | +5.88% | -8.14% | +20.00% |
| 10 | +6.30% | -14.42% | 0.31 | 24 | +62.50% | +1.21% | +10.56% | -7.92% | +19.30% |
| 21 | +9.27% | -14.71% | 0.56 | 22 | +77.27% | +2.89% | +20.62% | -4.95% | +19.01% |
| 63 | +9.82% | -20.56% | 0.50 | 11 | +72.73% | +7.48% | +45.44% | -4.40% | +13.16% |
| 126 | +11.11% | -24.50% | 0.56 | 7 | +85.71% | +14.85% | +63.33% | -3.11% | +9.22% |
| 252 | +12.77% | -24.50% | 0.65 | 3 | +100.00% | +52.89% | +80.98% | -1.45% | +9.22% |

### Signal: `combined`

| Hold (d) | CAGR | Max DD | Sharpe | # trades | Win % | Avg/trade | Time in mkt | vs B&H CAGR | vs B&H DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | +8.48% | -9.33% | 0.62 | 105 | +60.00% | +0.45% | +4.44% | -5.74% | +24.38% |
| 2 | +9.45% | -14.43% | 0.61 | 91 | +70.33% | +0.64% | +8.53% | -4.77% | +19.29% |
| 3 | +9.94% | -24.77% | 0.57 | 85 | +71.76% | +0.80% | +12.08% | -4.28% | +8.94% |
| 5 | +9.51% | -31.05% | 0.46 | 68 | +70.59% | +0.94% | +18.36% | -4.71% | +2.67% |
| 10 | +12.68% | -30.44% | 0.63 | 55 | +74.55% | +1.78% | +30.40% | -1.54% | +3.27% |
| 21 | +14.27% | -33.72% | 0.68 | 34 | +82.35% | +3.55% | +50.70% | +0.05% | -0.00% |
| 63 | +12.93% | -33.72% | 0.56 | 9 | +88.89% | +14.59% | +81.84% | -1.29% | +0.00% |
| 126 | +13.22% | -33.72% | 0.57 | 4 | +100.00% | +40.74% | +93.76% | -1.00% | +0.00% |
| 252 | +14.35% | -33.72% | 0.62 | 1 | +100.00% | +292.52% | +99.88% | +0.13% | +0.00% |

## How to read the deltas

- `vs B&H CAGR` — strategy CAGR minus SPY B&H CAGR. Positive = strategy beat buy-and-hold on return.
- `vs B&H DD` — strategy max DD minus SPY B&H max DD. Both are negative numbers; **less-negative (higher) is better**. Positive `vs B&H DD` means the strategy had a *shallower* worst drawdown than SPY B&H.
- `Win %` = fraction of fires whose SPY return over the hold exceeded the T-bill compound return over the same window. Above 50% means the signal's forward returns beat cash on a per-fire basis.
- `Time in mkt` — what fraction of the period the strategy held SPY. Strategies that are short-duration (1-5d holds) sit in cash most of the time and earn rf there; their CAGR is dominated by T-bill drift.

## Sample-size caveats

- Strict-`<` and strict-`>` daily-return thresholds at 1% mean fire counts are small on a 23-year sample. Per-signal `# trades` is reported above — interpret long-hold rows with few trades cautiously; one outlier dominates the CAGR.
- Re-fires within a hold extend an existing trade rather than opening a new one, so `# trades` is conservative (independent entries).
- Win-rate compares a SPY return over a fixed hold against a T-bill compound over the same window. It does not reweight by trade size or sequence — equity-curve metrics (CAGR/DD/Sharpe) do.

## Reproducibility

```bash
cd backtests/spy_tlt_signals
python backtest.py
```

Re-run with `--rf-pct 4.5` to change the risk-free baseline, or `--hold-days N,N,...` to override the hold sweep. Outputs land in `results/` with today's date.

Per-trade ledger sits next to this file as `*_trades.csv` — one row per independent entry with entry/exit dates, prices, the SPY return realized over the hold, and the T-bill return that the same capital would have earned in cash. That's the audit trail.
