"""Family B carry harness: rolled dispersion books on the SR3 lattice.

The grid's episodic family B was structurally starved: the lab quotes are
OTM-ONLY, so any fly straddling the money silently lost legs and the entry
was skipped. Here the full call surface is synthesized via put-call parity
(C = P + DF*(F-K); with settle-based forwards the error is ~0.03bp), and
the premium becomes a BOOK — rank-based quarterly holdings, rolled at
expiry-3d, marked daily, with per-day-type attribution and a tree-fair
richness series for the mean-reversion question.

Conventions: everything in bp of price; books defined LONG the structure
(long fly = short dispersion); costs per option leg per side at the 0.125bp
half-tick, charged at entries/rolls/early exits and NOT at expiry
settlement (cash intrinsic, no spread crossed).
"""
from __future__ import annotations

import dataclasses
import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LAB = Path("C:/Users/chris/clee/ARBS/notebooks/data/sfr_rv_lab")
FAMB = HERE.parent / "data" / "famb"

OPT_HALF_TICK_BP = 0.125
_MONTHS = {"H": 3, "M": 6, "U": 9, "Z": 12}


# ---------------------------------------------------------------------------
# Contract calendar
# ---------------------------------------------------------------------------

def quarterly_symbols(y0: int = 2021, y1: int = 2028) -> List[str]:
    return [f"SFR{c}{y % 100:02d}" for y in range(y0, y1 + 1) for c in "HMUZ"]


def rank_symbol(as_of: datetime.date, rank: int) -> Optional[str]:
    """The rank-th (1-based) quarterly whose option still trades at as_of."""
    from MDP.STIRFutures._sofr_option_contracts import sofr_option_last_trade_date
    alive = []
    for s in quarterly_symbols():
        x = sofr_option_last_trade_date(s)
        if x is not None and x - datetime.timedelta(days=3) > as_of:
            alive.append((x, s))
    alive.sort()
    return alive[rank - 1][1] if len(alive) >= rank else None


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_quotes() -> pd.DataFrame:
    """Lab panel plus every landed old-expiry backfill part (incremental)."""
    frames = [pd.read_parquet(LAB / "quotes.parquet")[
        ["as_of", "symbol", "right", "strike_price", "strike_rate",
         "premium_bp", "oi", "volume"]]]
    for p in sorted((FAMB / "parts").glob("*_quotes.parquet")):
        frames.append(pd.read_parquet(p))
    q = pd.concat(frames, ignore_index=True)
    q["as_of"] = pd.to_datetime(q["as_of"])
    q = q.drop_duplicates(["as_of", "symbol", "right", "strike_price"])
    return q


def sr3_forwards(symbols: Sequence[str]) -> pd.DataFrame:
    """Daily forward RATE (percent) per OPTION symbol from serff SR3 settles.

    Option roots are SFR*; the futures cache keys the same contracts SR3*.
    """
    from BT.serff.futures_data import load_cached
    rows = []
    for s in symbols:
        df = load_cached("SR3" + s[3:] if s.startswith("SFR") else s)
        col = next((c for c in ("Close", "Last", "Settle") if
                    df is not None and c in df.columns), None)
        if col is None:
            continue
        px = pd.to_numeric(df[col], errors="coerce").dropna()
        px.index = pd.to_datetime(px.index).normalize()
        rows.append(pd.DataFrame({"as_of": px.index, "symbol": s,
                                  "fwd_rate": 100.0 - px}))
    return pd.concat(rows, ignore_index=True)


