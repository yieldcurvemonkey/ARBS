r"""Detachment between Fedspeak and the data, and whether it is tradeable.

Two studies already on ``main`` measured the *lead* between an equal-weighted
inflation+labour surprise composite and a Fed sentiment index
(``fed_sentiment_lead.py``, ``fedlock_sentiment_lead.py``). Their answer was that
the lead is +11 to +13 weeks on 2023-2026, that this window is a twenty-year
maximum, that the durable number over 21 years is +1 to +2 weeks with r ~ 0.12,
and that **the level of either series does not reach the price**: forward 4 to
13-week changes in ``RATES.OIS.USD_SOFR.PAR.2Y`` regressed on the composite and
on both sentiment series gave ``|t| <= 1.90, R^2 <= 0.0076`` across 18 cells.

This module asks the different question those studies did not: not "does
sentiment follow the data", but **"when sentiment DETACHES from the data, does
the front end pay you to bet on the gap closing"**. The estimator layer is
imported wholesale from ``fed_sentiment_lead_data`` -- config, composite,
sentiment index, trailing standardisation, nulls, gates -- and nothing is forked.

What "detachment" is
--------------------
Four constructions, all strictly trailing, all on the weekly (W-FRI) grid, all
scale-free so the two sides can be differenced:

``gap``      ``z(S)_t - z(C)_{t-k}``
``resid``    residual of ``z(S)_t`` on ``z(C)_{t-k}`` from a rolling OLS
``dchg``     ``(z(S)_t - z(S)_{t-m}) - (z(C)_{t-k} - z(C)_{t-k-m})``
``rankgap``  trailing percentile rank of ``S`` minus that of ``C_{t-k}``

with ``k`` in ``{0, 2, 5, 11}``: contemporaneous; the 21-year survivor (+2w);
JWS's claim (+5w); and the lead the 2023-2026 window actually measures (+11w).
Each ``k`` is a number somebody has defended, not a swept nuisance parameter.

**Sign.** ``D > 0`` means Fedspeak is MORE HAWKISH than the data warrants. The
frozen reading is ``fade``: the gap closes by the Fed coming back to the data,
so the front end rallies and you are LONG the SR3 future. ``follow`` is the
opposite reading and is a second cell, not a robustness check -- the direction
is a free parameter and the search pays for it (every null below is scored on
``max |Sharpe|``, which is exactly the cost of not knowing the sign).

What is tradeable and what is not
---------------------------------
``jpm``
    The JPM NLP corpus, gated on publication date. **Tradeable**, and short:
    the corpus starts 2023-05-02 and a 52-week trailing standardisation of the
    sentiment index consumes 26 more weeks before the first signal.
``fedlock``
    FedLock V3, ~3,700 dated speeches from 1985. **Never tradeable** -- it has
    one ``builtOn`` stamp, TrueSkill fits every rating jointly against a
    comparison graph spanning the whole corpus including the future, and the
    judge has read decades of commentary about what the Fed did next. It is here
    for twenty-year context on the same question, and every number carried from
    it is labelled *historical association*, never a backtest.

Timing
------
Signal is read at the Friday close and **filled at the next session's settle**.
Filling on the same session the signal is read from lets the entry price be the
very print the signal was computed from, and this desk has already paid for that
(``project_cavf_grid_verdict``: "same-day fills harvest mark noise"). Same-day
entry is run as a sensitivity, never as the headline.
"""
from __future__ import annotations

import dataclasses
import datetime
import pathlib
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(HERE), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_detachment_prices as PX  # noqa: E402
import fed_sentiment_lead_data as L  # noqa: E402

CONSTRUCTIONS: Tuple[str, ...] = ("gap", "resid", "dchg", "rankgap")
LEAD_KS: Tuple[int, ...] = (0, 2, 5, 11)
THRESHOLDS: Tuple[float, ...] = (0.0, 0.5, 1.0, 1.5)
HORIZONS_W: Tuple[int, ...] = (1, 2, 4, 8)

