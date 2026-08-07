"""Shared plumbing for the SFR butterfly mean-reversion lab.

Deliberately a near-mirror of ``sfr_rv_lab_common.py`` -- same block names, same
header layout, same league-table schema, same verdict function -- so the two
labs are read and graded the same way. The differences are the ones the
instrument forces: a butterfly is a level series, so there is no mark book, no
strike selection and no staleness column; and it has *linear shadows*, so there
is a block the options lab does not have.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from RVUtils.MeanRev import (  # noqa: E402
    COST_SCENARIOS, MRConfig, MRResult, grid_search, leg_round_trip_bp,
    pivot_levels, run_backtest, shadow_levels, shadow_table,
)
from RVUtils.MeanRev.engine import DOLLARS_PER_BP  # noqa: E402
from RVUtils.SFRRVLab.stats import (  # noqa: E402
    cost_curve, deflated_for_grid, grid_distribution, neighbourhood_stability,
    nonoverlapping_sharpe, nw_tstat, verdict,
)

#: where the built panels live. ``set_output_dir`` moves the *results*; the
#: source parquets stay put, because there is only one panel.
PANEL_DIR = REPO / "notebooks" / "data" / "sfr_fly_meanrev"

DATA_DIR = REPO / "notebooks" / "data" / "sfr_fly_meanrev"
LEAGUE_CSV = DATA_DIR / "league_table.csv"
SIGN_CSV = DATA_DIR / "sign_tests.csv"
REGIME_CSV = DATA_DIR / "regime_splits.csv"
SHADOW_CSV = DATA_DIR / "shadow_tests.csv"

#: The round trip a league row is graded "taker" at, in bp on the package.
#: 2.5 is the prior lab's per-*leg* scenario and is kept as this module's default
#: so its published numbers are reproducible. The correct per-**contract** figure
#: for a 1/-2/1 fly is 2.0bp (4 contracts x 2 sides x 0.25bp) -- the kink lab sets
#: it, rather than this module silently changing under the older notebooks.
TAKER_BP = 2.5

#: Round trips shown in ``cost_block``'s cost curve.
COST_CURVE_BP = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 4.0)


def set_output_dir(path, *, taker_bp: Optional[float] = None,
                   cost_curve_bp: Optional[Sequence[float]] = None,
                   shadow_cost_mode: Optional[str] = None) -> None:
    """Point the reporting blocks at another lab's output directory.

    The blocks below read these as module globals at call time, so a sibling lab
    can reuse the identical header / grid / regime / shadow / league code without
    writing into this lab's CSVs. Nothing else about the blocks changes, which is
    the point -- two labs graded by different code are not comparable.
    """
    global DATA_DIR, LEAGUE_CSV, SIGN_CSV, REGIME_CSV, SHADOW_CSV
    global TAKER_BP, COST_CURVE_BP, SHADOW_COST_MODE
    DATA_DIR = Path(path)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LEAGUE_CSV = DATA_DIR / "league_table.csv"
    SIGN_CSV = DATA_DIR / "sign_tests.csv"
    REGIME_CSV = DATA_DIR / "regime_splits.csv"
    SHADOW_CSV = DATA_DIR / "shadow_tests.csv"
    if taker_bp is not None:
        TAKER_BP = float(taker_bp)
    if cost_curve_bp is not None:
        COST_CURVE_BP = tuple(float(c) for c in cost_curve_bp)
    if shadow_cost_mode is not None:
        SHADOW_COST_MODE = str(shadow_cost_mode)

#: The two honest sample windows, chosen from measured liquidity, not taste.
#: Slots 10-16 have 100% zero-volume days through 2020 and 50-63% in 2021; from
#: 2022 every slot trades every session. So the full 16-slot cross-section is
#: only real from 2022, while slots 1-8 are continuously liquid from 2019 --
#: and it is the 2019 start that buys ZIRP and the hiking cycle.
WINDOWS: Dict[str, dict] = {
    "liquid16": {"start": "2022-01-03", "end": None, "max_leg_slot": 16,
                 "why": "every strip slot trades every session from 2022"},
    "front8": {"start": "2019-01-02", "end": None, "max_leg_slot": 8,
               "why": "slots 1-8 are continuously liquid from 2019; buys ZIRP+hiking"},
    "full": {"start": None, "end": None, "max_leg_slot": 16,
             "why": "diagnostics only -- includes slots with no open interest"},
}

REGIME_ORDER = ["ZIRP", "HIKING", "PLATEAU", "CUTTING"]

#: Sessions dropped from every panel because the strip on them is not the strip.
#:
#: **2025-07-04** is US Independence Day, a market holiday, and it carries a panel
#: row built from **8 contracts -- H29 ... Z30, every one with zero open
#: interest**. The strip builder ranked those deep back months into slots 1-8, so
#: slot 1 is a four-year-forward contract: the front slot prints a -57bp jump in
#: and +58bp out, and every structure that day is mislabelled (`H29-M29-U29`
#: tagged `SFR123`). It is the only session in the file with fewer than 16
#: contracts. Reproduce with ``notebooks/rv/_probe_kink_bad_dates.py``.
#:
#: This was found after the 2026-07-29 fly mean-reversion findings were written,
#: so those numbers include the bad session -- one of 1,150 in `liquid16`.
BAD_DATES: Sequence[str] = ("2025-07-04",)


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load_lab(structure: str = "3m", window: str = "liquid16", *,
             data_dir: Optional[Path] = None, min_oi: float = 0.0,
             min_days_to_front_start: int = 0,
             drop_dates: Sequence[str] = BAD_DATES) -> Dict[str, object]:
    """Load one structure family over one window, with its shadows and gate.

    ``data_dir`` defaults to the **source panel** directory, which is where the
    built parquets live regardless of where a lab writes its results.
    """
    data_dir = Path(data_dir) if data_dir is not None else PANEL_DIR
    if window not in WINDOWS:
        raise ValueError(f"window must be one of {sorted(WINDOWS)}")
    w = WINDOWS[window]
    st = pd.read_parquet(data_dir / f"structures_{structure}.parquet")
    st["as_of"] = pd.to_datetime(st["as_of"])
    if drop_dates:
        bad = pd.DatetimeIndex(pd.to_datetime(list(drop_dates)))
        st = st[~st["as_of"].isin(bad)]
    if w["start"]:
        st = st[st["as_of"] >= pd.Timestamp(w["start"])]
    if w["end"]:
        st = st[st["as_of"] <= pd.Timestamp(w["end"])]
    st = st[st["back_slot"] <= int(w["max_leg_slot"])]
    st = st.sort_values(["as_of", "cm_slot"]).reset_index(drop=True)

    levels = pivot_levels(st)
    shadows = shadow_levels(st)
    slot_panel = pd.read_parquet(data_dir / "slot_panel.parquet")
    slot_panel.index = pd.to_datetime(slot_panel.index)
    slot_panel = slot_panel.loc[levels.index.min():levels.index.max()]
    slot_panel = slot_panel.reindex(levels.index)
    slot_panel.columns = [int(c) for c in slot_panel.columns]

    ok = pd.Series(True, index=st.index)
    if min_oi > 0:
        ok &= st["min_open_interest"].fillna(0.0) >= float(min_oi)
    if min_days_to_front_start > 0:
        ok &= st["days_to_front_start"].fillna(0) >= int(min_days_to_front_start)
    g = st.assign(_g=ok.to_numpy()).pivot_table(
        index="as_of", columns="key", values="_g", aggfunc="first")
    gate = (g.reindex(index=levels.index, columns=levels.columns)
            .astype(float).fillna(0.0) > 0.5)

    regimes = (st.drop_duplicates("as_of").set_index("as_of")["regime"]
               .reindex(levels.index).ffill())

    # A key's constant-maturity slot ROLLS: a fly born at slot 15 arrives at
    # slot 2 four years later. One label per key is therefore wrong (it would
    # tag every key with the slot it was born at), so CM lives in two places:
    #   cm_at      -- date x key labels, for attributing a trade by ENTRY date
    #   cm_levels  -- date x cm_label, a roll-adjusted constant-maturity series
    # cm_levels is for REPORTING only. It splices different contracts every
    # quarter, which is exactly why no backtest runs on it.
    cm_at = st.pivot_table(index="as_of", columns="key", values="cm_label_short",
                           aggfunc="first").reindex(index=levels.index,
                                                    columns=levels.columns)
    cm_slot_at = st.pivot_table(index="as_of", columns="key", values="cm_slot",
                                aggfunc="first").reindex(index=levels.index,
                                                         columns=levels.columns)
    cm_levels = st.pivot_table(index="as_of", columns="cm_label_short",
                               values="value", aggfunc="first").sort_index()
    slot_of_label = st.drop_duplicates("cm_label_short").set_index(
        "cm_label_short")["cm_slot"]
    cm_levels = cm_levels[slot_of_label.reindex(cm_levels.columns).sort_values().index]
    return {
        "struct": st, "levels": levels, "shadows": shadows, "gate": gate,
        "slot_panel": slot_panel, "regimes": regimes,
        "cm_at": cm_at, "cm_slot_at": cm_slot_at, "cm_levels": cm_levels,
        "slot_of_label": slot_of_label,
        "structure": structure, "window": window, "window_why": w["why"],
    }


def attach_cm(trades: pd.DataFrame, lab: Dict[str, object]) -> pd.DataFrame:
    """Tag each trade with the CM slot its key occupied **on the entry date**."""
    out = trades.copy()
    if out.empty:
        return out
    cm_at, slot_at = lab["cm_at"], lab["cm_slot_at"]
    labels, slots = [], []
    for _, r in out.iterrows():
        d, k = pd.Timestamp(r["entry"]), r["key"]
        try:
            labels.append(cm_at.at[d, k])
            slots.append(slot_at.at[d, k])
        except KeyError:
            labels.append(None)
            slots.append(np.nan)
    out["cm"] = labels
    out["slot"] = slots
    return out


def per_slot_table(res: MRResult, lab: Dict[str, object]) -> pd.DataFrame:
    """Net P&L by the CM slot each trade was entered in."""
    tr = attach_cm(res.trades, lab)
    if tr.empty:
        return pd.DataFrame()
    per = (tr.groupby(["slot", "cm"])
           .agg(n=("net_bp", "size"), hit=("net_bp", lambda s: (s > 0).mean()),
                avg_net_bp=("net_bp", "mean"), total_net_bp=("net_bp", "sum"),
                total_gross_bp=("gross_bp", "sum"), avg_hold=("days", "mean"))
           .reset_index().sort_values("slot"))
    per["total_net_usd"] = per["total_net_bp"] * DOLLARS_PER_BP * res.config.n_packages
    return per


def coverage_report(lab: Dict[str, object]) -> pd.DataFrame:
    st = lab["struct"]
    g = st.groupby("cm_label_short")
    out = pd.DataFrame({
        "cm_slot": g["cm_slot"].first(),
        "pack": g["pack"].first(),
        "n_obs": g.size(),
        "n_keys": g["key"].nunique(),
        "median_bp": g["value"].median(),
        "iqr_bp": g["value"].quantile(0.75) - g["value"].quantile(0.25),
        "daily_sd_bp": st.sort_values(["key", "as_of"]).assign(
            d=lambda x: x.groupby("key")["value"].diff()).groupby("cm_label_short")["d"].std(),
        "median_min_oi": g["min_open_interest"].median(),
    }).sort_values("cm_slot")
    return out


# ---------------------------------------------------------------------------
# reporting blocks (same names/layout as the options lab)
# ---------------------------------------------------------------------------

def header_block(name: str, res: MRResult, *, grid: Optional[pd.DataFrame] = None,
                 note: str = "") -> Dict[str, float]:
    """The standard stats header. Returns the dict it printed."""
    m = dict(res.metrics)
    m["nonoverlap_sharpe"] = (nonoverlapping_sharpe(res.trades)
                              if not res.trades.empty else np.nan)
    m["nw_t"] = nw_tstat(res.daily_bp.to_numpy(), lags=5) if len(res.daily_bp) else np.nan
    if grid is not None and not res.daily_bp.empty:
        d = deflated_for_grid(res.daily_bp, grid)
        m["dsr_prob"] = d.get("dsr_prob", np.nan)
        m["n_trials"] = d.get("n_trials", np.nan)
    print("=" * 92)
    print(f"{name}  |  {res.config.label()}  |  {res.config.n_packages} packages "
          f"(${DOLLARS_PER_BP * res.config.n_packages:,.0f}/bp, "
          f"{4 * res.config.n_packages:,} contracts)")
    if note:
        print(f"  {note}")
    print("=" * 92)
    if m["n_trades"] == 0:
        print("  no trades")
        return m
    print(f"  trades {m['n_trades']:>5d}   skipped {m.get('n_skipped', 0):>4d}   "
          f"hit {m['hit_rate']:.0%}   avg {m['avg_net_bp']:+.3f}bp   "
          f"avg hold {m['avg_hold_days']:.1f}d")
    print(f"  total  {m['total_net_bp']:+9.2f}bp   ${m['total_net_usd']:>+13,.0f}   "
          f"gross {m.get('total_gross_bp', float('nan')):+.2f}bp")
    print(f"  daily-MTM Sharpe {m['sharpe']:+.2f}   maxDD {m['max_dd_bp']:+.2f}bp "
          f"(${m['max_dd_usd']:+,.0f})   worst trade {m['worst_bp']:+.2f}bp")
    print(f"  t(trade) {m['t_stat']:+.2f}   NW t(daily) {m['nw_t']:+.2f}   "
          f"non-overlap SR {m['nonoverlap_sharpe']:+.2f}", end="")
    if "dsr_prob" in m:
        print(f"   DSR p={m['dsr_prob']:.3f} over {m['n_trials']} trials")
    else:
        print()
    return m


def three_panel_equity(res: MRResult, title: str):
    """bp equity | dollar equity | drawdown, the house layout."""
    import matplotlib.pyplot as plt
    if res.daily_bp.empty:
        print(f"  (no P&L to plot for {title})")
        return None
    cum = res.daily_bp.cumsum()
    usd = res.daily_usd.cumsum()
    dd = cum - cum.cummax()
    fig, axes = plt.subplots(1, 3, figsize=(16, 3.8))
    axes[0].plot(cum.index, cum.to_numpy(), lw=1.4, color="#1f4e79")
    axes[0].set_title(f"{title}\ncumulative net P&L (bp)", fontsize=10)
    axes[0].axhline(0, color="grey", lw=0.6)
    axes[1].plot(usd.index, usd.to_numpy(), lw=1.4, color="#2e7d32")
    axes[1].set_title(f"cumulative net P&L ($, {res.config.n_packages} packages)",
                      fontsize=10)
    axes[1].axhline(0, color="grey", lw=0.6)
    axes[2].fill_between(dd.index, dd.to_numpy(), 0, color="#c62828", alpha=0.35)
    axes[2].set_title("drawdown (bp)", fontsize=10)
    for a in axes:
        a.grid(alpha=0.25)
        a.tick_params(labelsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def grid_block(grid: pd.DataFrame, params: Sequence[str], *,
               metric: str = "total_net_bp", top: int = 8) -> pd.Series:
    """Distribution first, top rows second. The top row is never the verdict."""
    d = grid_distribution(grid, metric)
    print(f"  {d['n_configs']} configs | median {d['median']:+.2f}bp | "
          f"IQR [{d['q25']:+.2f}, {d['q75']:+.2f}] | "
          f"{d['pct_positive']:.0%} net-positive | best {d['best']:+.2f}bp")
    show = [c for c in list(params) + ["n_trades", "hit_rate", "avg_net_bp",
                                       "total_net_bp", "total_net_usd", "sharpe",
                                       "max_dd_bp"] if c in grid.columns]
    print("\n  top rows (SELECTION-INFLATED - read the distribution above first):")
    print(grid.sort_values(metric, ascending=False).head(top)[show]
          .round(3).to_string(index=False))
    print("\n  median net bp per parameter value:")
    for p in params:
        if p in grid.columns:
            print(f"    {p}: {grid.groupby(p)[metric].median().round(2).to_dict()}")
    return grid.loc[grid[metric].idxmax()]


def median_row(grid: pd.DataFrame, metric: str = "total_net_bp") -> pd.Series:
    """The grid row closest to the sweep's median - the un-cherry-picked config."""
    i = (grid[metric] - grid[metric].median()).abs().idxmin()
    return grid.loc[i]


