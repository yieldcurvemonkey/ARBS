r"""Trade SR3 on where the DATA says Fedspeak is going.

The claim under test
--------------------
JWS Macro #8 (23-Aug-2026): *"we see a tidy 5 week lead of data surprise vs.
Fedspeak"* -- Fed speakers turn hawkish or dovish behind the economic data, so
the surprise index tells you what the committee is about to sound like. If that
is true and the front end has not already priced it, the simplest possible trade
follows: **pay SR3 when the data says Fedspeak is heading hawkish, receive SR3
when it says dovish.**

This module is that trade, and only that trade. It does NOT use the Fed
sentiment index to decide anything in its primary reading -- the whole point is
that the data is the leading side, so the data alone is the signal. The
sentiment index appears in one secondary reading (``fit``) and in the diagnostics.

Two studies already on ``main`` measured the lead itself
(``fed_sentiment_lead.py``, ``fedlock_sentiment_lead.py``) and a third asked
whether the *gap* between the two sides is tradeable
(``fed_detachment_rv.py``, 2,048 cells, dead before costs). This is the
different, simpler question those three did not ask: **not the gap, the level
and the direction of the data itself, traded outright.**

Alignment -- the one piece of arithmetic that decides the study
--------------------------------------------------------------
It is tempting to write the signal as ``zc.shift(k)`` and sweep ``k``. That is
the alignment for *measuring* a lead, not for *trading* it, and using it makes
the signal gratuitously stale.

Do the arithmetic instead. Suppose the surprise composite ``C`` leads the Fed
sentiment index ``S`` by ``L`` weeks, so that ``S_t`` tracks ``C_{t-L}``. A
position opened at ``t`` and held ``h`` weeks is exposed to what the Fed sounds
like at ``t+h``, and

    ``S_{t+h}``  tracks  ``C_{t+h-L}`` = ``C_{t-(L-h)}``

so the change in Fedspeak over the holding period is forecast by

    ``s_t = C_{t-(L-h)} - C_{t-L}``          (the ``chg`` reading)

which is knowable at ``t`` whenever ``L >= h``. Both ends of that window are
lags, and both are pinned by ``(L, h)`` -- there is no free parameter. When
``L < h`` the near end clamps to ``0`` (today's reading is the most recent
information there is) and the window shortens.

:meth:`ExpectConfig.lags` implements exactly that map, and the grid's only
signal axis is ``L``, taking values somebody has defended:

    ``L = 0``   no lead at all -- trade the direction the data has ALREADY moved
                over the holding period. This is the honest null-hypothesis
                reading and it is the **pre-registered primary**.
    ``L = 2``   the 21-year survivor from ``fedlock_sentiment_lead`` (r ~ 0.12).
    ``L = 5``   JWS's claim.
    ``L = 11``  what the 2023-2026 window actually measures -- and which the
                FedLock study showed is that window's twenty-year MAXIMUM.

Sign convention -- stated once, pinned by the test suite
--------------------------------------------------------
``s_t > 0``  the data has surprised HOT, so Fedspeak is expected to turn
             HAWKISH, so the front end should sell off.
``direction = +1`` (**FOLLOW**, the frozen reading) therefore **PAYS** -- it is
             SHORT the SR3 future, which profits when the price falls and the
             rate rises.
``direction = -1`` (**FADE**) is the opposite reading. It is a second cell and
             it is paid for in the deflation, not a robustness check: the sign
             of a signal is a free parameter and searching it costs.

In code the price side is ``side = -direction * sign(s)``. ``side = +1`` is LONG
the future = RECEIVE. This module deliberately does **not** reuse
``DetachConfig.sign``, whose ``+1`` means FADE: two studies sharing a knob name
with opposite meanings is this desk's most repeated defect class.

Roll -- the trap this study is most exposed to
----------------------------------------------
A weekly directional book is exactly the thing that gets destroyed by a naive
roll. Measured by :func:`roll_placebo` on the real settle panel over the 432
Fridays of 2018-05-11..2026-08-21, rank 3, of which 33 contain a contract
change: differencing a fixed-RANK price column gives a signed mean weekly move
of **+4.56bp on roll weeks against -0.81bp otherwise**, and its |median| is
**16.5bp against 5.0bp**. Against the change in the contract actually HELD over
the same weeks (**-2.03bp** mean) the gap is **+6.59bp per roll week and
+217.5bp in total** -- pure fabrication, from stepping one contract further out
the strip. Off the roll weeks the two constructions agree to **0.0bp**, which is
the known answer that certifies the measurement.

Any book built by ``.diff()``-ing a rank column is trading that drift, and
``reference_imm_roll_fomc_collision`` records that 22 of the 33 SR3 rolls ARE
FOMC decision dates -- so the fabricated drift is correlated with the signal
rather than being noise.

Nothing here ever differences two contracts:

* the discrete book fixes the contract at the filled entry session and re-reads
  the SAME symbol at exit, and drops any trade whose contract expires inside the
  hold (:func:`price_trades`);
* the always-on book computes each week's P&L on the contract held THAT week,
  and pays a full round trip whenever the contract changes
  (:func:`weekly_book`).

:func:`roll_placebo` measures the drift the naive construction would have
booked, and :func:`gate_no_roll_jump` asserts that this module's books carry
none of it. The placebo is run first, on a construction whose answer is known,
because a checking tool that is itself wrong reports success.

Look-ahead -- what is gated and what is not
-------------------------------------------
Gated, with an assertion each:

    ``G-X1``  every signal series is trailing-only: truncating the inputs after
              ``t`` must not move the signal at ``t`` (:func:`gate_trailing_signal`).
    ``G-X2``  the fill is the NEXT session after the Friday the signal is read
              from, never that session (:func:`gate_fill_is_next_session`).
    ``G-X3``  no P&L differences two contracts (:func:`gate_no_roll_jump`).
    ``G-X4``  a rate is a rate: ``PX.gate_rate_sanity`` on the 2y OIS leg, band
              -1%..15%, because ``RATES.OIS.USD_SOFR.PAR.2Y`` in the shared tag
              cache is 47% swaption vol and two shipped studies regressed
              against it.

NOT gated, and named rather than buried:

    **The Citi surprise snapshot is a single vintage.** It was fetched on one
    day and carries only the latest read of every daily CESI value. Citi
    revises and periodically rebases its surprise indices, so a revision made
    after the fact is silently back-propagated into the trailing z-score. There
    is no publication axis on the surprise side at all -- ``G1`` in the lead
    study gates SPEECHES only. This is the largest residual look-ahead in the
    stack. :func:`vintage_sensitivity` bounds it by re-running the whole book
    with the composite delayed an extra 1 and 2 weeks; if the result survives a
    two-week delay it cannot be living on a revision.

    **The ``fit`` reading additionally inherits the JPM corpus's own vintage
    cost** -- 53% of Fed rows are published after the speech they score. It is
    publication-gated (``point_in_time=True``) but the gate is a lower bound,
    because an unparseable report date falls back to the speech date.
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

import fed_detachment_data as D  # noqa: E402
import fed_detachment_prices as PX  # noqa: E402
import fed_sentiment_lead_data as L  # noqa: E402

#: The readings. ``level`` and ``chg`` need only the surprise composite and so
#: run over the whole SR3 history; ``fit`` needs the Fed sentiment index and is
#: therefore confined to the JPM corpus's ~121 usable weeks.
READINGS: Tuple[str, ...] = ("level", "chg", "fit")

#: The lead axis. Every value is a number somebody has defended -- see the
#: module docstring. It is NOT a swept nuisance parameter.
LEADS_W: Tuple[int, ...] = (0, 2, 5, 11)

#: Holding periods, weeks.
HORIZONS_W: Tuple[int, ...] = (1, 2, 4, 8)

#: Entry gate in standardised units. 0.0 is always-on.
THRESHOLDS: Tuple[float, ...] = (0.0, 0.5, 1.0)

#: Reuse the detachment study's structure table verbatim rather than forking it:
#: same ranks, same weights, same contract counts, same bp scale.
STRUCTURES = D.STRUCTURES
NON_FUTURES = D.NON_FUTURES


# ==========================================================================
# config
# ==========================================================================
@dataclasses.dataclass(frozen=True)
class ExpectConfig:
    """Every knob, and why it sits where it does.

    Frozen. :data:`PRIMARY` below is pre-registered -- written down before the
    grid runs and reported first whatever the grid finds.
    """

    # -- the signal ------------------------------------------------------
    #: ``level`` | ``chg`` | ``fit``.
    reading: str = "chg"
    #: The lead the data is ASSUMED to have over Fedspeak, in weeks. Enters the
    #: signal only through :meth:`lags`, which turns ``(lead_w, horizon_w)``
    #: into the two lags the docstring derives.
    lead_w: int = 0
    #: Trailing OLS window for ``fit``, in weeks. 104 = two years, the same
    #: choice ``DetachConfig.reg_window_w`` makes and for the same reason.
    reg_window_w: int = 104

    # -- the trade -------------------------------------------------------
    horizon_w: int = 4
    #: ``|s|`` gate in standardised units. 0.0 = always in the market.
    threshold: float = 0.0
    structure: str = "out3"
    #: ``+1`` = FOLLOW the data (hot data -> PAY SR3). ``-1`` = FADE.
    direction: int = 1
    #: Signal read at the Friday close, filled at the NEXT session's settle.
    #: 0 is the same-day-fill sensitivity and is never the headline --
    #: ``project_cavf_grid_verdict``: "same-day fills harvest mark noise".
    entry_lag_sessions: int = 1

    # -- the standardisation ---------------------------------------------
    #: Inherited unchanged from ``LeadConfig`` (756bd / 504bd trailing) for the
    #: composite. The sentiment side, used only by ``fit``, uses these.
    sent_z_window_w: int = 52
    sent_z_min_w: int = 26

    # -- costs -----------------------------------------------------------
    #: One-way, per CONTRACT, in bp of rate. ``reference_sfr_fly_conventions``
    #: fixes this at 0.25, so an outright round trip is 0.50bp.
    cost_bp_one_way: float = 0.25

    # -- inference -------------------------------------------------------
    rotation_draws: int = 5000
    seed: int = 20260824

    # ---- derived --------------------------------------------------------
    def lags(self) -> Tuple[int, int]:
        """``(lag_near, lag_far)`` in weeks, from ``(lead_w, horizon_w)``.

        The derivation is in the module docstring. ``lag_far`` is where the
        holding period's START maps to on the data's clock; ``lag_near`` is
        where its END maps to. Both are non-negative by construction, and
        ``lag_near < lag_far`` always, so ``chg`` is never a difference of a
        value with itself.

        ``lead_w = 0`` is the no-lead reading: the near end is today and the far
        end is one holding period ago, i.e. "the direction the data has already
        moved over the same length of time I am about to hold for".
        """
        h = int(self.horizon_w)
        Lw = int(self.lead_w)
        if Lw <= 0:
            return 0, max(h, 1)
        return max(Lw - h, 0), max(Lw, 1)

    def cost_bp_round_trip(self) -> float:
        _, _, n_contracts, bp_scale = STRUCTURES[self.structure]
        return 2.0 * self.cost_bp_one_way * n_contracts / bp_scale

    def cost_bp_one_side(self) -> float:
        """Half a round trip -- what the always-on book pays per side change."""
        return 0.5 * self.cost_bp_round_trip()

    def rng(self, offset: int = 0) -> np.random.Generator:
        return np.random.default_rng(self.seed + offset)

    def label(self) -> str:
        near, far = self.lags()
        return (f"{self.reading}/L{self.lead_w}/h{self.horizon_w}/"
                f"thr{self.threshold:g}/{self.structure}/"
                f"{'follow' if self.direction > 0 else 'fade'}"
                f" [lags {near},{far}]")

    def describe(self) -> pd.DataFrame:
        rows = [{"knob": f.name, "value": getattr(self, f.name)}
                for f in dataclasses.fields(self)]
        near, far = self.lags()
        rows.append({"knob": "(derived) lag_near_w", "value": near})
        rows.append({"knob": "(derived) lag_far_w", "value": far})
        rows.append({"knob": "(derived) cost_bp_round_trip",
                     "value": self.cost_bp_round_trip()})
        return pd.DataFrame(rows)


#: The pre-registered primary cell. Written down before anything ran.
#:
#: ``chg`` because the trade is a bet on a CHANGE in the Fed's tone over the
#: holding period, and a level says nothing about a change; ``lead_w = 0``
#: because the honest starting point is that there is no exploitable lead and
#: the data's own recent direction is all you have -- and because 21 years of
#: FedLock puts any durable lead at +1 to +2 weeks, inside the weekly grid's own
#: resolution; ``horizon_w = 4`` because it is the shortest window over which a
#: committee visibly changes tack and the longest that keeps the trade count up
#: on a short sample; ``threshold = 0.0`` because the user's question is a plain
#: always-on directional rule -- "rec when we expect dovish, pay when we expect
#: hawkish" -- and a threshold is an extra decision the question did not ask for;
#: ``out3`` because the third deferred SR3 is where a repricing of the Fed path
#: shows up with real liquidity and no fixing already inside the window;
#: ``direction = +1`` (FOLLOW) because that is the direction the claim asserts.
PRIMARY = ExpectConfig()


# ==========================================================================
# inputs
# ==========================================================================
def load_composite(lead_cfg: Optional[L.LeadConfig] = None
                   ) -> Tuple[pd.Series, Dict[str, object]]:
    """The weekly (W-FRI) trailing-standardised surprise composite.

    Built by ``fed_sentiment_lead_data`` unchanged and deliberately not forked:
    two daily Citi CESI sub-indices (LABOUR_MARKET and PRICES_OR_MONEY_SUPPLY),
    each trailing-z'd over 756 business days with 504 min periods, equal
    weighted, NaN on any day either leg is missing, then sampled to the last
    daily value in each (Sat..Fri] bin and stamped on the Friday.
    """
    lead_cfg = lead_cfg or L.LeadConfig()
    panel, prov = L.load_surprise_panel()
    L.gate_surprise_sanity(panel, lead_cfg)
    composite, legs = L.build_surprise_composite(panel, lead_cfg)
    zc = L.weekly_last(composite, lead_cfg.week_anchor).rename("z_composite")
    prov = {**prov, "legs": list(legs.columns), "weeks": int(zc.notna().sum())}
    return zc, prov


def load_sentiment(cfg: ExpectConfig, lead_cfg: Optional[L.LeadConfig] = None
                   ) -> Tuple[pd.Series, Dict[str, object]]:
    """The weekly point-in-time Fed sentiment z-score. Only ``fit`` needs it."""
    lead_cfg = lead_cfg or L.LeadConfig()
    zc, _ = load_composite(lead_cfg)
    scores = L.load_fed_scores(lead_cfg)
    start = max(pd.Timestamp(scores["date"].min()),
                pd.Timestamp(zc.dropna().index.min()))
    grid = L.weekly_grid(start, pd.Timestamp(scores["date"].max()),
                         lead_cfg.week_anchor)
    sent = L.sentiment_index(scores, grid, lead_cfg, point_in_time=True)["sentiment"]
    L.gate_no_pre_corpus(sent, lead_cfg)
    zs = L.trailing_z(sent, cfg.sent_z_window_w, cfg.sent_z_min_w)
    return zs.rename("z_sentiment"), {"n_scores": int(len(scores)),
                                      "weeks": int(zs.notna().sum())}


# ==========================================================================
# the signal
# ==========================================================================
def build_signal(zc: pd.Series, cfg: ExpectConfig,
                 zs: Optional[pd.Series] = None) -> pd.Series:
    """The weekly signal ``s``. Positive = expect Fedspeak to turn HAWKISH.

    ``level``  ``s_t = C_{t-near}``      -- where the data stands, on the clock
                                            that maps to the end of the hold.
    ``chg``    ``s_t = C_{t-near} - C_{t-far}``
                                         -- the change in the data over the
                                            window that maps to the hold.
    ``fit``    ``s_t = Shat_t - S_t``    -- the trailing-OLS prediction of the
                                            sentiment index from the lagged
                                            composite, minus where sentiment
                                            actually is. Requires ``zs``.

    Every branch reads only observations at or before ``t``; :func:`gate_trailing_signal`
    is the assertion, not this docstring.
    """
    near, far = cfg.lags()
    if cfg.reading == "level":
        s = zc.shift(near)
    elif cfg.reading == "chg":
        s = zc.shift(near) - zc.shift(far)
    elif cfg.reading == "fit":
        if zs is None:
            raise ValueError("reading='fit' needs the sentiment series")
        idx = zc.index.union(zs.index).sort_values()
        x = zc.reindex(idx).shift(far)          # the composite as sentiment saw it
        xf = zc.reindex(idx).shift(near)        # ... and as it will see it at t+h
        y = zs.reindex(idx)
        fitted_now = _rolling_ols_predict(y, x, x, cfg.reg_window_w,
                                          max(cfg.sent_z_min_w, 12))
        fitted_fwd = _rolling_ols_predict(y, x, xf, cfg.reg_window_w,
                                          max(cfg.sent_z_min_w, 12))
        del fitted_now  # kept for symmetry of the read; the trade is fwd vs actual
        s = fitted_fwd - y
    else:
        raise ValueError(f"unknown reading {cfg.reading!r}; use one of {READINGS}")
    return s.rename("signal").dropna()


def _rolling_ols_predict(y: pd.Series, x: pd.Series, x_at: pd.Series,
                         window: int, min_periods: int) -> pd.Series:
    """``alpha + beta * x_at_t`` where ``(alpha, beta)`` is fitted on the
    TRAILING window of ``(y, x)`` ending at ``t`` inclusive.

    ``x_at`` is evaluated at ``t`` but may be a DIFFERENT lag of the same
    underlying series than the one the regression was fitted on -- that is the
    whole point of ``fit``: fit the relationship on the alignment the lead
    implies, then evaluate it at the reading that maps to the end of the hold.
    """
    df = pd.concat([y.rename("y"), x.rename("x"), x_at.rename("xa")], axis=1)
    yv = df["y"].to_numpy(float)
    xv = df["x"].to_numpy(float)
    av = df["xa"].to_numpy(float)
    out = np.full(len(df), np.nan)
    for i in range(len(df)):
        lo = max(0, i - window + 1)
        ys, xs = yv[lo:i + 1], xv[lo:i + 1]
        ok = np.isfinite(ys) & np.isfinite(xs)
        if ok.sum() < min_periods or not np.isfinite(av[i]):
            continue
        ys, xs = ys[ok], xs[ok]
        xm, ym = xs.mean(), ys.mean()
        vx = float(((xs - xm) ** 2).sum())
        if vx <= 0:
            continue
        beta = float(((xs - xm) * (ys - ym)).sum() / vx)
        out[i] = (ym - beta * xm) + beta * av[i]
    return pd.Series(out, index=df.index)


def gate_trailing_signal(zc: pd.Series, cfg: ExpectConfig, *,
                         probe_dates: Iterable,
                         zs: Optional[pd.Series] = None) -> pd.DataFrame:
    """G-X1 -- truncating the inputs after ``t`` must not move ``s_t``.

    The one testable property of a trailing statistic, applied to the WHOLE
    composition rather than to its parts, because it is the composition that
    feeds a trade. A rolling OLS, a shift and a z-score are each individually
    trailing; assembling them is where a leak gets introduced.
    """
    full = build_signal(zc, cfg, zs)
    rows = []
    for t in probe_dates:
        t = pd.Timestamp(t)
        zs_t = None if zs is None else zs[zs.index <= t]
        cut = build_signal(zc[zc.index <= t], cfg, zs_t)
        if t not in cut.index or t not in full.index:
            continue
        rows.append({"date": t, "truncated": float(cut.loc[t]),
                     "full_history": float(full.loc[t]),
                     "abs_diff": abs(float(cut.loc[t]) - float(full.loc[t]))})
    out = pd.DataFrame(rows)
    if not out.empty:
        worst = float(out["abs_diff"].max())
        assert worst < 1e-9, (
            f"G-X1 FAILED for reading={cfg.reading!r} lead_w={cfg.lead_w}: the "
            f"signal at a date moves when later data is removed (worst |diff| "
            f"{worst:.3e}) -- it is not computable in real time")
    return out


# ==========================================================================
# book A: discrete, non-overlapping trades
# ==========================================================================
def schedule_trades(s: pd.Series, cfg: ExpectConfig,
                    sessions: np.ndarray) -> pd.DataFrame:
    """Non-overlapping trades from the signal.

    Walk the weekly grid; when flat and ``|s| >= threshold``, take the trade,
    hold ``horizon_w`` weeks, go flat, resume looking. One P&L per trade rather
    than an overlapping stream, so a Sharpe computed on them is not quietly
    counting the same week ``h`` times.

    ``side`` is the PRICE side: ``-direction * sign(s)``. With the frozen
    ``direction = +1`` a positive signal (hot data, expect hawkish) gives
    ``side = -1`` = SHORT the future = PAY.
    """
    idx = list(s.index)
    vals = s.to_numpy(float)
    h = int(cfg.horizon_w)
    thr = float(cfg.threshold)
    rows: List[dict] = []
    i = 0
    while i < len(idx):
        v = vals[i]
        if not np.isfinite(v) or abs(v) < thr or v == 0.0:
            i += 1
            continue
        j = i + h
        if j >= len(idx):
            break
        entry = _shift_sessions(sessions, idx[i], cfg.entry_lag_sessions)
        exit_ = _shift_sessions(sessions, idx[j], cfg.entry_lag_sessions)
        if entry is None or exit_ is None or exit_ <= entry:
            i += 1
            continue
        rows.append({"signal_date": idx[i], "exit_signal_date": idx[j],
                     "entry_date": entry, "exit_date": exit_,
                     "signal": float(v),
                     "side": int(-cfg.direction * (1 if v > 0 else -1))})
        i = j
    return pd.DataFrame(rows)


def _shift_sessions(sessions: np.ndarray, on: pd.Timestamp,
                    lag: int) -> Optional[pd.Timestamp]:
    """``lag`` sessions strictly after ``on``; ``lag == 0`` snaps BACK.

    Snapping back at lag 0 is the same-day-fill sensitivity: the entry price
    becomes the very print the signal was computed from.
    """
    if int(lag) <= 0:
        i = int(np.searchsorted(sessions, np.datetime64(on), side="right")) - 1
        return None if i < 0 else pd.Timestamp(sessions[i])
    cur = on
    for _ in range(int(lag)):
        i = int(np.searchsorted(sessions, np.datetime64(cur), side="right"))
        if i >= len(sessions):
            return None
        cur = pd.Timestamp(sessions[i])
    return cur


def price_trades(trades: pd.DataFrame, panel: pd.DataFrame, cfg: ExpectConfig,
                 *, rate: Optional[pd.Series] = None
                 ) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Attach prices and P&L. **Contracts are fixed at the entry session.**

    That fixing is the whole roll story: the symbol is resolved once, at the
    filled entry, and the SAME symbol is read at exit, so no P&L here ever
    differences two contracts. A trade whose contract expires at or before its
    exit is dropped and counted -- not silently rolled.

    ``ois2y`` is not a futures structure: it prices off ``rate`` (percent) with
    ``long = profits when the rate falls``, so that ``side`` means the same
    thing on both legs.
    """
    reasons: Dict[str, int] = {}
    rows: List[dict] = []
    if trades.empty:
        return pd.DataFrame(), {"priced": 0}

    if cfg.structure in NON_FUTURES:
        if rate is None:
            raise RuntimeError(
                f"structure {cfg.structure!r} needs a rate series -- pass "
                f"rate=PX.curve_store_par_rate(2)")
        for _, t in trades.iterrows():
            e, x = pd.Timestamp(t["entry_date"]), pd.Timestamp(t["exit_date"])
            if e not in rate.index or x not in rate.index:
                reasons["no rate mark"] = reasons.get("no rate mark", 0) + 1
                continue
            re_, rx = float(rate.loc[e]), float(rate.loc[x])
            gross = float(t["side"]) * -(rx - re_) * 100.0
            rows.append({**t.to_dict(), "symbols": "OIS2Y",
                         "entry_px": re_, "exit_px": rx,
                         "pnl_bp_gross": gross,
                         "cost_bp": cfg.cost_bp_round_trip(),
                         "pnl_bp": gross - cfg.cost_bp_round_trip()})
        book = pd.DataFrame(rows)
        reasons["priced"] = int(len(book))
        return book, reasons

    ranks, weights, _n, _bp = STRUCTURES[cfg.structure]
    cost = cfg.cost_bp_round_trip()
    for _, t in trades.iterrows():
        e, x = pd.Timestamp(t["entry_date"]), pd.Timestamp(t["exit_date"])
        syms = [PX.rank_symbol(e.date(), r) for r in ranks]
        exp = min(pd.Timestamp(PX.contract_window(sy).end) for sy in syms)
        if exp <= x:
            reasons["contract expires inside the hold"] = reasons.get(
                "contract expires inside the hold", 0) + 1
            continue
        pe = D.structure_price(panel, syms, weights, e)
        pxx = D.structure_price(panel, syms, weights, x)
        if pe is None:
            reasons["no entry settle"] = reasons.get("no entry settle", 0) + 1
            continue
        if pxx is None:
            reasons["no exit settle"] = reasons.get("no exit settle", 0) + 1
            continue
        gross = float(t["side"]) * (pxx - pe) / PX.PX_PER_BP
        rows.append({**t.to_dict(), "symbols": "/".join(syms),
                     "entry_px": pe, "exit_px": pxx,
                     "pnl_bp_gross": gross, "cost_bp": cost,
                     "pnl_bp": gross - cost})
    book = pd.DataFrame(rows)
    reasons["priced"] = int(len(book))
    return book, reasons


