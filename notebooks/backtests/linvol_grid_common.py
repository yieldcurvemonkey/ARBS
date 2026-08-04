"""Shared data, engines and placebos for the linear-vs-vol backtest grid.

Everything marks from LISTED premiums (the quotes panel); the tree side comes
from the frozen meeting-prob panels (strict ZQ-null digitals). No spline, no
BL, no model marks anywhere in PnL. Costs are per contract per side:
SR3 option half-tick 0.125bp, SR3/ZQ futures half-tick 0.25bp.

Claim convention: every option structure is expressed through the CLAIM
``P(rate > boundary)`` priced in premium bp as ``prob * width``. For put
verticals that is the spread premium itself; for call verticals it is
``width - spread`` — a constant that drops out of every PnL difference, so
marks are additive and the REAL contract count (for costs) is tracked
separately.
"""
from __future__ import annotations

import dataclasses
import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data" / "meeting_prob"
MAIN = Path("C:/Users/chris/clee/ARBS/notebooks/data/sfr_rv_lab")
OUT = HERE.parent / "data" / "linvol_grid"

OPT_HALF_TICK_BP = 0.125
FUT_HALF_TICK_BP = 0.25


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

def load_panels() -> dict:
    mon = pd.read_parquet(DATA / "monitor.parquet")
    bd = pd.read_parquet(DATA / "boundaries.parquet")
    gate = pd.read_parquet(DATA / "tieout_gate.parquet")
    quotes = pd.read_parquet(MAIN / "quotes.parquet")
    contracts = pd.read_parquet(MAIN / "contracts.parquet")
    for f in (mon, bd, gate, quotes, contracts):
        f["as_of"] = pd.to_datetime(f["as_of"])
    return dict(
        mon=mon, bd=bd, gate=gate, quotes=quotes, contracts=contracts,
        q_idx=quotes.set_index(["symbol", "right", "strike_price", "as_of"])[
            "premium_bp"].sort_index(),
        fwd_idx=contracts.set_index(["as_of", "symbol"])["forward_rate"],
        all_dates=pd.DatetimeIndex(sorted(mon["as_of"].unique())),
    )


def build_ladders(mon: pd.DataFrame):
    """Daily ZQ ladders + long jumps frame (signal AND hedge object)."""
    from RVUtils.MeetingProb import meeting_ladder, zq_settle_panel
    from SDRUtils.analytics.fomc import load_fomc_schedule

    zq = zq_settle_panel(
        [f"ZQ{c}{y}" for y in (23, 24, 25, 26, 27) for c in "FGHJKMNQUVXZ"])
    fomc = load_fomc_schedule("USD-SOFR-1D")
    dates = sorted(mon["as_of"].dt.date.unique())
    ladders = {d: meeting_ladder(d, zq, fomc) for d in dates}
    jumps = pd.DataFrame(
        [{"as_of": pd.Timestamp(d), "effective": m.effective,
          "jump_bp": m.jump_bp}
         for d, lad in ladders.items() for m in lad])
    return ladders, jumps


# ---------------------------------------------------------------------------
# Signal frames (family A) — boundary classes over the full boundary panel
# ---------------------------------------------------------------------------

def _classify_boundaries(g: pd.DataFrame) -> pd.DataFrame:
    """Per (as_of, symbol): tag each boundary outer / mode_flank / largest."""
    g = g.sort_values("boundary_rate").reset_index(drop=True)
    n = len(g)
    g["is_outer"] = False
    g.loc[[0, n - 1], "is_outer"] = True
    # bucket masses between adjacent boundaries; digitals fall as rate rises
    if n > 1:
        mass = (g["p_tree"].to_numpy()[:-1] - g["p_tree"].to_numpy()[1:])
        k = int(np.argmax(mass))
        flanks = {k, k + 1}
    else:
        flanks = {0}
    g["is_mode_flank"] = [i in flanks for i in range(n)]
    g["is_largest"] = False
    g.loc[g["gap"].abs().idxmax(), "is_largest"] = True
    return g