def config_from_row(base: MRConfig, row: pd.Series, params: Sequence[str]) -> MRConfig:
    fields = {f.name for f in dataclasses.fields(MRConfig)}
    kw = {}
    for p in params:
        if p in row.index and p in fields:
            v = row[p]
            if isinstance(v, np.integer):
                v = int(v)
            elif isinstance(v, np.floating):
                v = float(v)
            kw[p] = v
    return dataclasses.replace(base, **kw)


def signal_params_from_row(row: pd.Series, params: Sequence[str]) -> dict:
    """The non-MRConfig half of a grid row (lookbacks, smoothing, ...)."""
    fields = {f.name for f in dataclasses.fields(MRConfig)}
    out = {}
    for p in params:
        if p in row.index and p not in fields:
            v = row[p]
            if isinstance(v, np.integer):
                v = int(v)
            elif isinstance(v, np.floating):
                v = float(v)
            out[p] = v
    return out


def stability_block(grid: pd.DataFrame, best: pd.Series, params: Sequence[str],
                    *, metric: str = "total_net_bp") -> pd.DataFrame:
    nb = neighbourhood_stability(grid, best, [p for p in params if p in grid.columns],
                                 metric=metric)
    print("\n  neighbourhood (one parameter moved at a time):")
    for p, sub in nb.groupby("param"):
        vals = ", ".join(f"{v}{'*' if b else ''}={x:+.2f}"
                         for v, x, b in zip(sub["value"], sub[metric], sub["is_best"]))
        print(f"    {p}: {vals}")
    return nb