def premium_surface(quotes: pd.DataFrame, fwd: pd.DataFrame) -> pd.Series:
    """Parity-completed BOTH-rights premium surface.

    Where only one right is listed (the panel is OTM-only), the other is
    synthesized: ``C = P + DF*(F_price - K)*100`` and vice versa; DF from
    the forward level over the residual tenor (error ~0.03bp on typical
    moneyness). Listed premiums always win over synthetic ones.
    Indexed (right, symbol, strike_price, as_of) -> premium bp.
    """
    from MDP.STIRFutures._sofr_option_contracts import sofr_option_last_trade_date
    q = quotes.merge(fwd, on=["as_of", "symbol"], how="inner")
    xp = {s: sofr_option_last_trade_date(s) for s in q["symbol"].unique()}
    q["tte"] = [(xp[s] - ts.date()).days / 360.0
                for s, ts in zip(q["symbol"], q["as_of"])]
    q["df"] = 1.0 / (1.0 + q["fwd_rate"] / 100.0 * q["tte"].clip(lower=0.0))
    q["fwd_px"] = 100.0 - q["fwd_rate"]
    par = q["df"] * (q["fwd_px"] - q["strike_price"]) * 100.0
    synth = q.assign(
        right=np.where(q["right"] == "C", "P", "C"),
        premium_bp=np.where(q["right"] == "C",
                            q["premium_bp"] - par,       # P = C - DF(F-K)
                            q["premium_bp"] + par),      # C = P + DF(F-K)
        listed=False)
    both = pd.concat([q.assign(listed=True), synth], ignore_index=True)
    both = (both.sort_values("listed", ascending=False)
            .drop_duplicates(["right", "symbol", "strike_price", "as_of"],
                             keep="first"))
    return both.set_index(["right", "symbol", "strike_price", "as_of"])[
        "premium_bp"].sort_index()


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------

def structure_legs(book: str, k_center: float) -> List[Tuple[str, float, float]]:
    """(right, strike_price, weight) legs. Flys/dflys all-call (parity-
    completed surface); strangles put-low + call-high — NEVER a synthesized
    ITM call, which would smuggle a forward position into the package."""
    k = k_center
    if book == "FLY25":
        return [("C", k - 0.25, 1.0), ("C", k, -2.0), ("C", k + 0.25, 1.0)]
    if book == "FLY50":
        return [("C", k - 0.50, 1.0), ("C", k, -2.0), ("C", k + 0.50, 1.0)]
    if book == "DFLY":
        return [("C", k - 0.25, 1.0), ("C", k, -3.0),
                ("C", k + 0.25, 3.0), ("C", k + 0.50, -1.0)]
    if book == "STRG50":
        return [("P", k - 0.50, 1.0), ("C", k + 0.50, 1.0)]
    if book == "STRG75":
        return [("P", k - 0.75, 1.0), ("C", k + 0.75, 1.0)]
    raise ValueError(book)


def n_contracts(book: str) -> int:
    return {"FLY25": 4, "FLY50": 4, "DFLY": 8, "STRG50": 2, "STRG75": 2}[book]


def intrinsic_bp(legs: Sequence[Tuple[str, float, float]],
                 settle_px: float) -> float:
    """Terminal package value at the futures price on option expiry."""
    out = 0.0
    for right, k, w in legs:
        pay = max(settle_px - k, 0.0) if right == "C" else max(k - settle_px,
                                                               0.0)
        out += w * pay * 100.0
    return float(out)


# ---------------------------------------------------------------------------
# Tree context (modal strike selection + fair premiums)
# ---------------------------------------------------------------------------