# ==========================================================================
# book B: always-on, weekly re-decision
# ==========================================================================
def weekly_book(s: pd.Series, panel: pd.DataFrame, cfg: ExpectConfig,
                sessions: np.ndarray, *, rate: Optional[pd.Series] = None
                ) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """The literal reading of the question: a position, re-decided every week.

    "Receive SR3 when we expect sentiment to go down, pay SR3 when we expect it
    to go up" is a continuously-held position, not a series of discrete bets.
    This builds it, and it is the book whose roll accounting has to be right.

    Each row is ONE week of holding:

    * the side is decided from ``s`` at Friday ``w`` and the position is opened
      at the fill session ``e`` = ``entry_lag_sessions`` after ``w``;
    * the contract is resolved AT ``e`` and the week's P&L is
      ``side * (P[sym, e_next] - P[sym, e]) / 0.01`` -- **the same symbol on
      both ends**, so no week ever differences two contracts;
    * cost is charged only when something actually turns over: a side change, a
      contract change, or opening from flat. Holding the same side in the same
      contract costs nothing, which is the honest accounting for a position you
      simply did not touch.

    The contract change is charged a FULL round trip (close the old, open the
    new) whatever the side does, which is what a roll costs.
    """
    if cfg.structure in NON_FUTURES and rate is None:
        raise RuntimeError(f"structure {cfg.structure!r} needs a rate series")
    ranks, weights, _n, _bp = STRUCTURES[cfg.structure]
    one_side = cfg.cost_bp_one_side()
    thr = float(cfg.threshold)

    reasons: Dict[str, int] = {}
    rows: List[dict] = []
    prev_side = 0
    prev_syms: Optional[str] = None

    weeks = list(s.index)
    vals = s.to_numpy(float)
    for i in range(len(weeks) - 1):
        v = vals[i]
        side = 0
        if np.isfinite(v) and abs(v) >= thr and v != 0.0:
            side = int(-cfg.direction * (1 if v > 0 else -1))

        e = _shift_sessions(sessions, weeks[i], cfg.entry_lag_sessions)
        x = _shift_sessions(sessions, weeks[i + 1], cfg.entry_lag_sessions)
        if e is None or x is None or x <= e:
            reasons["no session pair"] = reasons.get("no session pair", 0) + 1
            continue

        if cfg.structure in NON_FUTURES:
            key = "OIS2Y"
            if e not in rate.index or x not in rate.index:
                reasons["no rate mark"] = reasons.get("no rate mark", 0) + 1
                continue
            pe, pxx = float(rate.loc[e]), float(rate.loc[x])
            gross = side * -(pxx - pe) * 100.0
        else:
            syms = [PX.rank_symbol(e.date(), r) for r in ranks]
            key = "/".join(syms)
            exp = min(pd.Timestamp(PX.contract_window(sy).end) for sy in syms)
            if exp <= x:
                reasons["contract expires inside the week"] = reasons.get(
                    "contract expires inside the week", 0) + 1
                continue
            pe = D.structure_price(panel, syms, weights, e)
            pxx = D.structure_price(panel, syms, weights, x)
            if pe is None or pxx is None:
                reasons["no settle"] = reasons.get("no settle", 0) + 1
                continue
            gross = side * (pxx - pe) / PX.PX_PER_BP

        rolled = prev_syms is not None and key != prev_syms
        turnover = 0.0
        if side != prev_side:
            # close whatever was on (if anything) and open whatever is on now
            turnover += one_side * (abs(prev_side) + abs(side))
        if rolled and prev_side != 0 and side == prev_side:
            # same side, different contract: a full round trip to roll it
            turnover += 2.0 * one_side * abs(side)

        rows.append({"signal_date": weeks[i], "entry_date": e, "exit_date": x,
                     "signal": float(v) if np.isfinite(v) else np.nan,
                     "side": side, "symbols": key, "rolled": bool(rolled),
                     "entry_px": pe, "exit_px": pxx,
                     "pnl_bp_gross": gross, "cost_bp": turnover,
                     "pnl_bp": gross - turnover})
        prev_side, prev_syms = side, key

    book = pd.DataFrame(rows)
    reasons["weeks"] = int(len(book))
    reasons["weeks_in_market"] = int((book["side"] != 0).sum()) if len(book) else 0
    return book, reasons