def boundary_signal_frame(panels: dict) -> pd.DataFrame:
    """Every boundary row, classified and merged with monitor + day gate."""
    bd, mon, gate = panels["bd"], panels["mon"], panels["gate"]
    cls = (bd.drop(columns=["saturated"], errors="ignore")
           .groupby(["as_of", "symbol"], group_keys=False)
           .apply(_classify_boundaries))
    sig = cls.merge(
        mon[["as_of", "symbol", "channel", "saturated", "any_stale",
             "days_to_expiry", "n_resolved"]],
        on=["as_of", "symbol"], how="inner",
    ).merge(gate.rename(columns={"any_stale": "zq_stale_day"}),
            on="as_of", how="left")
    sig["gate"] = (sig["tieout_ok"].fillna(False) & ~sig["saturated"]
                   & ~sig["any_stale"])
    sig["gap_t"] = 99.0            # per-boundary tstats not available; gates
    return sig                     # + thresholds carry identification here
                                   # (finite: the engine skips non-finite t)


def select_boundaries(sig: pd.DataFrame, *, boundary_class: str,
                      dte_lo: int, dte_hi: int, gated: bool) -> pd.DataFrame:
    m = (sig["days_to_expiry"] >= dte_lo) & (sig["days_to_expiry"] < dte_hi)
    if gated:
        m &= sig["gate"]
    flag = {"outer": "is_outer", "mode_flank": "is_mode_flank",
            "largest": "is_largest"}[boundary_class]
    out = sig[m & sig[flag]].copy()
    # engine expects one row per (as_of, symbol): keep the largest |gap|
    # within the class
    out = out.reindex(out.groupby(["as_of", "symbol"])["gap"]
                      .apply(lambda s: s.abs().idxmax()).to_numpy())
    return out


# ---------------------------------------------------------------------------
# Listed claim marks
# ---------------------------------------------------------------------------

def claim_series(q_idx, sym: str, right: str, k_lo: float, k_hi: float
                 ) -> Optional[pd.Series]:
    """Daily premium (bp) of the claim P(rate > boundary), listed legs only."""
    try:
        lo = q_idx.loc[(sym, right, round(k_lo, 4))]
        hi = q_idx.loc[(sym, right, round(k_hi, 4))]
    except KeyError:
        return None
    j = pd.concat([lo.rename("lo"), hi.rename("hi")], axis=1).dropna()
    if j.empty:
        return None
    w = (k_hi - k_lo) * 100.0
    if right == "P":
        return (j["hi"] - j["lo"]).rename("claim_bp")
    return (w - (j["lo"] - j["hi"])).rename("claim_bp")


def fly_series(q_idx, sym: str, right: str, k_center: float,
               wing: float = 0.25) -> Optional[Tuple[pd.Series, int]]:
    """Daily premium (bp) of the 1/-2/1 butterfly at ``k_center``; 4 contracts."""
    legs = [(k_center - wing, 1.0), (k_center, -2.0), (k_center + wing, 1.0)]
    series = []
    for k, wgt in legs:
        try:
            s = q_idx.loc[(sym, right, round(k, 4))]
        except KeyError:
            return None
        series.append(s * wgt)
    j = pd.concat(series, axis=1).dropna()
    if j.empty:
        return None
    return j.sum(axis=1).rename("fly_bp"), 4


# ---------------------------------------------------------------------------
# Generic fixed-legs package backtest (families B, C)
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class PackageTrade:
    symbol: str
    entry: pd.Timestamp
    exit: pd.Timestamp
    direction: str                 # "long" pays if the claim gains
    entry_bp: float
    exit_bp: float
    n_contracts: int
    exit_reason: str
    meta: dict

    @property
    def gross_bp(self) -> float:
        s = 1.0 if self.direction == "long" else -1.0
        return s * (self.exit_bp - self.entry_bp)

    def cost_bp(self, mult: float = 1.0) -> float:
        return mult * self.n_contracts * OPT_HALF_TICK_BP * 2.0

    def net_bp(self, mult: float = 1.0) -> float:
        return self.gross_bp - self.cost_bp(mult)