def cost_block(res: MRResult) -> pd.DataFrame:
    if res.trades.empty:
        return pd.DataFrame()
    cc = cost_curve(res.trades, list(COST_CURVE_BP))
    cc["total_net_usd"] = cc["total_net_bp"] * DOLLARS_PER_BP * res.config.n_packages
    print("\n  cost curve (round-trip bp charged on the package):")
    print(cc.round(3).to_string(index=False))
    return cc


def exit_comparison(base: MRConfig, *, levels, signal, gate=None,
                    exits: Sequence[str] = ("z0", "half", "band", "t5", "t10", "t20")
                    ) -> pd.DataFrame:
    rows = []
    for ex in exits:
        cfg = dataclasses.replace(base, exit_style=ex)
        r = run_backtest(cfg, levels=levels, signal=signal, gate=gate)
        m = r.metrics
        rows.append({"exit": ex, "n_trades": m["n_trades"],
                     "avg_hold": m["avg_hold_days"], "hit_rate": m["hit_rate"],
                     "avg_net_bp": m["avg_net_bp"],
                     "total_net_bp": m["total_net_bp"], "sharpe": m["sharpe"]})
    return pd.DataFrame(rows)


def sign_test(grid: pd.DataFrame, metric: str = "total_net_bp", *,
              framework: str = "", write: bool = True) -> pd.DataFrame:
    """Fade vs momentum across the whole sweep - the house rule, never assumed."""
    if "direction" not in grid.columns:
        return pd.DataFrame()
    out = (grid.groupby("direction")
           .agg(n_configs=(metric, "size"), median_net_bp=(metric, "median"),
                pct_positive=(metric, lambda s: (s > 0).mean()),
                best_net_bp=(metric, "max"), median_trades=("n_trades", "median"))
           .round(3))
    print("\nSIGN TEST (both directions, whole sweep)")
    print(out.to_string())
    if write and framework:
        row = out.reset_index()
        row.insert(0, "framework", framework)
        row["winning_sign"] = out["median_net_bp"].idxmax()
        SIGN_CSV.parent.mkdir(parents=True, exist_ok=True)
        if SIGN_CSV.exists():
            old = pd.read_csv(SIGN_CSV)
            old = old[old["framework"] != framework]
            row = pd.concat([old, row], ignore_index=True)
        row.to_csv(SIGN_CSV, index=False)
    return out