# ==========================================================================
# roll diagnostics -- the placebo runs before the book
# ==========================================================================
def roll_placebo(panel: pd.DataFrame, weeks: pd.DatetimeIndex,
                 sessions: np.ndarray, rank: int = 3) -> Dict[str, object]:
    """What a NAIVE fixed-rank price column would have booked at the rolls.

    Build the thing this module refuses to build -- a per-rank price series --
    difference it week to week, and split the differences by whether the rank
    changed contract inside the week. The gap between those two groups is the
    fabricated drift that any ``.diff()``-based weekly book is trading.

    Run this FIRST. It is a construction whose answer is known in advance (the
    roll gap must be large and one-signed), so it certifies the measurement
    before the measurement is pointed at the real book.
    """
    marks, syms, entries = [], [], []
    for w in weeks:
        e = _shift_sessions(sessions, w, 1)
        if e is None or e not in panel.index:
            marks.append(np.nan); syms.append(None); entries.append(pd.NaT); continue
        sy = PX.rank_symbol(e.date(), rank)
        v = panel.at[e, sy] if sy in panel.columns else np.nan
        marks.append(float(v) if pd.notna(v) else np.nan)
        syms.append(sy); entries.append(e)
    m = pd.Series(marks, index=weeks)
    sy = pd.Series(syms, index=weeks)
    ent = pd.Series(entries, index=weeks)

    # THE WRONG CONSTRUCTION: difference the rank column week to week. On a roll
    # week that differences two different contracts.
    d_naive = m.diff() / PX.PX_PER_BP

    # THE RIGHT ONE, on the same weeks: the change in the contract that is
    # ACTUALLY HELD over week i, i.e. the contract resolved at week i's own
    # entry session, marked at that session and at the next week's.
    d_true = pd.Series(np.nan, index=weeks)
    idx = list(weeks)
    for i in range(1, len(idx)):
        s_now, e_now, e_prev = sy.iloc[i], ent.iloc[i], ent.iloc[i - 1]
        if s_now is None or pd.isna(e_now) or pd.isna(e_prev):
            continue
        if s_now not in panel.columns:
            continue
        try:
            a = panel.at[e_prev, s_now]
            b = panel.at[e_now, s_now]
        except KeyError:
            continue
        if pd.isna(a) or pd.isna(b):
            continue
        d_true.iloc[i] = (float(b) - float(a)) / PX.PX_PER_BP

    changed = sy != sy.shift(1)
    changed.iloc[0] = False
    both = pd.DataFrame({"d_naive_bp": d_naive, "d_true_bp": d_true,
                         "rolled": changed}).dropna(subset=["d_naive_bp"])
    roll = both.loc[both["rolled"]]
    flat = both.loc[~both["rolled"]]
    fabricated = (roll["d_naive_bp"] - roll["d_true_bp"]).dropna()
    out = {
        "rank": rank,
        "weeks": int(len(both)),
        "roll_weeks": int(len(roll)),
        "naive_roll_mean_bp": float(roll["d_naive_bp"].mean()) if len(roll) else np.nan,
        "naive_flat_mean_bp": float(flat["d_naive_bp"].mean()) if len(flat) else np.nan,
        "naive_roll_abs_median_bp": float(roll["d_naive_bp"].abs().median()) if len(roll) else np.nan,
        "naive_flat_abs_median_bp": float(flat["d_naive_bp"].abs().median()) if len(flat) else np.nan,
        "true_roll_mean_bp": float(roll["d_true_bp"].mean()) if len(roll) else np.nan,
        "true_roll_abs_median_bp": float(roll["d_true_bp"].abs().median()) if len(roll) else np.nan,
        # The gap between the two IS the fabrication: on a non-roll week it is
        # identically zero because the two constructions read the same contract.
        "fabricated_mean_bp": float(fabricated.mean()) if len(fabricated) else np.nan,
        "fabricated_total_bp": float(fabricated.sum()) if len(fabricated) else np.nan,
        "fabricated_on_flat_weeks_bp": float(
            (flat["d_naive_bp"] - flat["d_true_bp"]).abs().max()) if len(flat) else np.nan,
        "series": both,
    }
    # Known-answer half: on weeks the rank did NOT change, the naive and the true
    # construction must agree exactly. If they do not, this measuring tool is
    # broken and nothing it says about the roll weeks can be trusted.
    assert_flat_weeks_agree(both)
    return out