#: name -> (leg ranks, leg weights, contracts, bp-scale).
#:
#: ``bp_scale`` is dollars-per-bp of the STRUCTURE'S OWN QUOTE divided by $25,
#: i.e. how many contract-bp one bp of the quote is worth. It is what turns a
#: per-contract cost into a cost on the quote the P&L is measured in:
#: ``cost_bp_of_quote = 2 * one_way * n_contracts / bp_scale``. An outright pays
#: 0.50bp, a one-for-one calendar spread 1.00bp, and a four-contract pack quoted
#: as the average of its legs 0.50bp -- the pack is four times the risk AND four
#: times the cost, so per unit of gross risk every same-sign basket costs the
#: same. Only the spread is genuinely more expensive per unit of quote.
STRUCTURES: Dict[str, Tuple[Tuple[int, ...], Tuple[float, ...], int, float]] = {
    "out1": ((1,), (1.0,), 1, 1.0),
    "out2": ((2,), (1.0,), 1, 1.0),
    "out3": ((3,), (1.0,), 1, 1.0),
    "out4": ((4,), (1.0,), 1, 1.0),
    "spr1x3": ((1, 3), (1.0, -1.0), 2, 1.0),
    "spr2x4": ((2, 4), (1.0, -1.0), 2, 1.0),
    "pack1": ((1, 2, 3, 4), (0.25, 0.25, 0.25, 0.25), 4, 4.0),
    # Not a futures structure: a 2-year SOFR OIS, priced off the cached Citi tag
    # ``RATES.OIS.USD_SOFR.PAR.2Y``. It is in the grid for two reasons. It is the
    # only instrument that exists over FedLock's twenty-one years -- SR3 does not
    # trade before 2018-05 -- and it tests whether the *instrument* is what the
    # front-end grid is failing on rather than the signal. Its "one contract" is
    # a notional unit and its 0.50bp round trip is the same order as a 2y OIS
    # bid-offer; it is a MID quote from a vendor tag, not an executable price,
    # and every number that comes off it says so.
    "ois2y": ((0,), (1.0,), 1, 1.0),
}