class TreeCtx:
    def __init__(self, dates: Sequence[datetime.date]):
        from RVUtils.MeetingProb import meeting_ladder, zq_settle_panel
        from SDRUtils.analytics.fomc import load_fomc_schedule
        zq = zq_settle_panel([f"ZQ{c}{y:02d}" for y in range(21, 28)
                              for c in "FGHJKMNQUVXZ"])
        fomc = load_fomc_schedule("USD-SOFR-1D")
        self.ladders = {d: meeting_ladder(d, zq, fomc) for d in dates}
        self._cm_cache: Dict[Tuple[datetime.date, str], object] = {}

    def cm(self, d: datetime.date, sym: str):
        key = (d, sym)
        if key not in self._cm_cache:
            from RVUtils.MeetingProb import split_meetings
            lad = self.ladders.get(d)
            self._cm_cache[key] = (split_meetings(d, sym, lad)
                                   if lad else None)
        return self._cm_cache[key]

    def atoms(self, d: datetime.date, sym: str, fwd_rate: float):
        from RVUtils.MeetingProb.atoms import AtomEngine
        cm = self.cm(d, sym)
        if cm is None:
            return None
        eng = AtomEngine(cm)
        rates, probs = eng.rates_probs(fwd_rate)
        smear = float(np.sqrt(cm.unresolved_var_bp2 + 9.0))
        return rates, probs, smear

    def modal_center_px(self, d: datetime.date, sym: str,
                        fwd_rate: float) -> Optional[float]:
        """Price strike (0.25 grid) at the tree's modal atom."""
        out = self.atoms(d, sym, fwd_rate)
        if out is None:
            return None
        rates, probs, _ = out
        mode_rate = float(rates[int(np.argmax(probs))])
        return round((100.0 - mode_rate) * 4.0) / 4.0

    def fair_package_bp(self, d: datetime.date, sym: str, fwd_rate: float,
                        legs: Sequence[Tuple[str, float, float]]) -> float:
        from RVUtils.MeetingProb.pricer import price_option
        out = self.atoms(d, sym, fwd_rate)
        if out is None:
            return np.nan
        rates, probs, smear = out
        return float(sum(
            w * price_option(rates, probs, right, 100.0 - k, smear_bp=smear)
            for right, k, w in legs))


# ---------------------------------------------------------------------------
# The rolled book
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Holding:
    symbol: str
    start: pd.Timestamp
    end: pd.Timestamp
    legs: List[Tuple[str, float, float]]
    marks: pd.Series                    # daily package premium bp
    fair: pd.Series                     # tree-fair package premium bp
    terminal_bp: Optional[float]        # intrinsic at expiry (if held there)


def build_book(
    book: str,
    rank: int,
    dates: pd.DatetimeIndex,
    surface: pd.Series,
    fwd_idx: pd.Series,                 # (as_of, symbol) -> fwd_rate
    tree: TreeCtx,
) -> List[Holding]:
    """Hold the rank-th quarterly's structure, re-struck at each roll."""
    from MDP.STIRFutures._sofr_option_contracts import sofr_option_last_trade_date
    holdings: List[Holding] = []
    cur_sym, seg_start = None, None
    for ts in dates:
        sym = rank_symbol(ts.date(), rank)
        if sym != cur_sym:
            if cur_sym is not None:
                holdings.append((cur_sym, seg_start, ts))
            cur_sym, seg_start = sym, ts
    if cur_sym is not None:
        holdings.append((cur_sym, seg_start, dates[-1] + pd.Timedelta(days=1)))

    out: List[Holding] = []
    for sym, start, end in holdings:
        if sym is None:
            continue
        try:
            f0 = float(fwd_idx.loc[(start, sym)])
        except KeyError:
            # no settle on the roll day; try the next few sessions
            try:
                seg = fwd_idx.xs(sym, level="symbol")
            except KeyError:
                continue
            seg = seg[(seg.index >= start) & (seg.index < end)]
            if seg.empty:
                continue
            start, f0 = seg.index[0], float(seg.iloc[0])
        kc = tree.modal_center_px(start.date(), sym, f0)
        if kc is None:
            continue
        legs = structure_legs(book, kc)
        try:
            mk = sum(w * surface.loc[(right, sym, round(k, 4))]
                     for right, k, w in legs)
        except KeyError:
            continue
        mk = mk[(mk.index >= start) & (mk.index < end)].dropna()
        if len(mk) < 2:
            continue
        fair = pd.Series(
            {ts: tree.fair_package_bp(ts.date(), sym,
                                      float(fwd_idx.get((ts, sym), np.nan)),
                                      legs)
             for ts in mk.index}, dtype=float)
        expiry = sofr_option_last_trade_date(sym)
        term = None
        if mk.index[-1].date() >= expiry - datetime.timedelta(days=4):
            try:
                fx = float(fwd_idx.loc[(pd.Timestamp(expiry), sym)])
                term = intrinsic_bp(legs, 100.0 - fx)
            except KeyError:
                pass
        out.append(Holding(symbol=sym, start=mk.index[0], end=mk.index[-1],
                           legs=legs, marks=mk, fair=fair, terminal_bp=term))
    return out