def assert_flat_weeks_agree(both: pd.DataFrame, *, tol: float = 1e-9) -> float:
    """The placebo's known-answer half, extracted so it can be tested directly.

    On a week where the rank pointed at the same contract as the week before,
    "difference the rank column" and "difference the held contract" are the SAME
    arithmetic and must agree bit for bit. A disagreement there is a defect in
    the measurement -- an off-by-one between the mark dates and the symbol
    dates, most likely -- and it would silently rescale the roll-week number
    this placebo exists to produce.

    Returns the worst absolute disagreement on flat weeks.
    """
    flat = both.loc[~both["rolled"]]
    if flat.empty:
        return 0.0
    worst = float((flat["d_naive_bp"] - flat["d_true_bp"]).abs().max())
    assert not np.isfinite(worst) or worst < tol, (
        f"roll_placebo is broken: naive and true differ by {worst:.3e}bp on a "
        f"week with no contract change -- that is the measurement, not the market")
    return worst


def gate_no_roll_jump(book: pd.DataFrame, *, name: str = "book",
                      panel: Optional[pd.DataFrame] = None) -> Dict[str, object]:
    """G-X3 -- no row of a priced book may span two different contracts.

    The discrete book resolves one symbol at entry and reuses it at exit; the
    weekly book resolves one symbol per week. Either way the invariant is the
    same, and with ``panel`` supplied it is CHECKED against the settle panel
    rather than asserted in prose: for every row, ``entry_px`` must be the named
    contract's mark on the entry session and ``exit_px`` that same contract's
    mark on the exit session. A row whose two marks came from two contracts
    fails here.

    The failure this closes is not hypothetical. On the real panel the naive
    fixed-rank construction has a signed mean weekly change of about +4.6bp on
    roll weeks against -0.8bp otherwise; :func:`roll_placebo` measures it. A
    caller who post-processes a book by netting consecutive rows re-introduces
    exactly that inter-contract gap, and nothing else in the pipeline would say
    so.
    """
    if book is None or book.empty:
        return {"rows": 0, "checked": False}
    assert "symbols" in book.columns, f"{name}: no symbols column to check"
    bad = int(book["symbols"].isna().sum())
    assert bad == 0, f"G-X3 FAILED: {bad} rows in {name} carry no contract"
    out: Dict[str, object] = {"rows": int(len(book)), "checked": True,
                              "distinct_contracts": int(book["symbols"].nunique())}

    if panel is not None:
        worst = 0.0
        n_checked = 0
        for _, r in book.iterrows():
            syms = str(r["symbols"]).split("/")
            if any(s not in panel.columns for s in syms):
                continue           # ois2y, or a leg outside this panel
            e, x = pd.Timestamp(r["entry_date"]), pd.Timestamp(r["exit_date"])
            if e not in panel.index or x not in panel.index:
                continue
            # single-leg rows only: a multi-leg quote is a weighted sum and the
            # per-leg identity is what price_trades already enforces.
            if len(syms) != 1:
                continue
            pe, pxx = panel.at[e, syms[0]], panel.at[x, syms[0]]
            if pd.isna(pe) or pd.isna(pxx):
                continue
            worst = max(worst, abs(float(r["entry_px"]) - float(pe)),
                        abs(float(r["exit_px"]) - float(pxx)))
            n_checked += 1
        out["marks_checked"] = n_checked
        out["worst_mark_diff"] = worst
        assert worst < 1e-9, (
            f"G-X3 FAILED in {name}: a row's marks do not both come from the "
            f"contract it names (worst |diff| {worst:.3e}) -- the P&L spans two "
            f"contracts and is carrying a roll jump")

    if "rolled" in book.columns:
        out["roll_weeks"] = int(book["rolled"].sum())
        rolled = book.loc[book["rolled"]]
        if len(rolled):
            out["roll_mean_gross_bp"] = float(rolled["pnl_bp_gross"].mean())
            out["flat_mean_gross_bp"] = float(
                book.loc[~book["rolled"], "pnl_bp_gross"].mean())
    return out