def regime_block(res: MRResult, regimes: pd.Series, *, framework: str = "",
                 write: bool = True) -> pd.DataFrame:
    """Split one config's realised P&L by policy regime.

    Trades are attributed to the regime of their ENTRY date; the daily series is
    attributed bar by bar, so a trade spanning a regime boundary contributes to
    both in the daily columns and to one in the trade columns.
    """
    if res.trades.empty:
        return pd.DataFrame()
    tr = res.trades.copy()
    tr["regime"] = regimes.reindex(pd.DatetimeIndex(tr["entry"])).to_numpy()
    daily = res.daily_bp.copy()
    dreg = regimes.reindex(daily.index).ffill()
    rows = []
    for r in REGIME_ORDER:
        t = tr[tr["regime"] == r]
        d = daily[dreg == r]
        sd = d.std(ddof=1) if len(d) > 2 else np.nan
        rows.append({
            "regime": r, "n_trades": len(t), "n_days": len(d),
            "hit_rate": float((t["net_bp"] > 0).mean()) if len(t) else np.nan,
            "avg_net_bp": float(t["net_bp"].mean()) if len(t) else np.nan,
            "total_net_bp": float(t["net_bp"].sum()) if len(t) else 0.0,
            "total_net_usd": (float(t["net_bp"].sum()) * DOLLARS_PER_BP
                              * res.config.n_packages) if len(t) else 0.0,
            "daily_sharpe": (float(d.mean() / sd * np.sqrt(252))
                             if np.isfinite(sd) and sd > 0 else np.nan),
        })
    out = pd.DataFrame(rows)
    print("\nREGIME SPLIT (a single six-year parameter set is the thing being tested)")
    print(out.round(3).to_string(index=False))
    if write and framework:
        o = out.copy()
        o.insert(0, "framework", framework)
        REGIME_CSV.parent.mkdir(parents=True, exist_ok=True)
        if REGIME_CSV.exists():
            old = pd.read_csv(REGIME_CSV)
            old = old[old["framework"] != framework]
            o = pd.concat([old, o], ignore_index=True)
        o.to_csv(REGIME_CSV, index=False)
    return out


