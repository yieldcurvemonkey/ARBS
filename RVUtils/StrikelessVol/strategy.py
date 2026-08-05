"""The conditional two-sided rule: valuation sets the sign, drift can veto it,
the RV residual sets the size, and the short-convexity side is gated.

Nothing here is a constant of nature. Every threshold is a prior from the
research brief, to be re-estimated per pair in the backtest grid.

Both risk gates fail CLOSED on missing data: a non-finite ``drift_t`` vetoes
a mildly cheap flattener exactly as a large positive ``drift_t`` would, and a
non-finite ``iv_z`` gates the steepener exactly as a spike would. A gate
whose own input is missing cannot confirm the position is safe, so it
defaults to no new risk rather than to "neutral" -- treating NaN as neutral
would silently strip the gate the row needed most.

The rule is STATELESS: ``build_signals`` recomputes ``signal_state``
independently for each row, with no position memory. A position exits
precisely when ``sign`` changes (to flat or to the opposite sign), not when
``residual_z`` decays back through ``z_exit``. ``z_exit`` is reserved for a
future entry/exit hysteresis (enter at ``z_entry``, hold until ``z`` crosses
back through ``z_exit``) that no downstream consumer currently wires up --
Task 18's trade extraction derives episodes purely from ``sign`` transitions.
Do not assume ``z_exit`` does anything until that hysteresis is implemented.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.conventions import FLATTENER, STEEPENER

__all__ = ["SignalConfig", "signal_state", "build_signals"]

REQUIRED_COLUMNS = (
    "be_over_realized", "drift_t", "residual_z", "spread_vol_bp_day", "iv_z",
)


@dataclass(frozen=True)
class SignalConfig:
    """Every field is a prior to be swept in Task 18's grid, not a constant
    of nature.

    ``z_exit`` is reserved, unused config: it names the "exit at 0" leg of
    the research brief's Signal 3 (entries |z| >= 1.5-2, exit at 0), but
    ``signal_state``/``build_signals`` are stateless -- see the module
    docstring -- so no hysteresis is wired to it here or in Task 18's trade
    extraction. It does nothing until that wiring exists.
    """

    be_cheap: float = 0.8
    be_rich: float = 1.2
    be_deep_cheap: float = 0.5  # below this, drift cannot veto
    drift_t_gate: float = 2.0
    z_entry: float = 1.5
    z_exit: float = 0.0  # reserved -- see class docstring; not yet wired
    z_size_cap: float = 3.0
    # Corrected after Task 15: the research brief's 1.65 bp/day was measured at
    # 1.32 on this repo's own spread series. The gap is not an error in either
    # number -- our forwards are re-derived from a log-cubic spline rather than
    # quoted, so the series carries no bid/ask bounce (lag-1 autocorrelation
    # -0.018 against the brief's -0.270), and CostSchedule prices that
    # microstructure separately. Sizing off 1.65 AND charging the cost schedule
    # would double-count it.
    target_vol_bp_day: float = 1.32
    size_cap: float = 1.0
    short_side_enabled: bool = True
    iv_spike_gate_z: float = 2.0
    base_dv01_usd: float = 100_000.0


def signal_state(row: pd.Series, cfg: SignalConfig) -> dict:
    be = float(row["be_over_realized"])
    drift_t = float(row["drift_t"])
    z = float(row["residual_z"])
    sv = float(row["spread_vol_bp_day"])
    iv_z = float(row.get("iv_z", 0.0))

    if not np.isfinite(be):
        return {"sign": 0, "size": 0.0, "reason": "no valuation"}

    if be < cfg.be_cheap:
        sign, reason = FLATTENER, f"BE/RV={be:.2f} cheap"
    elif be > cfg.be_rich:
        sign, reason = STEEPENER, f"BE/RV={be:.2f} rich"
    else:
        return {"sign": 0, "size": 0.0, "reason": f"BE/RV={be:.2f} fair"}

    if sign == FLATTENER and be > cfg.be_deep_cheap:
        if not np.isfinite(drift_t):
            # Fail closed: we cannot confirm the drift gate is safe, so we
            # do not take the position. NaN is not "no drift signal" -- it
            # is "no information", and a missing upstream feature must not
            # silently disable precisely the gate this row needed.
            return {"sign": 0, "size": 0.0,
                    "reason": f"{reason}; drift unconfirmed (NaN) -- fail closed"}
        if drift_t > cfg.drift_t_gate:
            return {"sign": 0, "size": 0.0,
                    "reason": f"{reason}; vetoed by drift t={drift_t:+.1f}"}

    if sign == STEEPENER:
        if not cfg.short_side_enabled:
            return {"sign": 0, "size": 0.0, "reason": f"{reason}; short side disabled"}
        if not np.isfinite(iv_z):
            # Fail closed, same rationale as the drift gate above: a missing
            # iv_z cannot confirm the short-convexity side is safe to hold.
            return {"sign": 0, "size": 0.0,
                    "reason": f"{reason}; iv spike unconfirmed (NaN) -- fail closed"}
        if iv_z > cfg.iv_spike_gate_z:
            return {"sign": 0, "size": 0.0,
                    "reason": f"{reason}; gated by vol spike z={iv_z:+.1f}"}

    if not np.isfinite(z) or abs(z) < cfg.z_entry:
        return {"sign": 0, "size": 0.0, "reason": f"{reason}; |z|={abs(z):.2f} < entry"}

    # size: risk parity on spread vol, scaled by how stretched the residual is
    vol_scale = cfg.target_vol_bp_day / sv if sv > 0 else 0.0
    z_scale = min(abs(z), cfg.z_size_cap) / cfg.z_size_cap
    size = float(min(cfg.size_cap, vol_scale * z_scale))
    return {"sign": sign, "size": size, "reason": f"{reason}; z={z:+.2f}"}


def build_signals(panel: pd.DataFrame, cfg: SignalConfig) -> pd.DataFrame:
    """Lag-1 signals. A row never acts on its own day's information."""
    missing = [c for c in REQUIRED_COLUMNS if c not in panel.columns]
    if missing:
        raise KeyError(f"signal panel missing columns: {missing}")

    lagged = panel.shift(1)
    records = []
    for ts, row in lagged.iterrows():
        if row.isna().all():
            records.append({"sign": 0, "size": 0.0, "reason": "warmup", "dv01_usd": 0.0})
            continue
        st = signal_state(row, cfg)
        st["dv01_usd"] = st["sign"] * st["size"] * cfg.base_dv01_usd
        records.append(st)
    return pd.DataFrame(records, index=panel.index)