def gate_fill_is_next_session(sessions: np.ndarray, cfg: ExpectConfig,
                              *, probe_weeks: Sequence[pd.Timestamp]
                              ) -> pd.DataFrame:
    """G-X2 -- with ``entry_lag_sessions >= 1`` the fill is strictly AFTER the
    Friday the signal is read from.

    A fill on the signal session lets the entry price be the very print the
    signal was computed from. This desk has already paid for that
    (``project_cavf_grid_verdict``: same-day fills harvest mark noise), so the
    property is asserted rather than assumed.
    """
    rows = []
    for w in probe_weeks:
        e = _shift_sessions(sessions, pd.Timestamp(w), cfg.entry_lag_sessions)
        rows.append({"signal_friday": pd.Timestamp(w), "fill": e,
                     "strictly_after": (e is not None and e > pd.Timestamp(w))})
    out = pd.DataFrame(rows)
    if cfg.entry_lag_sessions >= 1 and len(out):
        assert bool(out["strictly_after"].all()), (
            "G-X2 FAILED: a fill landed on or before the signal Friday with "
            f"entry_lag_sessions={cfg.entry_lag_sessions}")
    return out


# ==========================================================================
# scoring
# ==========================================================================
def score_trades(book: pd.DataFrame, *, weeks_per_trade: float) -> Dict[str, float]:
    """Per-trade statistics for the discrete book, annualised by FREQUENCY.

    ``52 / weeks_per_trade`` rather than 252: a book that is flat between trades
    earns per year of running it, not per year of a daily strategy with the
    same per-observation Sharpe.
    """
    if book is None or book.empty:
        return {"trades": 0, "avg_bp": np.nan, "gross_avg_bp": np.nan,
                "total_bp": np.nan, "hit": np.nan, "sharpe": np.nan,
                "sharpe_ann": np.nan, "t_stat": np.nan}
    p = book["pnl_bp"].to_numpy(float)
    sd = float(p.std(ddof=1)) if len(p) > 1 else np.nan
    sr = float(p.mean() / sd) if sd and np.isfinite(sd) and sd > 0 else np.nan
    per_year = 52.0 / float(weeks_per_trade)
    return {"trades": int(len(p)), "avg_bp": float(p.mean()),
            "gross_avg_bp": float(book["pnl_bp_gross"].mean()),
            "total_bp": float(p.sum()), "hit": float((p > 0).mean()),
            "sharpe": sr,
            "sharpe_ann": sr * np.sqrt(per_year) if np.isfinite(sr) else np.nan,
            "t_stat": float(p.mean() / (sd / np.sqrt(len(p))))
            if sd and sd > 0 else np.nan}


