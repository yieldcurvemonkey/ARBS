r"""Signals and episode planning for the CA-vs-fly block.

Everything here is panel arithmetic on two date-indexed series (a CA column and
a fly rate column, both in bp) plus optional overlay series. No market data is
touched; the notebook builds the panels, this module turns them into positions.

Lag discipline — the defect this package has now found twice (a ``bfill`` in a
price panel, an unlagged CFTC report date) — is structural here, not a caller
convention: every estimator output is **shifted one day before it is exposed**,
so the z that decides an entry at *t* is built from parameters estimated
through *t−1* applied to *t*'s own observation. There is no unshifted variant
to reach for.

Two β conventions, per the pre-registration (they are NOT interchangeable and
with a shared convention the two families collapse into the same statistic):

* ``mode="pairs"`` — β from rolling OLS of **ΔCA on Δfly** (hedge-ratio
  semantics); the signal is the frozen-β spread ``CA − β·fly`` z-scored
  against its own rolling mean/sd.
* ``mode="fv"`` — CA regressed on fly in **levels with an intercept**
  (fair-value semantics, Citi's ``CA = α + β·fly``); the signal is the
  regression residual z-scored against its rolling sd
  (``sd_resid = sd_CA·sqrt(1−r²)``, the OLS identity).
* ``mode="ca_only"`` / ``mode="fly_only"`` — attribution controls: the same
  machinery with β pinned to 0 (z of the level itself).

P&L sign convention (verified against the engine in the notebook's sign
probe): a **long-spread** episode (``side=+1``) gains when ``CA − β·fly``
rises; its daily P&L is ``side · (ΔCA − β_entry·Δfly) · ca_dv01``. Long spread
= long CA (sell the pack, receive the matched swap) + short β·fly (receive the
belly); short spread is Citi's book verbatim (buy packs, pay the swap, pay the
belly).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "SignalConfig",
    "Episode",
    "apply_overlay",
    "build_signal_frame",
    "episodes_from_signals",
    "episode_pnl",
    "fill_date",
    "imm_roll_dates",
    "roll_splice",
    "book_equity",
    "positioning_mask",
    "basis_mask",
    "carry_mask",
]

_MODES = ("pairs", "fv", "ca_only", "fly_only")


def imm_roll_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The panel dates on which the front SR3 code has just rolled.

    Delegates the roll rule to the TB's own ``_cvx_front_imm_code`` (roll ON
    the IMM date) — the same function that resolves every label to contracts,
    so the splice and the vocabulary cannot disagree about when a label
    switches windows.
    """
    from TB.IRSwapsTB import _cvx_front_imm_code

    idx = pd.DatetimeIndex(index).sort_values()
    codes = [_cvx_front_imm_code(d.date()) for d in idx]
    rolls = [idx[i] for i in range(1, len(idx)) if codes[i] != codes[i - 1]]
    return pd.DatetimeIndex(rolls)


def roll_splice(series: pd.Series, roll_dates: pd.DatetimeIndex) -> pd.Series:
    """Remove the contract-switching jumps of a constant-rank label series.

    A CM label's level change ACROSS a front-IMM roll is the difference
    between two different windows, not a P&L — and 22 of 33 SR3 rolls land on
    FOMC decision dates, so the jump is systematically signed. The spliced
    series zeroes the roll-date change and backward-adjusts the level: its
    differences are the continuous return stream of holding the rank's window
    and rolling at the IMM date (at zero cost — the engine, holding real
    contracts, prices the roll). The RAW level stays the display quantity;
    this series exists to be diffed and z-scored.
    """
    s = series.dropna().astype(float)
    if s.empty or len(roll_dates) == 0:
        return s
    d = s.diff()
    on_roll = d.index.isin(roll_dates)
    adj = d.where(~on_roll, 0.0)
    out = s.iloc[0] + adj.fillna(0.0).cumsum()
    out.iloc[0] = s.iloc[0]
    return out.rename(series.name)