def run_package_backtest(
    entries: pd.DataFrame,
    mark_fn: Callable[[pd.Series], Optional[Tuple[pd.Series, int]]],
    all_dates: pd.DatetimeIndex,
    *,
    direction: str,
    lag: int = 1,
    hold_sessions: int = 20,
    dte_floor: int = 3,
    expiry_lookup: Optional[Callable[[str], datetime.date]] = None,
) -> List[PackageTrade]:
    """One open package per symbol; lag-1 entry on the global calendar.

    ``entries``: one row per signal (as_of, symbol, + meta columns).
    ``mark_fn(row) -> (daily premium series, n_contracts)`` with legs FIXED
    from the signal row. Exit at ``hold_sessions`` sessions after entry, or
    when dte hits ``dte_floor``, or at the last available mark.
    """
    open_until: Dict[str, pd.Timestamp] = {}
    trades: List[PackageTrade] = []
    for _, row in entries.sort_values("as_of").iterrows():
        sym = row["symbol"]
        d_sig = pd.Timestamp(row["as_of"])
        if sym in open_until and d_sig <= open_until[sym]:
            continue
        later = all_dates[all_dates > d_sig]
        if len(later) < lag:
            continue
        d_entry = later[lag - 1]
        mk = mark_fn(row)
        if mk is None:
            continue
        marks, n_con = mk
        marks = marks[marks.index >= d_entry]
        if marks.empty or pd.isna(marks.iloc[0]):
            continue
        stop = later[min(lag - 1 + hold_sessions, len(later) - 1)]
        exit_dt, reason = stop, "time_stop"
        if expiry_lookup is not None:
            xp = pd.Timestamp(expiry_lookup(sym)) - pd.Timedelta(days=dte_floor)
            if xp < exit_dt:
                exit_dt, reason = xp, "dte_floor"
        window = marks[marks.index <= exit_dt].dropna()
        if len(window) < 2:
            continue
        trades.append(PackageTrade(
            symbol=sym, entry=window.index[0], exit=window.index[-1],
            direction=direction, entry_bp=float(window.iloc[0]),
            exit_bp=float(window.iloc[-1]), n_contracts=n_con,
            exit_reason=reason,
            meta={k: row[k] for k in row.index
                  if k not in ("as_of", "symbol")},
        ))
        open_until[sym] = window.index[-1]
    return trades


def league_row(trades: Sequence, config: dict, *,
               cost_fn=None) -> dict:
    """Uniform metrics; ``cost_fn(trade, mult) -> cost_bp`` defaults to the
    package model; works for Channel1Trade via its own cost_bp field."""
    row = dict(config)
    if not trades:
        row.update(n_trades=0, hit=np.nan, total_gross_bp=0.0,
                   net_1x_bp=0.0, net_2x_bp=0.0, avg_net_1x_bp=np.nan,
                   t_stat=np.nan)
        return row
    if cost_fn is None:
        def cost_fn(x, m):
            return x.cost_bp(m) if callable(getattr(x, "cost_bp", None)) \
                else m * x.cost_bp
    gross = np.array([x.gross_bp for x in trades], dtype=float)
    net1 = np.array([x.gross_bp - cost_fn(x, 1.0) for x in trades])
    net2 = np.array([x.gross_bp - cost_fn(x, 2.0) for x in trades])
    se = net1.std(ddof=1) / np.sqrt(len(net1)) if len(net1) > 1 else np.nan
    row.update(
        n_trades=len(trades), hit=float((net1 > 0).mean()),
        total_gross_bp=float(gross.sum()), net_1x_bp=float(net1.sum()),
        net_2x_bp=float(net2.sum()), avg_net_1x_bp=float(net1.mean()),
        t_stat=float(net1.mean() / se) if se and se > 0 else np.nan,
    )
    return row


# ---------------------------------------------------------------------------
# Placebos
# ---------------------------------------------------------------------------

def pick_winner(live: pd.DataFrame) -> pd.Series:
    """Best league row with a sample-size floor: a 1-trade max() is noise.

    n >= 10 preferred (the verdict floor), n >= 5 tolerated with a flag,
    otherwise the least-starved row — callers print n_trades either way.
    """
    for floor in (10, 5, 1):
        cand = live[live["n_trades"] >= floor]
        if not cand.empty:
            return cand.sort_values("net_1x_bp").iloc[-1]
    return live.iloc[-1]


def gaussian_tree_gaps(sig: pd.DataFrame, mon: pd.DataFrame) -> pd.DataFrame:
    """P1: replace the lattice digitals with a moment-matched Gaussian.

    Same mean (forward) and same total std (event + smear) — everything the
    tree knows EXCEPT the lattice. Signals recomputed on the same listed
    digitals; an edge that survives is not lattice information.
    """
    from scipy.stats import norm

    m = mon.set_index(["as_of", "symbol"])
    key = pd.MultiIndex.from_frame(sig[["as_of", "symbol"]])
    fwd = m["forward_rate"].reindex(key).to_numpy()
    std = np.sqrt(m["event_std_zq_bp"].reindex(key).to_numpy() ** 2
                  + m["smear_bp"].reindex(key).to_numpy() ** 2) / 100.0
    out = sig.copy()
    p_gauss = 1.0 - norm.cdf((out["boundary_rate"].to_numpy() - fwd) / std)
    out["p_tree"] = p_gauss
    out["gap"] = out["p_listed"] - p_gauss
    # RE-classify: mode flank and largest-|gap| are functions of the tree,
    # so the placebo must recompute them — stale flags would leak the real
    # lattice's information into the "no-lattice" world
    out = (out.drop(columns=["is_outer", "is_mode_flank", "is_largest"])
           .groupby(["as_of", "symbol"], group_keys=False)
           .apply(_classify_boundaries).reset_index(drop=True))
    return out