def score_weekly(book: pd.DataFrame) -> Dict[str, float]:
    """Weekly-book statistics. The Sharpe is annualised by ``sqrt(52)``.

    ``weeks_in_market`` and ``turnover_bp`` travel with every row because an
    always-on book's cost is a function of how often it changes its mind, and a
    reader comparing it to the discrete book needs both numbers to do that.
    """
    if book is None or book.empty:
        return {"weeks": 0, "weeks_in_market": 0, "avg_bp": np.nan,
                "total_bp": np.nan, "hit": np.nan, "sharpe_ann": np.nan,
                "t_stat": np.nan, "gross_total_bp": np.nan, "turnover_bp": np.nan,
                "max_dd_bp": np.nan}
    p = book["pnl_bp"].to_numpy(float)
    sd = float(p.std(ddof=1)) if len(p) > 1 else np.nan
    sr = float(p.mean() / sd) if sd and np.isfinite(sd) and sd > 0 else np.nan
    eq = np.cumsum(p)
    dd = float((eq - np.maximum.accumulate(eq)).min()) if len(eq) else np.nan
    live = book.loc[book["side"] != 0, "pnl_bp"].to_numpy(float)
    return {"weeks": int(len(p)),
            "weeks_in_market": int((book["side"] != 0).sum()),
            "avg_bp": float(p.mean()),
            "avg_bp_in_market": float(live.mean()) if len(live) else np.nan,
            "total_bp": float(p.sum()),
            "gross_total_bp": float(book["pnl_bp_gross"].sum()),
            "turnover_bp": float(book["cost_bp"].sum()),
            "hit": float((live > 0).mean()) if len(live) else np.nan,
            "sharpe_ann": sr * np.sqrt(52.0) if np.isfinite(sr) else np.nan,
            "t_stat": float(p.mean() / (sd / np.sqrt(len(p))))
            if sd and sd > 0 else np.nan,
            "max_dd_bp": dd}