@dataclass(frozen=True)
class SignalConfig:
    """Knobs of one declared cell. Defaults are the pre-registered primaries."""

    #: rolling window, business-day ROWS, for both β and the z moments. The
    #: row-based-window trap (a "252-day" window spanning 1,289 calendar days)
    #: does not bite here because the CA panel measured 100% dense; the guard
    #: below still refuses a window whose calendar span is pathological.
    window: int = 252
    z_entry: float = 2.0
    z_exit: float = 0.5
    max_hold_bd: int = 63
    #: β gate in bp-per-bp (≡ 1..100 in Citi's bp-per-percent units). A day
    #: outside the gate cannot OPEN a position; it never force-closes one.
    beta_abs_min: float = 0.01
    beta_abs_max: float = 1.0
    #: both sides traded (Citi only ever sold CA; two-sided is declared).
    two_sided: bool = True
    #: refuse windows whose calendar span exceeds this multiple of the nominal
    #: (252 rows ≈ 365 calendar days; 1.5 ⇒ ~550 days).
    max_window_span_ratio: float = 1.5

    def __post_init__(self) -> None:
        if self.z_exit >= self.z_entry:
            raise ValueError(
                f"z_exit {self.z_exit} must sit strictly inside z_entry "
                f"{self.z_entry}, or every entry exits the same day")
        if self.beta_abs_min >= self.beta_abs_max:
            raise ValueError("beta gate is empty")


@dataclass(frozen=True)
class Episode:
    """One held position in one cell."""

    entry: pd.Timestamp
    exit: pd.Timestamp
    side: int                      # +1 long spread, −1 short spread
    beta_entry: float              # frozen at entry, bp per bp (0 for controls)
    z_at_entry: float
    exit_reason: str               # "z_exit" | "max_hold" | "end_of_data"

    @property
    def hold_bd(self) -> int:
        return int(np.busday_count(self.entry.date(), self.exit.date()))


def _check_window_span(idx: pd.DatetimeIndex, window: int, ratio: float) -> None:
    if len(idx) < window + 2:
        return
    spans = (idx[window:] - idx[:-window]).days
    worst = int(np.max(spans))
    nominal = window * 365.25 / 252.0
    if worst > nominal * ratio:
        raise ValueError(
            f"a {window}-row window spans {worst} calendar days "
            f"(> {ratio}x the nominal {nominal:.0f}); the panel has holes and "
            "row-based rolling stats would silently mix regimes")


def build_signal_frame(ca: pd.Series, fly: Optional[pd.Series],
                       cfg: SignalConfig, *, mode: str) -> pd.DataFrame:
    """Date-indexed frame: ``beta``, ``z``, ``gate_ok`` — all decision-ready.

    ``beta`` and the z moments are estimated through *t−1* and applied to
    *t*'s observation; the returned columns need no further shifting.
    ``fly`` may be None only for ``mode="ca_only"``.
    """
    if mode not in _MODES:
        raise ValueError(f"mode {mode!r} not in {_MODES}")
    if mode == "fly_only":
        if fly is None:
            raise ValueError("fly_only needs the fly series")
        ca, fly = fly, None          # the "CA" slot carries the fly level
        mode = "ca_only"
    if mode == "ca_only":
        y = ca.dropna().astype(float)
        _check_window_span(y.index, cfg.window, cfg.max_window_span_ratio)
        mu = y.rolling(cfg.window).mean().shift(1)
        sd = y.rolling(cfg.window).std(ddof=1).shift(1)
        z = (y - mu) / sd.replace(0.0, np.nan)
        out = pd.DataFrame({"beta": 0.0, "z": z})
        out["gate_ok"] = np.isfinite(out["z"])
        return out

    if fly is None:
        raise ValueError(f"mode {mode!r} needs the fly series")
    df = pd.concat([ca.rename("ca"), fly.rename("fly")], axis=1).dropna().astype(float)
    _check_window_span(df.index, cfg.window, cfg.max_window_span_ratio)
    w = cfg.window

    if mode == "pairs":
        d = df.diff()
        cov = d["ca"].rolling(w).cov(d["fly"])
        var = d["fly"].rolling(w).var(ddof=1)
        beta = (cov / var.replace(0.0, np.nan)).shift(1)
        # frozen-β spread, z-scored against the same window's moments under
        # the SAME frozen β: mean/sd of (ca − β·fly) decompose into rolling
        # moments of ca, fly and their cross terms.
        m_ca = df["ca"].rolling(w).mean().shift(1)
        m_fly = df["fly"].rolling(w).mean().shift(1)
        v_ca = df["ca"].rolling(w).var(ddof=1).shift(1)
        v_fly = df["fly"].rolling(w).var(ddof=1).shift(1)
        c_cf = df["ca"].rolling(w).cov(df["fly"]).shift(1)
        spread = df["ca"] - beta * df["fly"]
        mu = m_ca - beta * m_fly
        var_s = v_ca + beta ** 2 * v_fly - 2.0 * beta * c_cf
        sd = np.sqrt(var_s.clip(lower=0.0))
        z = (spread - mu) / sd.replace(0.0, np.nan)
    else:  # fv: levels OLS with intercept
        cov = df["ca"].rolling(w).cov(df["fly"])
        var = df["fly"].rolling(w).var(ddof=1)
        corr = df["ca"].rolling(w).corr(df["fly"])
        m_ca = df["ca"].rolling(w).mean()
        m_fly = df["fly"].rolling(w).mean()
        sd_ca = df["ca"].rolling(w).std(ddof=1)
        beta = (cov / var.replace(0.0, np.nan)).shift(1)
        alpha = (m_ca - (cov / var.replace(0.0, np.nan)) * m_fly).shift(1)
        sd_resid = (sd_ca * np.sqrt((1.0 - corr ** 2).clip(lower=0.0))).shift(1)
        resid = df["ca"] - alpha - beta * df["fly"]
        z = resid / sd_resid.replace(0.0, np.nan)

    out = pd.DataFrame({"beta": beta, "z": z})
    out["gate_ok"] = (np.isfinite(out["z"])
                      & (out["beta"].abs() >= cfg.beta_abs_min)
                      & (out["beta"].abs() <= cfg.beta_abs_max))
    return out