def tree_digitals_from_ladders(sig: pd.DataFrame, mon: pd.DataFrame,
                               ladders: dict) -> pd.DataFrame:
    """Recompute p_tree/gap at the panel's boundaries from GIVEN ladders.

    Reproduces the history build's convention: strict ZQ-null tree, smear =
    sqrt(unresolved_var + 3^2). Used by the wrong-calendar placebo so the
    SIGNAL (not just the hedge) lives in the shifted world; verified against
    the frozen panel when called with the real ladders.
    """
    from scipy.stats import norm
    from RVUtils.MeetingProb.atoms import AtomEngine, split_meetings

    fwd = mon.set_index(["as_of", "symbol"])["forward_rate"]
    out = sig.copy()
    p_new = np.full(len(out), np.nan)
    for (ts, sym), idx in out.groupby(["as_of", "symbol"]).groups.items():
        lad = ladders.get(pd.Timestamp(ts).date())
        if not lad:
            continue
        cm = split_meetings(pd.Timestamp(ts).date(), sym, lad)
        if cm is None:
            continue
        try:
            f = float(fwd.loc[(ts, sym)])
        except KeyError:
            continue
        rates, probs = AtomEngine(cm).rates_probs(f)
        smear = float(np.sqrt(cm.unresolved_var_bp2 + 9.0)) / 100.0
        b = out.loc[idx, "boundary_rate"].to_numpy()
        z = (b[:, None] - rates[None, :]) / smear
        p_new[out.index.get_indexer(idx)] = (probs[None, :]
                                             * (1.0 - norm.cdf(z))).sum(axis=1)
    out["p_tree"] = p_new
    out["gap"] = out["p_listed"] - out["p_tree"]
    out = out.dropna(subset=["p_tree"])
    out = (out.drop(columns=["is_outer", "is_mode_flank", "is_largest"])
           .groupby(["as_of", "symbol"], group_keys=False)
           .apply(_classify_boundaries).reset_index(drop=True))
    return out


def shifted_ladders(ladders: dict) -> dict:
    """P2: wrong calendar — every meeting wears the NEXT meeting's q/jump."""
    import dataclasses as _dc
    out = {}
    for d, lad in ladders.items():
        if len(lad) < 2:
            out[d] = lad
            continue
        shifted = []
        for i, m in enumerate(lad):
            src = lad[min(i + 1, len(lad) - 1)]
            shifted.append(_dc.replace(
                m, jump_bp=src.jump_bp, support=src.support, q=src.q))
        out[d] = shifted
    return out


# ---------------------------------------------------------------------------
# Family E: the decomposed ICS residual series
# ---------------------------------------------------------------------------