def episodes(book: pd.DataFrame, gap_weeks: int = 8) -> pd.DataFrame:
    """Label rows into EPISODES -- runs of the same side, close together.

    A signal built from a heavily standardised macro series does not change its
    mind weekly; it holds a view for months. A book of 40 trades living in four
    episodes has an effective sample of four, and any statistic computed as if
    it had forty describes something that does not exist.
    """
    if book is None or book.empty:
        return pd.DataFrame(columns=["episode"])
    b = book.sort_values("entry_date").reset_index(drop=True).copy()
    ep, cur = [], 0
    prev_side, prev_date = None, None
    for _, r in b.iterrows():
        if r["side"] == 0:
            ep.append(np.nan)
            continue
        gap = ((pd.Timestamp(r["entry_date"]) - prev_date).days / 7.0
               if prev_date is not None else np.inf)
        if prev_side is None or r["side"] != prev_side or gap > gap_weeks:
            cur += 1
        ep.append(cur)
        prev_side, prev_date = r["side"], pd.Timestamp(r["entry_date"])
    b["episode"] = ep
    return b


# ==========================================================================
# inference
# ==========================================================================
def rotation_offsets(n: int, max_lag: int, max_h: int) -> np.ndarray:
    """The legal circular rotations of a signal against a return series.

    Only ``n - 2*min_offset`` distinct rotations exist, and ``min_offset`` must
    exceed twice the widest alignment the analysis searches, or a rotation can
    reproduce the true alignment and the p-value stops measuring effect size
    and starts measuring where the argmax sits
    (``reference_rotation_null_self_match``).
    """
    min_offset = 2 * (int(max_lag) + int(max_h)) + 1
    if n <= 2 * min_offset:
        return np.array([], dtype=int)
    return np.arange(min_offset, n - min_offset + 1, dtype=int)