def episodes_from_signals(sig: pd.DataFrame, cfg: SignalConfig) -> List[Episode]:
    """Collapse the daily signal frame into held episodes.

    Entry: flat, ``gate_ok`` and ``|z| ≥ z_entry`` → ``side = −sign(z)``
    (rich spread is sold). Exit: ``|z| ≤ z_exit``, or the hold reaches
    ``max_hold_bd``, or the data ends. One position at a time per cell.
    """
    idx = sig.index
    z = sig["z"].to_numpy()
    beta = sig["beta"].to_numpy()
    ok = sig["gate_ok"].to_numpy()

    out: List[Episode] = []
    in_pos = False
    e_i = 0
    e_side = 0
    e_beta = 0.0
    e_z = float("nan")
    for i in range(len(idx)):
        if not in_pos:
            if not ok[i] or not np.isfinite(z[i]) or abs(z[i]) < cfg.z_entry:
                continue
            side = -int(np.sign(z[i]))
            if side > 0 and not cfg.two_sided:
                continue
            in_pos, e_i, e_side, e_beta, e_z = True, i, side, float(beta[i]), float(z[i])
            continue
        hold = int(np.busday_count(idx[e_i].date(), idx[i].date()))
        if np.isfinite(z[i]) and abs(z[i]) <= cfg.z_exit:
            out.append(Episode(idx[e_i], idx[i], e_side, e_beta, e_z, "z_exit"))
            in_pos = False
        elif hold >= cfg.max_hold_bd:
            out.append(Episode(idx[e_i], idx[i], e_side, e_beta, e_z, "max_hold"))
            in_pos = False
    if in_pos:
        out.append(Episode(idx[e_i], idx[-1], e_side, e_beta, e_z, "end_of_data"))
    return out


def fill_date(idx: pd.DatetimeIndex, decision: pd.Timestamp,
              exec_lag_bd: int) -> Optional[pd.Timestamp]:
    """The mark a decision at *decision* actually transacts at.

    ``exec_lag_bd=1`` is the primary convention: a settle-based signal cannot
    be filled at the settle it was computed from — the first grid pass filled
    same-day and harvested the mark's own measurement noise at a 100% hit
    rate. Returns None when the fill would fall off the end of the data.
    """
    pos = idx.searchsorted(decision) + exec_lag_bd
    if pos >= len(idx):
        return None
    return idx[pos]


