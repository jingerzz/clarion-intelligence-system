# backtests/

Auditable backtest reports for proposed signals before they enter the Clarion lib.

This directory exists so that empirical claims about a signal's value live next to the system that consumes them. Each subdirectory is one self-contained study: its own script, its own vendored input data (so reports stay reproducible without external repo dependencies), and a dated `results/` folder with the markdown report + per-trade CSV ledger.

## Studies

- **`spy_tlt_signals/`** — Validation of two Tier-1 candidate signals from `jingerzz/AI-trading-platform/packages/spy-tlt-strat` (`big_blue_day` and `capitulation`) against SPY buy-and-hold and all-T-bill baselines, sweeping holding periods 1d → 252d across full / OOS / IS period splits. Output: recommendation on whether and how to port these into Clarion's `regime/color.py` for Phase 2.

## Conventions

- **Scripts use only the Clarion `.venv`'s existing dependencies** (`pandas`, `numpy`) — no new lib additions.
- **Input data is vendored under `<study>/data/`**, copied from its upstream source at study creation time. The data CSV is part of the audit trail; the report's results are tied to that exact snapshot.
- **Outputs land in `<study>/results/YYYY-MM-DD_<slug>.md`** plus a paired `*_trades.csv` when applicable. The date in the filename is the date the script was run, not the as-of date of the data.
- **No live network calls** when the script runs. If the underlying data ever needs refreshing, that's an explicit `cp` step before re-running, recorded in the commit message.

## Adding a new study

1. Create `backtests/<study-name>/`
2. Vendor any input files under `data/`
3. Write the script, document the methodology in the report it produces
4. Run it; commit the script + `data/` + `results/` together so any reader can re-derive the numbers