def rotation_null(signal: pd.Series, score_fn, *, max_lag: int, max_h: int,
                  draws: int, rng: np.random.Generator) -> Dict[str, object]:
    """Rotate the SIGNAL against the calendar and re-score, keeping the search.

    Rotating the real path keeps its trend, persistence, variance and marginals
    exactly and destroys only the alignment with the price -- which is the null
    a lead claim needs. ``score_fn(rotated_series) -> float`` must perform the
    SAME searched maximum the real analysis takes, or the null is scored on a
    weaker statistic than the observation.

    The reference set is finite and is enumerated in full when it fits the
    budget; ``p_floor = 1 / (used + 1)`` is reported rather than hidden.
    """
    v = signal.to_numpy(float)
    n = len(v)
    offs = rotation_offsets(n, max_lag, max_h)
    if offs.size == 0:
        return {"n_offsets": 0, "stats": np.array([]), "p_floor": np.nan,
                "note": "sample too short for any legal rotation"}
    if offs.size > draws:
        offs = rng.choice(offs, size=draws, replace=False)
    stats = np.empty(offs.size)
    for i, o in enumerate(offs):
        stats[i] = score_fn(pd.Series(np.roll(v, int(o)), index=signal.index))
    return {"n_offsets": int(offs.size), "stats": stats,
            "p_floor": 1.0 / (offs.size + 1.0),
            "enumerated": bool(offs.size == rotation_offsets(n, max_lag, max_h).size)}


def rotation_pvalue(observed: float, null: Dict[str, object]) -> float:
    st = np.asarray(null.get("stats", []), dtype=float)
    st = st[np.isfinite(st)]
    if st.size == 0 or not np.isfinite(observed):
        return np.nan
    return float((1 + np.sum(st >= observed)) / (st.size + 1))


def sign_flip_pvalue(pnl: Sequence[float], *, draws: int = 20000,
                     rng: Optional[np.random.Generator] = None) -> float:
    """Two-sided sign-flip permutation on the realised P&Ls.

    Secondary, always. It treats every trade as independent, and this signal
    moves in multi-month episodes, so it overstates. Report it beside the
    episode count, never instead of the rotation p.
    """
    p = np.asarray([x for x in pnl if np.isfinite(x)], dtype=float)
    if p.size < 3:
        return np.nan
    rng = rng or np.random.default_rng(0)
    obs = abs(float(p.mean()))
    sims = np.abs((rng.choice([-1.0, 1.0], size=(draws, p.size)) * p).mean(axis=1))
    return float((1 + np.sum(sims >= obs)) / (draws + 1))


def expected_max_sharpe(sr_variance: float, n_trials: int) -> float:
    """``E[max Sharpe]`` under the null over ``n_trials`` independent trials.

    Bailey/Lopez de Prado's SR* -- the bar a searched winner has to clear before
    it means anything. Transcribed rather than imported so this module does not
    depend on the intraday backtest package.
    """
    if n_trials < 2 or not np.isfinite(sr_variance) or sr_variance <= 0:
        return 0.0
    from scipy.stats import norm

    gamma = 0.5772156649015329
    e = 1.0 - 1.0 / n_trials
    z1 = norm.ppf(e) if 0 < e < 1 else 0.0
    z2 = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return float(np.sqrt(sr_variance) * ((1 - gamma) * z1 + gamma * z2))


def deflated_sharpe(returns: np.ndarray, sr_star: float) -> float:
    """P(true SR > 0 | observed SR, skew, kurtosis, n, SR*). Bailey/LdP."""
    r = np.asarray([x for x in np.asarray(returns, float) if np.isfinite(x)])
    n = r.size
    if n < 8:
        return np.nan
    sd = r.std(ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return np.nan
    sr = r.mean() / sd
    z = (r - r.mean()) / sd
    skew = float((z ** 3).mean())
    kurt = float((z ** 4).mean())
    denom = np.sqrt(max(1e-12, 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr ** 2))
    from scipy.stats import norm

    return float(norm.cdf((sr - sr_star) * np.sqrt(n - 1) / denom))


# ==========================================================================
# sensitivities
# ==========================================================================
def vintage_sensitivity(zc: pd.Series, cfg: ExpectConfig, panel: pd.DataFrame,
                        sessions: np.ndarray, *, extra_weeks: Sequence[int] = (0, 1, 2),
                        rate: Optional[pd.Series] = None,
                        zs: Optional[pd.Series] = None,
                        support: Optional[pd.DatetimeIndex] = None) -> pd.DataFrame:
    """Re-run the book with the composite delayed an extra ``d`` weeks.

    The Citi snapshot is ONE vintage: it carries only today's read of every
    daily surprise value, and Citi revises and rebases. There is no publication
    axis on the surprise side to gate against, so the exposure cannot be
    removed -- it can only be bounded. A revision published within a week or
    two of the observation cannot help a book that is only allowed to read the
    composite as it stood two weeks earlier. If the edge survives ``d = 2`` it
    is not living on a revision; if it dies, the headline was.
    """
    rows = []
    for d in extra_weeks:
        s = build_signal(zc.shift(int(d)), cfg, zs)
        if support is not None:
            # Run on the SAME weeks the headline ran on. Without this the
            # sensitivity silently spans a different (longer) sample and its
            # trade count does not match the cell it is a sensitivity FOR --
            # measured: 109 trades against the headline's 30.
            s = s.reindex(support).dropna()
        tr = schedule_trades(s, cfg, sessions)
        book, _r = price_trades(tr, panel, cfg, rate=rate)
        st = score_trades(book, weeks_per_trade=float(cfg.horizon_w))
        rows.append({"extra_delay_w": int(d), **st})
    return pd.DataFrame(rows)