#: how ``shadow_block`` charges each shadow instrument. ``per_leg`` reproduces
#: the prior lab; ``per_contract`` is correct for futures and is what
#: ``set_output_dir`` switches the kink lab to. They differ only on the
#: butterfly (4 contracts, 2.0bp -- not 3 legs, 1.5bp), and per-leg costing
#: therefore gives the fly a 0.5bp/trade head start over its own shadows.
SHADOW_COST_MODE = "per_leg"


def shadow_block(signal: pd.DataFrame, lab: Dict[str, object], base: MRConfig, *,
                 framework: str = "", write: bool = True) -> pd.DataFrame:
    """Run the identical signal on the fly's linear shadows.

    fly = (belly - front) + (belly - back), so if the edge is really a calendar
    or a directional trade it shows up on an instrument that costs fewer legs.
    """
    tbl = shadow_table(signal, lab["shadows"], base=base, gate=lab["gate"],
                       cost_mode=SHADOW_COST_MODE)
    print("\nLINEAR-SHADOW DECOMPOSITION (same signal, simpler instrument, own cost)")
    print(tbl.round(3).to_string(index=False))
    print(f"  -> {tbl.attrs.get('verdict', 'n/a')}")
    if write and framework:
        o = tbl.copy()
        o.insert(0, "framework", framework)
        SHADOW_CSV.parent.mkdir(parents=True, exist_ok=True)
        if SHADOW_CSV.exists():
            old = pd.read_csv(SHADOW_CSV)
            old = old[old["framework"] != framework]
            o = pd.concat([old, o], ignore_index=True)
        o.to_csv(SHADOW_CSV, index=False)
    return tbl


