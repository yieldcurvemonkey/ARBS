r"""GV block — signal frames, roll-segmented episodes, and episode P&L.

The house pattern: signals live strategy-side as a precomputed panel keyed by
(date, structure, leg); the engine owns marks and P&L.  Nothing here reads a
pricer.

Three conventions are load-bearing and each is pinned by a known-answer test:

**Fills lag decisions by one mark.**  The CA mark is a composite of a
17:00-nearest futures bar and a separately-timed swap curve; measured
mark-noise is 0.17-1.13 bp/day against true daily moves of 0.18-0.90.  A z-rule
that enters AT the mark it was computed from buys that noise at a price nobody
can trade.  ``exec_lag_bd=0`` reproduces the same-day diagnostic and must show
an inflated hit rate; that gap is the harvest.

**No position may straddle an IMM roll.**  Episodes live inside the tradeable
segments returned by ``gv_universe.roll_segments``; an open position is
force-closed at the last pre-blackout mark.  With the blackout disabled a
long-CA book must pick up the measured +0.95 bp/roll BLUES artifact — that is
the control which proves the blackout is switched on.

**Signals see the denoised CA; P&L sees the raw one.**  Smoothing a signal is
legitimate, smoothing an execution price is not.  ``build_signal_frame`` takes
both series and never crosses them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV.gv_universe import leg_cost_dv01

__all__ = [
    "SignalConfig",
    "Episode",
    "build_signal_frame",
    "episodes_from_signals",
    "episode_pnl",
    "episode_cost_usd",
    "book_daily",
    "fill_date",
    "inv_vol_scale",
    "FUT_RT_BP",
    "SWAP_RT_BP",
    "LEG_RT_BP",
]

#: Round-trip costs in bp, charged on the relevant DV01 at the unwind.
#: Anchors: CME's 0.5 bp two-way 2y IMM swap quote, the 0.25 bp pack/bundle
#: tick (one package tick regardless of leg count -- CME's own bundle execution
#: economics), 0.5 bp per swap leg of a fly.
FUT_RT_BP = 0.25
SWAP_RT_BP = 0.5
LEG_RT_BP = 0.5


@dataclass(frozen=True)
class SignalConfig:
    z_entry: float = 2.0
    z_exit: float = 0.5
    z_stop: Optional[float] = None
    max_hold_bd: int = 63
    window: int = 252
    min_periods: Optional[int] = None
    exec_lag_bd: int = 1
    #: extra lag applied to the whole signal frame; the placebo runs at 20.
    signal_lag_bd: int = 0


@dataclass
class Episode:
    entry: pd.Timestamp
    exit: pd.Timestamp
    side: int                      # +1 long the spread, -1 short it
    beta_entry: float              # bp of CA per bp of leg, frozen at entry
    ca_dv01: float                 # USD per bp of CA for this episode
    z_entry: float
    exit_reason: str               # "z" | "stop" | "max_hold" | "segment_end"
    segment: int = -1


# ---------------------------------------------------------------------------
def fill_date(index: pd.DatetimeIndex, t: pd.Timestamp, lag: int
              ) -> Optional[pd.Timestamp]:
    """The mark a decision taken on *t* is filled at: *lag* marks later."""
    if t not in index:
        after = index[index >= t]
        if len(after) == 0:
            return None
        t = after[0]
    i = int(index.get_loc(t)) + int(lag)
    return index[i] if 0 <= i < len(index) else None


def build_signal_frame(ca_raw: pd.Series, ca_denoised: pd.Series,
                       leg: pd.Series, beta: pd.Series, gate_ok: pd.Series,
                       *, cfg: SignalConfig) -> pd.DataFrame:
    """The per-date decision inputs.

    ``spread = CA_denoised - beta * leg`` and ``z`` is its own rolling z-score.
    ``beta`` is whatever the declared sizing rule produced, in bp of CA per bp
    of leg; the frame does not know or care which rule it came from.
    """
    idx = ca_raw.dropna().index.intersection(leg.dropna().index)
    f = pd.DataFrame(index=idx)
    f["ca"] = ca_raw.reindex(idx)
    f["ca_dn"] = ca_denoised.reindex(idx)
    f["leg"] = leg.reindex(idx)
    f["beta"] = beta.reindex(idx)
    f["gate_ok"] = gate_ok.reindex(idx).fillna(False).astype(bool)
    f["spread"] = f["ca_dn"] - f["beta"] * f["leg"]
    mp = cfg.min_periods or max(60, cfg.window // 2)
    mu = f["spread"].rolling(cfg.window, min_periods=mp).mean()
    sd = f["spread"].rolling(cfg.window, min_periods=mp).std(ddof=1)
    f["z"] = (f["spread"] - mu) / sd.replace(0.0, np.nan)
    if cfg.signal_lag_bd:
        f[["beta", "gate_ok", "spread", "z"]] = (
            f[["beta", "gate_ok", "spread", "z"]].shift(cfg.signal_lag_bd))
        f["gate_ok"] = f["gate_ok"].astype(object).where(
            f["gate_ok"].notna(), False).astype(bool)
    return f


def episodes_from_signals(frame: pd.DataFrame, cfg: SignalConfig,
                          segments: Sequence[Tuple[pd.Timestamp, pd.Timestamp]],
                          *, ca_dv01_series: Optional[pd.Series] = None,
                          ca_dv01: float = 100_000.0) -> List[Episode]:
    """Run the two-sided z state machine INSIDE each tradeable segment.

    A segment is a stretch between IMM-roll blackouts.  Positions cannot be
    carried across one; a position still open at a segment's last date exits
    there with ``exit_reason="segment_end"``.  Because SR3 rolls quarterly this
    caps every hold at roughly one quarter, which is the brief's "ideally we
    don't have a position on during the roll / we are flat" made mechanical.
    """
    out: List[Episode] = []
    z = frame["z"]
    beta = frame["beta"]
    gate = frame["gate_ok"]
    for si, (a, b) in enumerate(segments):
        win = frame.loc[a:b]
        if win.empty:
            continue
        dates = win.index
        pos = 0
        entry_i = -1
        side = 0
        b_entry = np.nan
        z_ent = np.nan
        for i, t in enumerate(dates):
            zt = z.get(t, np.nan)
            if pos == 0:
                if (np.isfinite(zt) and abs(zt) >= cfg.z_entry
                        and bool(gate.get(t, False))
                        and np.isfinite(beta.get(t, np.nan))):
                    # z high => spread rich => SHORT the spread.
                    side = -1 if zt > 0 else 1
                    pos, entry_i, b_entry, z_ent = side, i, float(beta[t]), float(zt)
                continue
            held = i - entry_i
            reason = None
            if cfg.z_stop is not None and np.isfinite(zt) and abs(zt) >= cfg.z_stop:
                reason = "stop"
            elif np.isfinite(zt) and abs(zt) <= cfg.z_exit:
                reason = "z"
            elif held >= cfg.max_hold_bd:
                reason = "max_hold"
            elif i == len(dates) - 1:
                reason = "segment_end"
            if reason:
                d0 = dates[entry_i]
                d = (float(ca_dv01_series.get(d0, np.nan))
                     if ca_dv01_series is not None else float(ca_dv01))
                if np.isfinite(d) and d > 0:
                    out.append(Episode(d0, t, int(side), b_entry, d,
                                       z_ent, reason, si))
                pos, entry_i, side = 0, -1, 0
    return out


def episode_pnl(ep: Episode, ca_raw: pd.Series, leg_raw: pd.Series,
                *, exec_lag_bd: int = 1) -> pd.Series:
    """Daily USD P&L of one episode, accrued on ``(entry_fill, exit_fill]``.

    ``side * (dCA - beta_entry * dleg) * ca_dv01``.  ``beta_entry`` is frozen at
    entry — the hedge is not re-struck intra-episode, so a rolling beta cannot
    launder a look-ahead into the position.  Both series are the RAW marks.
    """
    idx = ca_raw.dropna().index
    t0 = fill_date(idx, ep.entry, exec_lag_bd)
    t1 = fill_date(idx, ep.exit, exec_lag_bd)
    if t0 is None:
        return pd.Series(dtype=float)
    if t1 is None:
        t1 = idx[-1]
    if t1 <= t0:
        return pd.Series(dtype=float)
    d = ca_raw.loc[t0:t1].diff()
    if ep.beta_entry:
        d = d - ep.beta_entry * leg_raw.reindex(ca_raw.index).loc[t0:t1].diff()
    return (ep.side * d.iloc[1:] * ep.ca_dv01).astype(float)


def episode_cost_usd(ep: Episode, leg_id: Optional[str], *, mult: float = 1.0
                     ) -> float:
    """Round-trip cost of one episode, per leg, on that leg's own DV01.

    The futures package pays ONE package tick regardless of leg count; the
    matched swap pays its own; each fly/curve leg pays 0.5 bp on the DV01 that
    leg actually carries, which for a fly quoted ``2b-f-k`` is **4x** the
    quoted-combination DV01.  This is the term that grows when the hedge is
    re-sized, so it is computed from the same ``leg_dv01`` the P&L uses rather
    than assumed proportional to it.
    """
    if mult == 0.0:
        return 0.0
    ca = float(ep.ca_dv01)
    total = (FUT_RT_BP + SWAP_RT_BP) * ca
    if leg_id is not None and ep.beta_entry:
        total += LEG_RT_BP * leg_cost_dv01(leg_id, abs(ep.beta_entry) * ca)
    return float(mult * total)


def book_daily(episodes: Sequence[Episode], ca_raw: pd.Series,
               leg_raw: pd.Series, *, leg_id: Optional[str],
               index: Optional[pd.DatetimeIndex] = None,
               cost_mult: float = 0.0, exec_lag_bd: int = 1) -> pd.Series:
    """Daily USD P&L of a whole cell (not cumulative), cost charged at the exit
    fill."""
    idx = index if index is not None else ca_raw.dropna().index
    daily = pd.Series(0.0, index=idx)
    for ep in episodes:
        daily = daily.add(episode_pnl(ep, ca_raw, leg_raw,
                                      exec_lag_bd=exec_lag_bd), fill_value=0.0)
        c = episode_cost_usd(ep, leg_id, mult=cost_mult)
        if c:
            tx = fill_date(idx, ep.exit, exec_lag_bd) or idx[-1]
            daily.loc[tx] = daily.get(tx, 0.0) - c
    return daily


def inv_vol_scale(ca_raw: pd.Series, leg_raw: pd.Series, beta: pd.Series,
                  *, base_dv01: float = 100_000.0, window: int = 63,
                  cap: float = 3.0) -> pd.Series:
    """Per-date ``ca_dv01`` under the ``inv_vol`` book-scale rule.

    The pair's realised daily P&L per unit ``ca_dv01`` is ``dCA - beta*dleg``;
    scale so its trailing ``window``-day sd equals the full-sample median of the
    same quantity, capped at ``cap``x.  Uses only trailing information, and the
    normalising median is computed on the SAME trailing series (an expanding
    median), never on the full sample.
    """
    u = (ca_raw.diff() - beta * leg_raw.reindex(ca_raw.index).diff()).abs()
    sd = (ca_raw.diff() - beta * leg_raw.reindex(ca_raw.index).diff()
          ).rolling(window, min_periods=max(20, window // 2)).std(ddof=1)
    target = sd.expanding(min_periods=window).median()
    scale = (target / sd.replace(0.0, np.nan)).clip(upper=cap, lower=1.0 / cap)
    _ = u
    return (base_dv01 * scale).rename("ca_dv01")