#: Structures whose price does not come from the SR3 settle panel.
NON_FUTURES: Tuple[str, ...] = ("ois2y",)


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class DetachConfig:
    """Every knob in the detachment study, and why it sits where it does.

    Frozen, and the PRIMARY cell below is pre-registered: it is written down
    before the grid runs and it is reported first whatever the grid finds. The
    failure mode this guards is the one recorded in
    ``feedback_adversarial_review_flatters`` -- when the winner is chosen after
    the fact, every subsequent judgement call bends toward it.
    """

    # -- sentiment -------------------------------------------------------
    #: ``jpm`` (tradeable, 2023-05 onwards) or ``fedlock`` (21 years, never
    #: tradeable). Both are run; neither is quoted without its label.
    source: str = "jpm"
    #: FedLock's RAW ``m`` column, not the era-adjusted ``ma``. Era adjustment is
    #: quarterly block demeaning: it uses within-quarter information and removes
    #: variation at roughly the frequency a multi-week gap lives at, which is
    #: exactly the signal here. ``fedlock_data`` documents that ``ma`` is right
    #: for RANKING SPEAKERS and ``m`` for the timeline; this is a timeline.
    fedlock_score_column: str = "m"

    # -- standardisation -------------------------------------------------
    #: Trailing window for the sentiment z-score, in WEEKS. 52/26 rather than
    #: 104/52 because the JPM corpus is only ~173 weeks long and the longer
    #: window would spend a third of it before emitting a signal. The consumed
    #: weeks are counted in the funnel, and the window is swept as robustness.
    sent_z_window_w: int = 52
    sent_z_min_w: int = 26
    #: The surprise composite's own standardisation is inherited unchanged from
    #: ``LeadConfig`` (756bd / 504bd), which starts in 2005 and so binds on
    #: nothing here.

    # -- detachment ------------------------------------------------------
    construction: str = "gap"
    lead_k: int = 0
    #: Rolling-OLS window for ``resid``, in weeks. 104 is two years: long enough
    #: for a slope, short enough to follow a regime. Frozen, swept as robustness.
    reg_window_w: int = 104
    #: The differencing horizon for ``dchg``, in weeks.
    chg_window_w: int = 4
    #: The trailing window for ``rankgap``, in weeks.
    rank_window_w: int = 52

    # -- trade -----------------------------------------------------------
    #: Entry gate in standardised units. 0.0 means always-on: re-decide every
    #: ``horizon_w`` weeks and always hold something.
    threshold: float = 1.0
    horizon_w: int = 4
    structure: str = "out3"
    #: +1 = FADE (long SR3 when Fedspeak is too hawkish for the data).
    #: -1 = FOLLOW.
    sign: int = 1
    #: Fill at the next session's settle after the Friday the signal is read.
    entry_lag_sessions: int = 1

    # -- costs -----------------------------------------------------------
    #: One-way, per CONTRACT, in bp of rate. ``reference_sfr_fly_conventions``
    #: fixes this at 0.25 ("2.0bp round trip on a fly (4 contracts) ... 0.5bp on
    #: an outright"). This study's handover note says "a single-contract round
    #: trip is ~0.25bp" in the same sentence as the 2.0bp fly, which cannot both
    #: be true; the conservative reading is frozen and the optimistic one is a
    #: sensitivity.
    cost_bp_one_way: float = 0.25

    # -- inference -------------------------------------------------------
    #: Rotations of the finished detachment series against the price. The
    #: reference set is finite and is enumerated in full; the p-floor is
    #: reported rather than hidden.
    rotation_draws: int = 4000
    surrogate_draws: int = 2000
    seed: int = 20260824

    def rng(self, offset: int = 0) -> np.random.Generator:
        return np.random.default_rng(self.seed + offset)

    def cost_bp_round_trip(self) -> float:
        _, _, n_contracts, bp_scale = STRUCTURES[self.structure]
        return 2.0 * self.cost_bp_one_way * n_contracts / bp_scale

    def describe(self) -> pd.DataFrame:
        rows = []
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            rows.append({"knob": f.name, "value": "\n".join(map(str, v))
                         if isinstance(v, tuple) else v})
        return pd.DataFrame(rows)