def league_row(framework: str, variant: str, res: MRResult, *,
               grid: Optional[pd.DataFrame], cls: str, note: str = "",
               window: str = "", structure: str = "", write: bool = True
               ) -> Dict[str, object]:
    """Build (and upsert) one league-table row with the uniform verdict."""
    m = dict(res.metrics)
    taker_bp = float(TAKER_BP)
    cc = (cost_curve(res.trades, [0.0, taker_bp]).set_index("round_trip_bp")
          if not res.trades.empty else None)
    maker = float(cc.loc[0.0, "total_net_bp"]) if cc is not None else 0.0
    taker = float(cc.loc[taker_bp, "total_net_bp"]) if cc is not None else 0.0
    dsr = (deflated_for_grid(res.daily_bp, grid).get("dsr_prob", np.nan)
           if grid is not None and len(grid) and not res.daily_bp.empty else np.nan)
    median_net = (float(grid["total_net_bp"].median())
                  if grid is not None and len(grid) else np.nan)
    row = {
        "framework": framework, "variant": variant, "class": cls,
        "structure": structure, "window": window, "config": res.config.label(),
        "n_trades": m["n_trades"], "hit_rate": m["hit_rate"],
        "avg_net_bp": m["avg_net_bp"],
        "total_gross_bp": m.get("total_gross_bp", np.nan),
        "total_net_bp": m["total_net_bp"], "total_net_usd": m["total_net_usd"],
        "net_bp_maker": maker, "net_bp_taker": taker, "taker_bp": taker_bp,
        "net_usd_taker": taker * DOLLARS_PER_BP * res.config.n_packages,
        "sharpe": m["sharpe"], "max_dd_bp": m["max_dd_bp"],
        "max_dd_usd": m["max_dd_usd"], "avg_hold_days": m["avg_hold_days"],
        "dsr_prob": dsr, "grid_median_net_bp": median_net,
        "nonoverlap_sharpe": (nonoverlapping_sharpe(res.trades)
                              if not res.trades.empty else np.nan),
        "verdict": verdict(net_bp_at_taker=taker, net_bp_at_maker=maker,
                           dsr_prob=dsr if np.isfinite(dsr) else 0.0,
                           median_net_bp=median_net if np.isfinite(median_net) else -1.0,
                           n_trades=m["n_trades"]),
        "note": note,
    }
    if write:
        LEAGUE_CSV.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([row])
        if LEAGUE_CSV.exists():
            old = pd.read_csv(LEAGUE_CSV)
            old = old[~((old["framework"] == framework) & (old["variant"] == variant))]
            df = pd.concat([old, df], ignore_index=True)
        df.to_csv(LEAGUE_CSV, index=False)
    print(f"\n  LEAGUE ROW  {framework} / {variant}: {row['verdict']}  "
          f"(taker {taker:+.2f}bp, maker {maker:+.2f}bp, "
          f"DSR p={dsr if np.isfinite(dsr) else float('nan'):.3f})")
    return row


