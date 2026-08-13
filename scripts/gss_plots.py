"""Render the GSS book with :mod:`RVUtils.BookViz`, on real data.

A visualisation module exercised only against synthetic fixtures is not verified — the fixtures
were written by the same hand as the code and share its assumptions. This runs the real book
through it and writes standalone HTML.

It is also the check that the dashboard tells the truth about *this* book. The equity curve here
is the engine's marked series and the trade sum is +7.9m against a book that made +431k, so the
figure must show two clearly different lines. If they overlay, the dashboard is re-deriving the
curve from the ledger and the whole point has been lost.

    conda run -n stir python scripts/gss_plots.py --out notebooks/data/gss_fly/plots
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.ERROR)

from BT.gss_fly import CostConfig, FlyConfig, GSSConfig, build_curve_panel, resolve_repo_curve  # noqa: E402
from BT.gss_fly.backtest import run_gss_backtest  # noqa: E402
from BT.gss_fly.data import ust_business_days  # noqa: E402
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP  # noqa: E402
from RVUtils.BookViz import BookSpec, book_dashboard, compare_books  # noqa: E402

VARIANTS = {
    "default (all legs)": lambda: GSSConfig(),
    "belly-only costs": lambda: GSSConfig(costs=CostConfig(cost_legs="belly_only")),
    "legacy wing objective": lambda: GSSConfig(fly=FlyConfig(wing_objective="legacy_ttm_bug")),
}

#: dollars, and the closed log's own column names
SPEC = BookSpec(unit="USD", precision=0, pnl="realized_pnl", time="closed_at",
                label="fly_id", hold="holding_period_days",
                extra_hover=("gross_realized_pnl", "fee_allocated"))


def _components(res) -> dict:
    """The four disjoint terms as cumulative series, for the component panel."""
    hist = getattr(res.backtest, "frb_component_histories", None) or {}
    out = {}
    for key, label in (("bond_realized", "bond (coupons + convergence)"),
                       ("financing_realized", "financing"),
                       ("bond_open_mtm", "open mark")):
        h = hist.get(key) or {}
        if h:
            s = pd.Series(h).sort_index()
            s.index = pd.to_datetime(s.index)
            out[label] = s
    if not res.closed.empty and "fee_allocated" in res.closed.columns:
        f = res.closed.copy()
        f["closed_at"] = pd.to_datetime(f["closed_at"])
        out["fees (cumulative)"] = -f.set_index("closed_at")["fee_allocated"].astype(float).sort_index().cumsum()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2024-09-02")
    ap.add_argument("--end", default="2026-01-02")
    ap.add_argument("--cache", default="notebooks/data/gss_fly/panel_cached")
    ap.add_argument("--out", default="notebooks/data/gss_fly/plots")
    ap.add_argument("--repo-workbook", default=r"C:/Users/chris/Downloads/gc_repo_hist_example.xlsx")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    days = ust_business_days(args.start, args.end)
    panel = build_curve_panel(days, mdp, cache_path=Path(args.cache), show_progress=False)
    print(f"PLOT: {panel.summary()}", flush=True)

    # The basis goes in every FIGURE TITLE, not only the log. A chart is what gets screenshotted,
    # and it travels without the log that would have said how it was funded.
    repo, basis = resolve_repo_curve(args.repo_workbook, announce=lambda m: print("PLOT: " + m, flush=True))

    span = (pd.Timestamp(args.end) - pd.Timestamp(args.start)).days / 365.25
    curves = {}
    for name, make in VARIANTS.items():
        res = run_gss_backtest(panel, mdp, cfg=make(), repo_curve=repo,
                               show_progress=False, strict=False)
        sm = res.summary()
        fig = book_dashboard(
            res.closed, title=f"GSS butterfly — {name} [{basis}]", spec=SPEC,
            equity=res.equity, components=_components(res), span_years=span, height=1180,
        )
        slug = name.split(" (")[0].replace(" ", "_")
        p = out / f"gss_{slug}.html"
        fig.write_html(p, include_plotlyjs="cdn")
        curves[name] = res.equity

        # the property the dashboard exists to make visible
        traces = {getattr(t, "name", None) for t in fig.data}
        assert "marked equity" in traces and "Σ trades" in traces, traces
        print(f"PLOT: {name}: equity={sm['end_equity_usd']:,.0f} "
              f"Σtrades={sm['per_trade_pnl_usd']:,.0f} "
              f"gap={sm['reconciliation_gap_usd']:,.2f} -> {p}", flush=True)

    cmp_fig = compare_books(curves, title=f"GSS variants — marked equity [{basis}]", unit="USD", height=620)
    p = out / "gss_variants.html"
    cmp_fig.write_html(p, include_plotlyjs="cdn")
    print(f"PLOT: comparison -> {p}", flush=True)
    print("PLOTDONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