#: The pre-registered primary cell. Written down before the grid ran.
#:
#: ``gap`` because a level difference is the plainest reading of "detached";
#: ``k=0`` because a *contemporaneous* gap is what the word means, and because
#: the 21-year evidence puts any real lead at +1 to +2 weeks, i.e. inside the
#: weekly grid's own resolution; ``threshold 1.0`` because a one-sigma gap is
#: the conventional bar and 0.0 would not be "detachment" at all; ``4 weeks``
#: because it is the shortest horizon over which a committee can visibly change
#: tack and the longest that keeps ~35 non-overlapping trades in a 3-year
#: sample; ``out3`` because the third deferred SR3 is where a repricing of the
#: Fed path shows up with real liquidity and no fixing already in the window;
#: ``sign +1`` (fade) because the data is the anchor -- the studies on ``main``
#: found surprises leading sentiment and never the reverse, so the side that is
#: expected to move is the Fed's.
PRIMARY = DetachConfig()


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------
def load_sides(cfg: DetachConfig, lead_cfg: Optional[L.LeadConfig] = None
               ) -> Tuple[pd.Series, pd.Series, Dict[str, object]]:
    """``(weekly z-composite, weekly z-sentiment, provenance)``.

    The composite is built by ``fed_sentiment_lead_data`` unchanged: two daily
    Citi surprise sub-indices, each trailing-standardised over 756bd, averaged
    only on days both are present. The sentiment index is the same module's
    calendar EWMA over VISIBLE speeches -- publication-gated for ``jpm``, and
    for ``fedlock`` explicitly not gated because there is nothing to gate on.
    """
    lead_cfg = lead_cfg or L.LeadConfig()
    panel, prov = L.load_surprise_panel()
    L.gate_surprise_sanity(panel, lead_cfg)
    composite, _legs = L.build_surprise_composite(panel, lead_cfg)
    zc = L.weekly_last(composite, lead_cfg.week_anchor)

    if cfg.source == "jpm":
        scores = L.load_fed_scores(lead_cfg)
        point_in_time = True
        note = "JPM NLP corpus, publication-gated -- tradeable"
    elif cfg.source == "fedlock":
        import fedlock_data as F

        speeches, fprov = F.load_speeches()
        F.gate_single_vintage(speeches, fprov)
        scores = F.to_score_book(speeches, score_column=cfg.fedlock_score_column)
        point_in_time = False
        note = ("FedLock V3, single vintage, jointly estimated -- HISTORICAL "
                "ASSOCIATION ONLY, never a backtest")
        prov = {**prov, "fedlock": fprov}
    else:
        raise ValueError(f"unknown source {cfg.source!r}")

    start = max(pd.Timestamp(scores["date"].min()), pd.Timestamp(zc.dropna().index.min()))
    grid = L.weekly_grid(start, pd.Timestamp(scores["date"].max()), lead_cfg.week_anchor)
    sent = L.sentiment_index(scores, grid, lead_cfg, point_in_time=point_in_time)["sentiment"]
    zs = L.trailing_z(sent, cfg.sent_z_window_w, cfg.sent_z_min_w)

    if cfg.source == "jpm":
        L.gate_no_pre_corpus(sent, lead_cfg)

    zc = zc.reindex(zs.index.union(zc.index)).sort_index()
    return zc.rename("z_composite"), zs.rename("z_sentiment"), {**prov, "note": note}


# --------------------------------------------------------------------------
# detachment
# --------------------------------------------------------------------------
def _rolling_beta_resid(y: pd.Series, x: pd.Series, window: int, min_periods: int
                        ) -> pd.Series:
    """Residual of ``y`` on ``x`` from an OLS fitted on the TRAILING window.

    The window ends at ``t`` inclusive. That uses no future information -- the
    fit at ``t`` reads only observations up to ``t`` -- and it is what a reader
    running the regression on the day would have. The alternative, ending the
    window at ``t-1``, is also defensible and is swept; it changes the residual
    by less than the tick size of anything downstream.
    """
    df = pd.concat([y.rename("y"), x.rename("x")], axis=1)
    out = pd.Series(np.nan, index=df.index, dtype=float)
    yv, xv = df["y"].to_numpy(float), df["x"].to_numpy(float)
    for i in range(len(df)):
        lo = max(0, i - window + 1)
        ys, xs = yv[lo : i + 1], xv[lo : i + 1]
        ok = np.isfinite(ys) & np.isfinite(xs)
        if ok.sum() < min_periods:
            continue
        ys, xs = ys[ok], xs[ok]
        xm, ym = xs.mean(), ys.mean()
        vx = float(((xs - xm) ** 2).sum())
        if vx <= 0:
            continue
        beta = float(((xs - xm) * (ys - ym)).sum() / vx)
        alpha = ym - beta * xm
        if np.isfinite(yv[i]) and np.isfinite(xv[i]):
            out.iloc[i] = yv[i] - (alpha + beta * xv[i])
    return out