def ics_residual_series(panels: dict, ladders: dict,
                        symbols: Sequence[str]) -> pd.DataFrame:
    """Daily decomposed ICS residual per quarterly, from settles + fixings."""
    from BT.serff.futures_data import load_cached
    from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings
    from MDP.STIRFutures._sofr_option_contracts import quarterly_reference_window
    from RVUtils.MeetingProb.ics import (
        compounding_wedge_bp, ics_blend_contracts, proxy_wedge_bp)

    fwd_idx = panels["fwd_idx"]
    last_day = fwd_idx.index.get_level_values(0).max().date() \
        if len(fwd_idx) else datetime.date(2026, 7, 28)
    sofr_fix = _fetch_fixings(as_of_date=last_day, curve_name="USD-SOFR-1D")
    effr_fix = _fetch_fixings(as_of_date=last_day, curve_name="USD-OIS")
    rows = []
    zq_cols: Dict[str, pd.Series] = {}

    def settle(contract: str) -> Optional[pd.Series]:
        if contract not in zq_cols:
            df = load_cached(contract)
            col = next((c for c in ("Close", "Last", "Settle") if
                        df is not None and c in df.columns), None)
            zq_cols[contract] = (pd.to_numeric(df[col], errors="coerce")
                                 if col else None)
            if zq_cols[contract] is not None:
                zq_cols[contract].index = pd.to_datetime(
                    zq_cols[contract].index).normalize()
        return zq_cols[contract]

    for sym in symbols:
        b1, b2 = ics_blend_contracts(sym)
        s1, s2 = settle(b1), settle(b2)
        if s1 is None or s2 is None:
            continue
        S, E = quarterly_reference_window(sym)
        win_days = (E - S).days
        idx = fwd_idx.xs(sym, level="symbol")
        for ts, fwd in idx.items():
            d = ts.date()
            if not (np.isfinite(fwd)):
                continue
            try:
                p1 = float(s1.loc[:ts].iloc[-1])
                p2 = float(s2.loc[:ts].iloc[-1])
            except (IndexError, KeyError):
                continue
            spread = ((p1 + p2) / 2.0 - (100.0 - fwd)) * 100.0
            try:
                sofr = float(sofr_fix[sofr_fix.index <= ts].iloc[-1])
                effr = float(effr_fix[effr_fix.index <= ts].iloc[-1])
            except (IndexError, TypeError):
                continue
            basis = (sofr - effr) * 1e4
            comp = compounding_wedge_bp(fwd, win_days)
            lad = ladders.get(d)
            wedge = proxy_wedge_bp(lad, sym) if lad else np.nan
            rows.append({"as_of": ts, "symbol": sym, "ics_bp": spread,
                         "basis_bp": basis, "comp_bp": comp,
                         "wedge_bp": wedge,
                         "resid_bp": spread - basis - comp + wedge,
                         "turn_quarter": sym[-3] == "Z"})
    return pd.DataFrame(rows)


def run_ics_backtest(resid: pd.DataFrame, all_dates: pd.DatetimeIndex, *,
                     threshold_bp: float, include_turn: bool,
                     direction: str = "fade", lag: int = 1,
                     hold_sessions: int = 20,
                     exit_below_bp: float = 1.0) -> List[PackageTrade]:
    """Fade (or ride) the decomposed residual via the 10:6 listed package.

    PnL in SPREAD bp on $250/bp DV01 both legs. Round-trip cost at 1x:
    10 SR3 + 6 ZQ contracts x half-tick x 2 sides, converted to spread bp.
    """
    cost_1x = (10 * FUT_HALF_TICK_BP * 25.0 + 6 * FUT_HALF_TICK_BP * 41.67) \
        / 250.0 * 2.0
    trades: List[PackageTrade] = []
    for sym, g in resid.dropna(subset=["resid_bp"]).groupby("symbol"):
        g = g.sort_values("as_of").set_index("as_of")
        open_until = None
        for ts, row in g.iterrows():
            if open_until is not None and ts <= open_until:
                continue
            if not include_turn and row["turn_quarter"]:
                continue
            if abs(row["resid_bp"]) < threshold_bp:
                continue
            later = all_dates[all_dates > ts]
            if len(later) < lag:
                continue
            path = g.loc[g.index >= later[lag - 1], "resid_bp"].dropna()
            if len(path) < 2:
                continue
            path = path.iloc[:hold_sessions + 1]
            hit = path[path.abs() < exit_below_bp]
            exit_ts = hit.index[0] if len(hit) else path.index[-1]
            seg = path.loc[:exit_ts]
            sign = -np.sign(row["resid_bp"])       # fade: profit as resid -> 0
            if direction == "momentum":
                sign = -sign
            pnl = float(sign * (seg.iloc[-1] - seg.iloc[0]))
            # the residual sign is already applied: store as a LONG claim on
            # pnl so PackageTrade.gross_bp == pnl; fade/momentum lives in meta
            trades.append(PackageTrade(
                symbol=sym, entry=seg.index[0], exit=exit_ts,
                direction="long", entry_bp=0.0, exit_bp=pnl,
                n_contracts=16,
                exit_reason="converged" if len(hit) else "time_stop",
                meta={"entry_resid": float(row["resid_bp"]), "mode": direction}))
            trades[-1].cost_override = cost_1x
            open_until = exit_ts
    return trades


def ics_cost_fn(trade, mult: float) -> float:
    return mult * getattr(trade, "cost_override", 0.8)