# ---------------------------------------------------------------------------
# the compressed path
# ---------------------------------------------------------------------------

def run_family(
    name: str, *, lab: Dict[str, object], signal_fn, grid_spec: Dict[str, Sequence],
    params: Sequence[str], base: MRConfig, cls: str, note: str = "",
    plot: bool = True, league: bool = True, show_trades: int = 25,
    exits: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    """grid -> distribution -> stability -> sign -> best -> equity -> trades ->
    exits -> costs -> regimes -> shadows -> median config -> league rows.

    ``signal_fn(levels, **signal_params)`` is called with whichever grid keys are
    not :class:`MRConfig` fields; identical signal parameters are computed once.
    """
    import matplotlib.pyplot as plt

    levels, gate = lab["levels"], lab["gate"]
    print(f"\n### GRID  ({len(levels.columns)} keys, {len(levels)} sessions, "
          f"window={lab['window']}: {lab['window_why']})")
    grid = grid_search(grid_spec, levels=levels, signal=None, gate=gate,
                       base=base, signal_fn=signal_fn, show_progress=True)
    best = grid_block(grid, params)
    stability_block(grid, best, params)
    sign_test(grid, framework=name)

    sig_best = signal_fn(levels, **signal_params_from_row(best, params))
    cfg_best = config_from_row(base, best, params)
    res = run_backtest(cfg_best, levels=levels, signal=sig_best, gate=gate)
    header_block(f"{name} - best config", res, grid=grid, note=note)
    if plot:
        three_panel_equity(res, f"{name} - best config")
        plt.show()
    if not res.trades.empty:
        print("\n  trade log (first rows):")
        print(res.trades.sort_values("entry").head(show_trades).to_string(index=False))
    print("\n  exit comparison:")
    ex_kw = {} if exits is None else {"exits": tuple(exits)}
    print(exit_comparison(cfg_best, levels=levels, signal=sig_best, gate=gate,
                          **ex_kw).round(3).to_string(index=False))
    cost_block(res)
    regime_block(res, lab["regimes"], framework=name)
    shadow_block(sig_best, lab, cfg_best, framework=name)

    med = median_row(grid)
    sig_med = signal_fn(levels, **signal_params_from_row(med, params))
    res_med = run_backtest(config_from_row(base, med, params), levels=levels,
                           signal=sig_med, gate=gate)
    header_block(f"{name} - MEDIAN config (the anti-selection control)", res_med,
                 grid=grid)

    if league:
        league_row(name, "best-config", res, grid=grid, cls=cls, note=note,
                   window=str(lab["window"]), structure=str(lab["structure"]))
        league_row(name, "median-config", res_med, grid=grid, cls=cls,
                   note="median of the sweep, not selected",
                   window=str(lab["window"]), structure=str(lab["structure"]))
    return {"grid": grid, "best": best, "config": cfg_best, "result": res,
            "median_result": res_med, "signal": sig_best}