def _trailing_rank(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Percentile rank of ``x_t`` inside its own trailing window, in [-1, +1].

    Rank rather than z so a single outlying week cannot set the level. Centred
    on zero so it differences against the other side the same way a z-score does.
    """
    s = pd.Series(series).astype(float)
    r = s.rolling(window, min_periods=min_periods).apply(
        lambda w: (np.sum(w[:-1] < w[-1]) + 0.5 * np.sum(w[:-1] == w[-1])) / max(len(w) - 1, 1),
        raw=True,
    )
    return 2.0 * r - 1.0


def detachment(zc: pd.Series, zs: pd.Series, cfg: DetachConfig) -> pd.Series:
    """The detachment series ``D``. Positive = Fedspeak hawkish vs the data.

    ``zc`` is lagged by ``lead_k`` weeks, so ``D_t`` compares today's sentiment
    with the composite as it stood ``k`` weeks ago -- the reading under which a
    measured lead of ``k`` would make the two series contemporaneous.
    """
    k = int(cfg.lead_k)
    c = zc.shift(k)
    idx = zs.index.union(c.index).sort_values()
    zs, c = zs.reindex(idx), c.reindex(idx)

    if cfg.construction == "gap":
        d = zs - c
    elif cfg.construction == "resid":
        d = _rolling_beta_resid(zs, c, cfg.reg_window_w, max(cfg.sent_z_min_w, 12))
    elif cfg.construction == "dchg":
        m = int(cfg.chg_window_w)
        d = (zs - zs.shift(m)) - (c - c.shift(m))
    elif cfg.construction == "rankgap":
        w, mp = cfg.rank_window_w, max(cfg.sent_z_min_w, 12)
        d = _trailing_rank(zs, w, mp) - _trailing_rank(c, w, mp)
    else:
        raise ValueError(f"unknown construction {cfg.construction!r}")
    return d.rename("detachment").dropna()


def gate_trailing_detachment(zc: pd.Series, zs: pd.Series, cfg: DetachConfig,
                             *, probe_dates: Iterable) -> pd.DataFrame:
    """G-D1 -- truncating the inputs after ``t`` must not change ``D`` at ``t``.

    The one testable property of a trailing statistic, applied to the whole
    construction rather than to its parts. A rolling regression, a rolling rank
    and a z-score are each individually trailing; the composition is what gets
    tested here, because it is the composition that feeds a trade.
    """
    full = detachment(zc, zs, cfg)
    rows = []
    for t in probe_dates:
        t = pd.Timestamp(t)
        d_trunc = detachment(zc[zc.index <= t], zs[zs.index <= t], cfg)
        if t not in d_trunc.index or t not in full.index:
            continue
        rows.append({"date": t, "truncated": float(d_trunc.loc[t]),
                     "full_history": float(full.loc[t]),
                     "abs_diff": abs(float(d_trunc.loc[t]) - float(full.loc[t]))})
    out = pd.DataFrame(rows)
    if not out.empty:
        worst = float(out["abs_diff"].max())
        assert worst < 1e-9, (
            f"G-D1 FAILED for construction={cfg.construction!r} k={cfg.lead_k}: the "
            f"detachment at a date moves when later data is removed (worst |diff| "
            f"{worst:.3e}) -- it is not computable in real time")
    return out


# --------------------------------------------------------------------------
# the book
# --------------------------------------------------------------------------
def session_index(panel: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(panel.index)


def _next_session(sessions: np.ndarray, after: pd.Timestamp) -> Optional[pd.Timestamp]:
    """The first session STRICTLY after ``after``. ``None`` past the end."""
    i = int(np.searchsorted(sessions, np.datetime64(after), side="right"))
    return None if i >= len(sessions) else pd.Timestamp(sessions[i])


def structure_price(panel: pd.DataFrame, symbols: Sequence[str],
                    weights: Sequence[float], date: pd.Timestamp) -> Optional[float]:
    """The structure's quote, in PRICE units, from a fixed set of contracts."""
    if date not in panel.index:
        return None
    tot = 0.0
    for sym, w in zip(symbols, weights):
        if sym not in panel.columns:
            return None
        v = panel.at[date, sym]
        if pd.isna(v):
            return None
        tot += float(w) * float(v)
    return tot


def schedule(d: pd.Series, cfg: DetachConfig, sessions: np.ndarray) -> pd.DataFrame:
    """Non-overlapping trades from the detachment series.

    The rule: walk the weekly grid; when flat and ``|D| >= threshold``, take the
    trade, hold ``horizon_w`` weeks, then go flat and start looking again. That
    is a book somebody could run, it produces one P&L per trade rather than an
    overlapping stream, and it means a Sharpe computed on those P&Ls is not
    quietly counting the same week eight times.

    Entry and exit are both SESSIONS, taken ``entry_lag_sessions`` after the
    Friday whose close the signal was read from.
    """
    idx = list(d.index)
    vals = d.to_numpy(float)
    h = int(cfg.horizon_w)
    thr = float(cfg.threshold)
    rows = []
    i = 0
    while i < len(idx):
        v = vals[i]
        if not np.isfinite(v) or abs(v) < thr or (thr == 0.0 and v == 0.0):
            i += 1
            continue
        j = i + h
        if j >= len(idx):
            break
        signal_date, exit_signal_date = idx[i], idx[j]
        entry = signal_date
        for _ in range(int(cfg.entry_lag_sessions)):
            entry = _next_session(sessions, entry)
            if entry is None:
                break
        exit_ = exit_signal_date
        for _ in range(int(cfg.entry_lag_sessions)):
            exit_ = _next_session(sessions, exit_)
            if exit_ is None:
                break
        if cfg.entry_lag_sessions == 0:
            entry = _snap_back(sessions, signal_date)
            exit_ = _snap_back(sessions, exit_signal_date)
        if entry is None or exit_ is None or exit_ <= entry:
            i += 1
            continue
        rows.append({"signal_date": signal_date, "entry_date": entry,
                     "exit_date": exit_, "detachment": float(v),
                     "side": int(cfg.sign) * (1 if v > 0 else -1)})
        i = j
    return pd.DataFrame(rows)


def _snap_back(sessions: np.ndarray, on: pd.Timestamp) -> Optional[pd.Timestamp]:
    """The last session at or before ``on`` -- the same-day-fill sensitivity."""
    i = int(np.searchsorted(sessions, np.datetime64(on), side="right")) - 1
    return None if i < 0 else pd.Timestamp(sessions[i])


def price_book(trades: pd.DataFrame, panel: pd.DataFrame, cfg: DetachConfig
               ) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Attach entry/exit prices and P&L. Contracts are fixed AT ENTRY.

    That fixing is the whole roll story. Rank 1 is the front contract whose
    reference quarter has not yet STARTED, so a rank-N contract selected at
    ``t`` cannot expire sooner than about thirteen weeks later, and the longest
    holding period here is eight. No trade crosses a roll, so no P&L in this
    module ever differences two different contracts -- which matters because
    ``reference_imm_roll_fomc_collision`` records that 22 of 33 SR3 rolls are
    themselves FOMC decision dates, i.e. a roll jump would be correlated with
    the signal rather than being noise.
    """
    if cfg.structure in NON_FUTURES:
        raise ValueError(
            f"{cfg.structure!r} is not an SR3 structure -- this path exists to "
            f"cross-check the futures book against the engine, and a vendor rate "
            f"tag has no contract to check")
    ranks, weights, n_contracts, bp_scale = STRUCTURES[cfg.structure]
    cost = cfg.cost_bp_round_trip()
    reasons: Dict[str, int] = {}
    rows = []
    for _, t in trades.iterrows():
        entry_d = pd.Timestamp(t["entry_date"])
        syms = [PX.rank_symbol(entry_d.date(), r) for r in ranks]
        exp = min(pd.Timestamp(PX.contract_window(s).end) for s in syms)
        if exp <= pd.Timestamp(t["exit_date"]):
            reasons["contract expires inside the hold"] = reasons.get(
                "contract expires inside the hold", 0) + 1
            continue
        pe = structure_price(panel, syms, weights, entry_d)
        pxx = structure_price(panel, syms, weights, pd.Timestamp(t["exit_date"]))
        if pe is None:
            reasons["no entry settle"] = reasons.get("no entry settle", 0) + 1
            continue
        if pxx is None:
            reasons["no exit settle"] = reasons.get("no exit settle", 0) + 1
            continue
        gross = float(t["side"]) * (pxx - pe) / PX.PX_PER_BP
        rows.append({**t.to_dict(), "symbols": "/".join(syms), "entry_px": pe,
                     "exit_px": pxx, "pnl_bp_gross": gross, "cost_bp": cost,
                     "pnl_bp": gross - cost, "n_contracts": n_contracts,
                     "bp_scale": bp_scale})
    book = pd.DataFrame(rows)
    reasons["priced"] = int(len(book))
    return book, reasons


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------
def score_book(book: pd.DataFrame, *, weeks_per_trade: float) -> Dict[str, float]:
    """Per-trade statistics, plus a Sharpe annualised by trade FREQUENCY.

    Annualising by ``52 / weeks_per_trade`` rather than by 252 is the only
    honest scaling for a book that is flat between trades: it says what this
    strategy earns per year of running it, not what a daily strategy with the
    same per-observation Sharpe would earn.
    """
    if book is None or book.empty:
        return {"trades": 0, "avg_bp": np.nan, "sharpe": np.nan, "sharpe_ann": np.nan,
                "hit": np.nan, "total_bp": np.nan, "t_stat": np.nan,
                "gross_avg_bp": np.nan, "episodes": 0, "top_episode_share": np.nan}
    p = book["pnl_bp"].to_numpy(float)
    sd = float(p.std(ddof=1)) if len(p) > 1 else np.nan
    sr = float(p.mean() / sd) if sd and np.isfinite(sd) and sd > 0 else np.nan
    per_year = 52.0 / float(weeks_per_trade)
    ep = episodes(book)
    tot = float(np.abs(p).sum())
    return {
        "trades": int(len(p)),
        "avg_bp": float(p.mean()),
        "gross_avg_bp": float(book["pnl_bp_gross"].mean()),
        "total_bp": float(p.sum()),
        "hit": float((p > 0).mean()),
        "sharpe": sr,
        "sharpe_ann": sr * np.sqrt(per_year) if np.isfinite(sr) else np.nan,
        "t_stat": float(p.mean() / (sd / np.sqrt(len(p)))) if sd and sd > 0 else np.nan,
        "episodes": int(ep["episode"].nunique()) if len(ep) else 0,
        "top_episode_share": float(
            ep.groupby("episode")["pnl_bp"].sum().abs().max() / tot) if tot > 0 and len(ep)
        else np.nan,
    }


def episodes(book: pd.DataFrame, gap_weeks: int = 8) -> pd.DataFrame:
    """Label trades into EPISODES -- runs of the same side, close together.

    Two smoothed series produce a handful of multi-month disagreements, not a
    stream of independent weekly bets. A book of 30 trades that lives in three
    episodes has an effective sample of three, and any statistic computed as if
    it had thirty is describing something that does not exist. So the episode
    count and the share of |P&L| in the largest one travel with every cell.
    """
    if book is None or book.empty:
        return pd.DataFrame(columns=["episode", "pnl_bp"])
    b = book.sort_values("signal_date").reset_index(drop=True).copy()
    ep, cur = [], 0
    prev_side, prev_date = None, None
    for _, r in b.iterrows():
        d = pd.Timestamp(r["signal_date"])
        new = (prev_side is None or int(r["side"]) != int(prev_side)
               or (d - prev_date).days > gap_weeks * 7)
        if new:
            cur += 1
        ep.append(cur)
        prev_side, prev_date = int(r["side"]), d
    b["episode"] = ep
    return b
