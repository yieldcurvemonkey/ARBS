"""What does the GSS book earn, per cost basis — and on which funding basis was that measured?

Two separate axes get conflated whenever this book is quoted, and both have to appear on every
number:

* **cost basis** — whose bid/offer table is charged. ``assumed`` is the transparent default that
  shipped with the port; ``measured`` is FedInvest's own quoted bid/offer priced to yield
  (:data:`BT.gss_fly.config.MEASURED_HALF_SPREAD_BP`, built by ``scripts/gss_measure_cost_table.py``);
  ``*_belly_only`` additionally restores the source's convention of charging the belly's bucket and
  letting both wings trade free.
* **funding basis** — whether a repo curve was supplied at all. There is no flat-rate fallback:
  ``CostConfig.fallback_repo_pct`` is declared and read by nothing. Without a workbook the book is
  **UNFINANCED** and every figure is gross of funding. That is not a footnote on a carry trade.

The four cost bases share ONE candidate scan (the cost table is a gate-layer knob and never feeds
back into which flies are considered), so this costs one scan plus four cheap replays rather than
four full runs::

    conda run -n stir python scripts/gss_cost_basis.py

Everything is reported with its standard error. SE(annualised Sharpe) = sqrt(252/n) is 0.87 on this
sample, so the differences between cost bases below are economically large and statistically
indistinguishable at the same time; the m* column is the one that carries information, because it
is a ratio of two sums rather than a mean over a noisy series.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.ERROR)

from BT.gss_fly import CostConfig, GSSConfig, build_curve_panel, resolve_repo_curve  # noqa: E402
from BT.gss_fly.backtest import run_gss_backtest  # noqa: E402
from BT.gss_fly.config import MEASURED_HALF_SPREAD_BP  # noqa: E402
from BT.gss_fly.data import ust_business_days  # noqa: E402
from BT.gss_fly.grid import series_metrics  # noqa: E402
from BT.gss_fly.signals import build_bond_signals  # noqa: E402
from BT.gss_fly.strategy import GSSSignalEngine, scan_candidates  # noqa: E402
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP  # noqa: E402

ASSUMED = CostConfig().half_spread_bp

ZERO = {k: 0.0 for k in ASSUMED}

BASES = [
    # The zero row is the sanity anchor: it says whether there is anything here BEFORE costs at all.
    # Its equity must equal `end_equity + fees` from every other row, because the trade set is
    # identical — that identity is asserted below rather than eyeballed.
    ("gross (no costs)", dict(half_spread_bp=ZERO, cost_legs="all")),
    ("assumed", dict(half_spread_bp=ASSUMED, cost_legs="all")),
    ("measured", dict(half_spread_bp=dict(MEASURED_HALF_SPREAD_BP), cost_legs="all")),
    ("assumed, belly-only", dict(half_spread_bp=ASSUMED, cost_legs="belly_only")),
    ("measured, belly-only", dict(half_spread_bp=dict(MEASURED_HALF_SPREAD_BP), cost_legs="belly_only")),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2024-09-02")
    ap.add_argument("--end", default="2026-01-02")
    ap.add_argument("--cache", default="notebooks/data/gss_fly/panel_cached")
    ap.add_argument("--repo-workbook", default=r"C:/Users/chris/Downloads/gc_repo_hist_example.xlsx")
    ap.add_argument("--out", default="notebooks/data/gss_fly/cost_basis.csv")
    args = ap.parse_args()

    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    days = ust_business_days(args.start, args.end)
    panel = build_curve_panel(days, mdp, cache_path=Path(args.cache), show_progress=False)
    print(f"COST: {panel.summary()}", flush=True)

    repo, basis = resolve_repo_curve(args.repo_workbook, announce=lambda m: print("COST: " + m, flush=True))

    # One scan for all four. The cost table is a gate-layer knob: it prices a decision that has
    # already been made, so the candidate set is identical across the four rows and the trade set
    # is too. That is what makes the comparison a clean re-pricing rather than four backtests.
    base_cfg = GSSConfig()
    t0 = time.time()
    sig = build_bond_signals(panel.s2c, base_cfg.signal)["signal"]
    cands = scan_candidates(GSSSignalEngine(panel, sig, base_cfg, repo_curve=repo), panel.dates)
    print(f"COST: scan {time.time() - t0:.0f}s, "
          f"{sum(len(v) for v in cands.values()):,} candidates", flush=True)

    rows = []
    for label, kw in BASES:
        cfg = GSSConfig(costs=CostConfig(**kw, repo_penalty_bp=base_cfg.costs.repo_penalty_bp))
        res = run_gss_backtest(panel, mdp, cfg=cfg, repo_curve=repo, show_progress=False,
                               strict=False, candidates=cands)
        sm = res.summary()
        daily = res.equity.dropna().astype(float).diff().dropna()
        met = series_metrics(daily.to_numpy())
        fees = abs(float(sm.get("fees_usd", np.nan)))
        eq = float(sm.get("end_equity_usd", np.nan))
        rows.append({
            "cost_basis": label,
            "funding_basis": basis,
            "trades": int(sm.get("closed_trades", 0) or 0),
            "fees_usd": -fees,
            "end_equity_usd": eq,
            # m* = gross / fees, recomputed from the engine endpoint (equity = gross - fees), not
            # from the component ledgers — the ledger form reads its open-mark term at the last
            # entry PRESENT rather than at the last date, which is stale for any config ending flat.
            "m_star": (eq + fees) / fees if fees else np.nan,
            "sharpe_ann": met["sharpe_ann"],
            "n_obs": met["n_obs"],
            "max_dd_usd": float(sm.get("max_dd_usd", np.nan)),
            "recon_gap_usd": float(sm.get("reconciliation_gap_usd", np.nan)),
            # the four ledger terms, so the decomposition is re-stated on the CURRENT code rather
            # than quoted from an older run. `financing_ledger_usd` is the tell for the funding
            # basis: it is exactly 0 when no repo curve was supplied, because `GSSEntryAction`
            # attaches the `financing` meta block only when `gc_rate is not None`.
            "carry_during_hold_usd": float(sm.get("carry_during_hold_usd", np.nan)),
            "unwind_proceeds_usd": float(sm.get("unwind_proceeds_usd", np.nan)),
            "open_mtm_usd": float(sm.get("open_mtm_usd", np.nan)),
            "bond_ledger_usd": float(sm.get("bond_ledger_usd", np.nan)),
            "financing_ledger_usd": float(sm.get("financing_ledger_usd", np.nan)),
        })
        print(f"COST: {label:24s} fees {-fees:>13,.0f}  equity {eq:>13,.0f}  "
              f"m* {rows[-1]['m_star']:.3f}  SR {met['sharpe_ann']:+.2f}", flush=True)

    t = pd.DataFrame(rows)
    se = float(np.sqrt(252.0 / max(t["n_obs"].median(), 1)))

    # The trade set must be IDENTICAL across the four rows; if it is not, this is no longer a
    # re-pricing and the fee comparison is confounded by a different book.
    assert t["trades"].nunique() == 1, f"cost basis changed the trade set: {t['trades'].tolist()}"
    assert t["recon_gap_usd"].abs().max() < 1e-3, t["recon_gap_usd"].tolist()

    # gross must be recoverable from every priced row: equity + fees is the same number in all of
    # them, and it must be the zero-cost row's equity. If it is not, the fee is feeding back into
    # the decision somewhere and this table is four backtests, not one re-pricing.
    gross_rows = (t["end_equity_usd"] + t["fees_usd"].abs())
    assert gross_rows.std() < 1.0, f"gross is not invariant across cost bases: {gross_rows.tolist()}"

    # The funding basis has an observable consequence, so check it rather than trusting the label:
    # with no repo curve the financing ledger must be exactly zero.
    fin = t["financing_ledger_usd"]
    if basis == "financed":
        assert fin.abs().max() > 0, "labelled financed but the financing ledger is empty"
    else:
        assert fin.abs().max() == 0, f"labelled UNFINANCED but financing booked {fin.tolist()}"

    print(f"\n=== GSS by cost basis — funding basis {basis} ===", flush=True)
    print(t.drop(columns=["n_obs", "recon_gap_usd", "bond_ledger_usd"]).to_string(
        index=False, float_format=lambda v: f"{v:,.3f}"), flush=True)
    print(f"\n  same {int(t['trades'].iloc[0])} trades in every row — the fee never feeds back "
          f"into the decision.", flush=True)
    print(f"  SE(annualised Sharpe) = sqrt(252/{int(t['n_obs'].median())}) = {se:.2f}; a DIFFERENCE "
          f"between two rows needs ~{se*np.sqrt(2)*2:.1f} to be significant.", flush=True)
    if basis != "financed":
        print("\n  >>> UNFINANCED: carry is NOT charged in any row above. On a book whose thesis is "
              "\n  >>> convergence financed in repo, these Sharpes are upper bounds, not estimates.",
              flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    t.to_csv(out, index=False)
    print(f"\nCOST: -> {out}\nCOSTDONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