def book_daily_pnl(holdings: Sequence[Holding], *,
                   cost_mult: float = 1.0,
                   n_legs: int = 4) -> pd.DataFrame:
    """Daily long-book PnL with roll costs; terminal settle replaces the
    last mark when available (expiry exits are cash intrinsic, no cost)."""
    rows = []
    per_side = n_legs * OPT_HALF_TICK_BP * cost_mult
    for h in holdings:
        d = h.marks.diff().dropna()
        for ts, v in d.items():
            rows.append({"as_of": ts, "symbol": h.symbol, "pnl_bp": float(v),
                         "kind": "mark"})
        rows.append({"as_of": h.marks.index[0], "symbol": h.symbol,
                     "pnl_bp": -per_side, "kind": "entry_cost"})
        if h.terminal_bp is not None:
            rows.append({"as_of": h.marks.index[-1], "symbol": h.symbol,
                         "pnl_bp": float(h.terminal_bp - h.marks.iloc[-1]),
                         "kind": "settle"})
        else:
            rows.append({"as_of": h.marks.index[-1], "symbol": h.symbol,
                         "pnl_bp": -per_side, "kind": "exit_cost"})
    return pd.DataFrame(rows)


def attribution(pnl: pd.DataFrame, decisions: Sequence[datetime.date]
                ) -> pd.DataFrame:
    """Split daily PnL into decision-window / settle / cost / ordinary."""
    dec = pd.DatetimeIndex([pd.Timestamp(d) for d in decisions])
    df = pnl.copy()

    def tag(row):
        if row["kind"] in ("entry_cost", "exit_cost"):
            return "costs"
        if row["kind"] == "settle":
            return "settlement"
        near = (abs((dec - row["as_of"]).days).min()
                if len(dec) else 99)
        return "decision_window" if near <= 1 else "ordinary"

    df["bucket"] = df.apply(tag, axis=1)
    return df.groupby("bucket")["pnl_bp"].agg(["sum", "count"])


# ---------------------------------------------------------------------------
# Richness + mean reversion
# ---------------------------------------------------------------------------

def richness_frame(holdings: Sequence[Holding]) -> pd.DataFrame:
    rows = []
    for h in holdings:
        rich = (h.marks - h.fair).dropna()
        for ts, v in rich.items():
            rows.append({"as_of": ts, "symbol": h.symbol,
                         "rich_bp": float(v)})
    return pd.DataFrame(rows)


def ou_half_life(rich: pd.DataFrame) -> Tuple[float, float, int]:
    """Pooled AR(1) on within-holding richness -> (half-life days, phi, n)."""
    xs, ys = [], []
    for _, g in rich.groupby("symbol"):
        s = g.set_index("as_of")["rich_bp"].sort_index()
        if len(s) < 10:
            continue
        xs.append(s.shift(1).iloc[1:].to_numpy())
        ys.append(s.iloc[1:].to_numpy())
    if not xs:
        return np.nan, np.nan, 0
    x = np.concatenate(xs)
    y = np.concatenate(ys)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    xm, ym = x - x.mean(), y - y.mean()
    phi = float(np.dot(xm, ym) / np.dot(xm, xm))
    hl = float(np.log(0.5) / np.log(abs(phi))) if 0 < abs(phi) < 1 else np.inf
    return hl, phi, len(x)