def episode_pnl(ep: Episode, ca: pd.Series, fly: Optional[pd.Series],
                ca_dv01: float, *, exec_lag_bd: int = 1) -> pd.Series:
    """Daily P&L of one episode in USD, accrued (entry_fill, exit_fill].

    ``side·(ΔCA − β_entry·Δfly)·ca_dv01``; the controls pass ``beta_entry=0``
    (ca_only) or route the fly through the ``ca`` slot (fly_only), so this one
    expression covers every mode. Fills lag the decision by ``exec_lag_bd``
    marks (default 1 — see :func:`fill_date`); ``exec_lag_bd=0`` reproduces
    the same-day diagnostic.
    """
    idx = ca.dropna().index
    t0 = fill_date(idx, ep.entry, exec_lag_bd)
    t1 = fill_date(idx, ep.exit, exec_lag_bd)
    if t0 is None:
        return pd.Series(dtype=float)
    if t1 is None:
        t1 = idx[-1]
    if t1 <= t0:
        return pd.Series(dtype=float)
    win = ca.loc[t0:t1]
    d = win.diff()
    if fly is not None and ep.beta_entry != 0.0:
        d = d - ep.beta_entry * fly.loc[t0:t1].diff()
    return (ep.side * d.iloc[1:] * ca_dv01).astype(float)


def book_equity(episodes: Sequence[Episode], ca: pd.Series,
                fly: Optional[pd.Series], *, ca_dv01: float,
                index: Optional[pd.DatetimeIndex] = None,
                cost_usd_per_episode: float = 0.0,
                exec_lag_bd: int = 1) -> pd.Series:
    """Cumulative equity of one cell: episode P&L summed onto a daily grid,
    with the round-trip cost charged at each episode's exit FILL."""
    idx = index if index is not None else ca.dropna().index
    daily = pd.Series(0.0, index=idx)
    for ep in episodes:
        p = episode_pnl(ep, ca, fly, ca_dv01, exec_lag_bd=exec_lag_bd)
        daily = daily.add(p, fill_value=0.0)
        if cost_usd_per_episode:
            tx = fill_date(idx, ep.exit, exec_lag_bd) or idx[-1]
            daily.loc[tx] = daily.get(tx, 0.0) - cost_usd_per_episode
    return daily.cumsum()


# ---------------------------------------------------------------------------
# Overlay masks (families C, D, E) — conditioning, never standalone signals
# ---------------------------------------------------------------------------
def positioning_mask(dealer_z: pd.Series, *, z_min: float = 1.0
                     ) -> Callable[[pd.Timestamp, int], bool]:
    """Citi's mechanism sided: short-CA (short spread) only when dealer net is
    stretched LONG (z ≥ +z_min); long-CA only when stretched short. The series
    must already be release-lagged — this function adds no lag of its own and
    says so, because double-lagging is as wrong as not lagging."""
    def ok(t: pd.Timestamp, side: int) -> bool:
        s = dealer_z.dropna()
        if s.empty or t < s.index[0]:
            return False
        v = s.asof(t)
        if not np.isfinite(v):
            return False
        return v >= z_min if side < 0 else v <= -z_min
    return ok


def basis_mask(basis: pd.Series, *, chg_bd: int = 20, min_abs_bp: float = 0.25
               ) -> Callable[[pd.Timestamp, int], bool]:
    """CCP-basis overlay: the 20-day change in the (already market-lagged)
    LCH−CME basis must be at least ``min_abs_bp`` and aligned with the trade
    sign — a widening basis wedge argues the measured CA is drifting rich."""
    chg = (basis - basis.shift(chg_bd)).dropna()

    def ok(t: pd.Timestamp, side: int) -> bool:
        if chg.empty or t < chg.index[0]:
            return False
        v = chg.asof(t)
        if not np.isfinite(v) or abs(v) < min_abs_bp:
            return False
        return v > 0 if side < 0 else v < 0
    return ok


def carry_mask(roll_3m: pd.Series) -> Callable[[pd.Timestamp, int], bool]:
    """RAC overlay: a short-CA entry must carry positively (the screen's own
    3m roll column, ``CA(p) − CA(p−1) > 0``); long-CA entries require the
    opposite. The roll series must be lagged by the caller to t−1.

    An EMPTY roll series refuses every entry rather than raising: rank 1 has
    no nearer window (`Strat2Config` refuses ``rank_start < 2`` for the same
    structural reason), so a WHITES carry overlay can never fire — that is a
    recorded property of the structure, not an error."""
    def ok(t: pd.Timestamp, side: int) -> bool:
        s = roll_3m.dropna()
        if s.empty:
            return False
        v = s.asof(t)
        if not np.isfinite(v):
            return False
        return v > 0 if side < 0 else v < 0
    return ok


def apply_overlay(episodes: Sequence[Episode],
                  mask: Callable[[pd.Timestamp, int], bool]) -> List[Episode]:
    """Filter a base book's episodes on an entry-time overlay mask."""
    return [ep for ep in episodes if mask(ep.entry, ep.side)]