def series_stats(daily: pd.Series) -> dict:
    """Uniform daily-series statistics: Sharpe, NW t, maxDD, skew, worst."""
    from RVUtils.SFRRVLab.stats import nw_tstat
    d = daily.dropna()
    if len(d) < 5:
        return {"days": len(d), "total_bp": float(d.sum())}
    sd = d.std(ddof=1)
    eq = d.cumsum()
    dd = eq - eq.cummax()
    return {
        "days": int(len(d)),
        "total_bp": round(float(d.sum()), 1),
        "sharpe_ann": round(float(d.mean() / sd * np.sqrt(252)), 2)
        if sd > 0 else np.nan,
        "nw_t": round(float(nw_tstat(d.to_numpy())), 2),
        "max_dd_bp": round(float(dd.min()), 1),
        "worst_day_bp": round(float(d.min()), 2),
        "skew": round(float(d.skew()), 2),
    }


def trades_daily_pnl(trades: Sequence[dict], holdings: Sequence[Holding],
                     *, cost_mult: float = 1.0, n_legs: int = 4) -> pd.Series:
    """Position-based daily PnL of an intra-quarter trade list.

    Each trade contributes side * daily mark change over (entry, exit], with
    half the round-trip cost booked on the entry day and half on the exit
    day — the honest daily series for NW t / Sharpe / drawdown.
    """
    hmap: Dict[Tuple[str, pd.Timestamp], Holding] = {}
    for h in holdings:
        hmap[(h.symbol, h.marks.index[0])] = h
    by_sym: Dict[str, List[Holding]] = {}
    for h in holdings:
        by_sym.setdefault(h.symbol, []).append(h)
    out: Dict[pd.Timestamp, float] = {}
    half_cost = n_legs * OPT_HALF_TICK_BP * cost_mult
    for t in trades:
        h = next((h for h in by_sym.get(t["symbol"], [])
                  if h.marks.index[0] <= t["entry"] <= h.marks.index[-1]),
                 None)
        if h is None:
            continue
        seg = h.marks[(h.marks.index >= t["entry"])
                      & (h.marks.index <= t["exit"])]
        d = float(t["side"]) * seg.diff().dropna()
        for ts, v in d.items():
            out[ts] = out.get(ts, 0.0) + float(v)
        out[seg.index[0]] = out.get(seg.index[0], 0.0) - half_cost
        out[seg.index[-1]] = out.get(seg.index[-1], 0.0) - half_cost
    return pd.Series(out).sort_index()


def intra_quarter_backtest(
    holdings: Sequence[Holding], *,
    thr_bp: float, exit_frac: float = 0.5, max_hold: int = 15,
    direction: str = "fade", cost_mult: float = 1.0, n_legs: int = 4,
    lag: int = 1,
) -> List[dict]:
    """Trade richness WITHOUT holding to resolution: enter |rich|>thr,
    exit at thr*exit_frac / max_hold sessions / holding end."""
    trades = []
    per_round_trip = 2 * n_legs * OPT_HALF_TICK_BP * cost_mult
    for h in holdings:
        rich = (h.marks - h.fair).dropna()
        marks = h.marks.reindex(rich.index)
        i = 0
        while i < len(rich) - lag - 1:
            r0 = float(rich.iloc[i])
            if abs(r0) < thr_bp:
                i += 1
                continue
            e = i + lag                          # lag-1 entry
            side = -np.sign(r0)                  # fade: short rich structure
            if direction == "momentum":
                side = -side
            j = e + 1
            while j < len(rich) - 1 and j - e < max_hold \
                    and abs(rich.iloc[j]) > abs(r0) * exit_frac:
                j += 1
            gross = float(side * (marks.iloc[j] - marks.iloc[e]))
            trades.append({
                "symbol": h.symbol, "entry": rich.index[e],
                "exit": rich.index[j], "entry_rich": r0,
                "side": float(side),
                "gross_bp": gross, "net_bp": gross - per_round_trip,
                "sessions": int(j - e),
            })
            i = j + 1
    return trades
