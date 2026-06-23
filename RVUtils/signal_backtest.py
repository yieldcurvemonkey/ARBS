"""Signal -> Position -> Backtest builder for rates relative-value.

Data-agnostic closure-factory (pure pandas/numpy, no pricing/IO).
Mirrors the pca_rv.py builder style.

Usage
-----
    forecast, zscore_signal, position, pnl, stats, ex_ante_sharpe, \
        first_passage, regime_gate, get_data = \
        make_signal_backtest_builder(signal, ret=ret, periods_per_year=252)

    # Carver-style forecast
    fc = forecast(scale=10.0, cap=20.0)

    # Mean-reversion z-score position series in {-1, 0, +1}
    pos = zscore_signal(window=60, entry=2.0, exit=0.5, stop=4.0)

    # Vol-targeted position (Carver)
    pos = position(method="vol_target", target_vol=0.10)

    # P&L series (no look-ahead: shift(1))
    p = pnl(pos, cost_bps=1.0)

    # Performance dictionary
    s = stats(pos, cost_bps=1.0)

    # OU-based ex-ante Sharpe
    sr = ex_ante_sharpe(horizon=21)

    # Expected first-passage time in business days
    fpt = first_passage(target=0.0, sims=2000, steps=252)

    # Tuckman macro gating
    gated = regime_gate(pos, regime_series, allowed=["expansion"])

    signal, ret = get_data()

Notes on forecast mean
-----------------------
The `scale` factor in `forecast()` is divided by ``mean(|signal|)`` computed
over the *full sample* (static, not rolling). This matches Carver (2022)
"Systematic Trading" Sec. 5.3 where the forecast scalar is calibrated once on
all available history.  Consequently forecasts may look slightly different on
subsamples.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from RVUtils.mean_reversion import calibrate_ou, ou_ex_ante_sharpe, first_passage_time


def make_signal_backtest_builder(
    signal: pd.Series,
    *,
    ret: pd.Series | None = None,
    periods_per_year: int = 252,
):
    """Build a closure-based signal backtest toolkit.

    Parameters
    ----------
    signal : pd.Series
        The tradable level / spread (e.g. a fly residual or z-scorable spread).
    ret : pd.Series | None
        Per-period P&L of being LONG one unit of the structure.
        Defaults to ``signal.diff()``.
    periods_per_year : int
        Trading periods per year (252 for daily, 52 for weekly, 12 for monthly).

    Returns
    -------
    tuple of 9 callables:
        (forecast, zscore_signal, position, pnl, stats,
         ex_ante_sharpe, first_passage, regime_gate, get_data)
    """
    signal = pd.Series(signal).copy()
    if ret is None:
        ret = signal.diff()
    else:
        ret = pd.Series(ret).copy()

    _ppy = int(periods_per_year)

    # ── forecast ────────────────────────────────────────────────────────────

    def forecast(scale: float = 10.0, cap: float = 20.0, reversion: bool = False, window=None) -> pd.Series:
        """Carver-style forecast = clip(scale * signal / mean(|signal|), -cap, +cap).

        Sign convention: by default the forecast is MOMENTUM-signed (positive
        forecast => long the structure, same sign as `signal`). For a
        mean-reversion RV signal pass ``reversion=True`` to flip the sign so a
        cheap/low spread maps to a positive/long forecast, matching the
        ``zscore_signal`` convention used elsewhere in this module.

        ``window=None`` uses the full-sample ``mean(|signal|)`` (the static Carver
        scalar; mildly forward-looking in *magnitude* only). Pass an int
        ``window`` for a causal trailing ``mean(|signal|)`` with no look-ahead.
        """
        if window is None:
            mean_abs = float(signal.abs().mean())
            denom = mean_abs if mean_abs != 0.0 else np.nan
            raw = scale * signal / denom
        else:
            ma = signal.abs().rolling(int(window), min_periods=max(2, int(window) // 2)).mean()
            raw = scale * signal / ma.replace(0.0, np.nan)
        if reversion:
            raw = -raw
        out = raw.clip(-cap, cap)
        out.name = "forecast"
        return out

    # ── zscore_signal ────────────────────────────────────────────────────────

    def zscore_signal(
        window: int = 60,
        entry: float = 2.0,
        exit: float = 0.5,
        stop: float = 4.0,
    ) -> pd.Series:
        """Mean-reversion z-score position series in {-1, 0, +1}.

        Convention (mean-reversion):
          z >= +entry  -> SHORT (-1)  [spread rich, fade it]
          z <= -entry  -> LONG  (+1)  [spread cheap, buy it]
          |z| <= exit  -> FLAT  (0)   [take profit / exit]
          |z| >= stop  -> FLAT  (0)   [stop-loss / force-close]

        Implemented as a stateful forward pass (no look-ahead).
        """
        r = signal.rolling(int(window))
        z = (signal - r.mean()) / r.std(ddof=1)
        z_vals = z.values
        n = len(z_vals)
        pos = np.zeros(n)
        current = 0  # current position

        for i in range(n):
            zi = z_vals[i]
            if np.isnan(zi):
                pos[i] = 0
                continue
            # Stop-loss: force-close regardless of current position
            if abs(zi) >= stop:
                current = 0
            # Exit (take profit): close when |z| <= exit
            elif abs(zi) <= exit:
                current = 0
            # Entry signals (only when flat)
            elif current == 0:
                if zi >= entry:
                    current = -1  # spread rich -> short
                elif zi <= -entry:
                    current = 1   # spread cheap -> long
            # Remain in existing position otherwise
            pos[i] = current

        return pd.Series(pos, index=signal.index, name="zscore_pos")

    # ── position ────────────────────────────────────────────────────────────

    def position(
        method: str = "vol_target",
        target_vol: float = 0.10,
        vol_window: int = 36,
        idm: float = 1.0,
        cap_idm: float = 2.5,
        signal_pos: pd.Series | None = None,
        reversion: bool = False,
        forecast_window=None,
    ) -> pd.Series:
        """Size a position from the signal.

        method="binary"
            Sign-based position from ``zscore_signal()`` (or ``signal_pos``
            if provided) -- already mean-reversion-signed.

        method="vol_target"  (Carver)
            (forecast / 10) * (target_vol / realized_vol) * min(idm, cap_idm)
            where ``realized_vol = rolling_std(ret) * sqrt(periods_per_year)``.

        method="inverse_vol"
            sign(forecast) * (target_vol / realized_vol) * min(idm, cap_idm)

        ``reversion``/``forecast_window`` are forwarded to ``forecast()`` for the
        vol_target/inverse_vol methods (which inherit the forecast's sign sense:
        momentum unless ``reversion=True``).
        """
        eff_idm = min(float(idm), float(cap_idm))

        if method == "binary":
            base = signal_pos if signal_pos is not None else zscore_signal()
            out = pd.Series(base, index=signal.index, name="position").reindex(signal.index)
            return out

        # Realized vol (annualised)
        rvol = ret.rolling(int(vol_window)).std(ddof=1) * np.sqrt(_ppy)
        rvol = rvol.replace(0.0, np.nan)

        if method == "vol_target":
            fc = forecast(scale=10.0, cap=20.0, reversion=reversion, window=forecast_window)
            raw = (fc / 10.0) * (target_vol / rvol) * eff_idm
        elif method == "inverse_vol":
            fc = forecast(scale=10.0, cap=20.0, reversion=reversion, window=forecast_window)
            raw = np.sign(fc) * (target_vol / rvol) * eff_idm
        else:
            raise ValueError(f"Unknown method: {method!r}. Use 'binary', 'vol_target', or 'inverse_vol'.")

        # Forward-fill so positions persist through missing vol windows
        raw = raw.ffill()
        raw.name = "position"
        return raw

    # ── pnl ─────────────────────────────────────────────────────────────────

    def pnl(positions: pd.Series, cost_bps: float = 0.0) -> pd.Series:
        """Compute daily P&L series.

        pnl_t = positions_{t-1} * ret_t - turnover_t * (cost_bps / 1e4)

        where turnover_t = |positions_t - positions_{t-1}|.

        No look-ahead: positions are shifted by 1 before multiplying ret.
        """
        pos = pd.Series(positions, index=signal.index).reindex(signal.index)
        pos_lag = pos.shift(1)
        gross = pos_lag * ret.reindex(signal.index)
        if cost_bps != 0.0:
            turnover = pos.diff().abs()
            cost = turnover * (float(cost_bps) / 1e4)
            p = gross - cost
        else:
            p = gross
        p.name = "pnl"
        return p

    # ── stats ────────────────────────────────────────────────────────────────

    def stats(
        positions: pd.Series | None = None,
        cost_bps: float = 0.0,
    ) -> dict:
        """Compute performance statistics.

        Parameters
        ----------
        positions : pd.Series | None
            If None, uses binary position from ``zscore_signal()``.
        cost_bps : float
            Transaction cost in basis points (for ``sharpe_net`` and PnL).

        Returns
        -------
        dict with keys:
            sharpe       — annualised Sharpe (gross, cost_bps=0)
            t_stat       — mean / (std / sqrt(n))  over non-NaN pnl
            hit_rate     — fraction of non-zero pnl days with pnl > 0
            max_dd       — maximum drawdown (<= 0) of cumulative pnl
            turnover     — total |pos.diff()| / years
            avg_hold     — periods / number_of_position_changes
            sharpe_net   — annualised Sharpe using cost_bps
        """
        if positions is None:
            positions = zscore_signal()

        pos = pd.Series(positions)

        # Gross pnl (zero cost) for Sharpe
        p_gross = pnl(pos, cost_bps=0.0).dropna()
        # Net pnl (with cost)
        p_net = pnl(pos, cost_bps=cost_bps).dropna()

        n = len(p_gross)
        if n < 2:
            nan = float("nan")
            return {k: nan for k in ("sharpe", "t_stat", "hit_rate", "max_dd",
                                      "turnover", "avg_hold", "sharpe_net")}

        mu_g = float(p_gross.mean())
        sd_g = float(p_gross.std(ddof=1))
        sharpe_gross = (mu_g / sd_g * np.sqrt(_ppy)) if sd_g > 0 else float("nan")

        mu_n = float(p_net.mean())
        sd_n = float(p_net.std(ddof=1))
        sharpe_net = (mu_n / sd_n * np.sqrt(_ppy)) if sd_n > 0 else float("nan")

        t_stat = (mu_g / (sd_g / np.sqrt(n))) if sd_g > 0 else float("nan")

        non_zero = p_gross[p_gross != 0]
        hit_rate = float((non_zero > 0).mean()) if len(non_zero) > 0 else 0.0

        cum = p_gross.cumsum()
        max_dd = float((cum - cum.cummax()).min())

        years = n / _ppy
        pos_aligned = pos.reindex(p_gross.index)
        turnover = float(pos_aligned.diff().abs().sum()) / max(years, 1e-9)

        changes = (pos_aligned.diff() != 0).sum()
        avg_hold = float(n / changes) if changes > 0 else float(n)

        return {
            "sharpe": sharpe_gross,
            "t_stat": t_stat,
            "hit_rate": hit_rate,
            "max_dd": max_dd,
            "turnover": turnover,
            "avg_hold": avg_hold,
            "sharpe_net": sharpe_net,
        }

    # ── ex_ante_sharpe ───────────────────────────────────────────────────────

    def ex_ante_sharpe(x0: float | None = None, horizon: int = 21) -> float:
        """OU-based ex-ante Sharpe ratio.

        Calibrates an OU process to ``signal``, then computes the conditional
        expected Sharpe over ``horizon`` periods.

        Parameters
        ----------
        x0 : float | None
            Starting value. Defaults to the last non-NaN value of ``signal``.
        horizon : int
            Forward horizon in periods.
        """
        params = calibrate_ou(signal)
        if x0 is None:
            last = signal.dropna()
            x0 = float(last.iloc[-1]) if len(last) > 0 else float(params.get("mu", 0.0))
        return ou_ex_ante_sharpe(float(x0), params, float(horizon), periods=_ppy)

    # ── first_passage ────────────────────────────────────────────────────────

    def first_passage(
        target: float,
        x0: float | None = None,
        sims: int = 2000,
        steps: int = 252,
    ) -> float:
        """Monte-Carlo expected first-passage time in periods.

        Parameters
        ----------
        target : float
            The level the spread must reach (e.g. the OU mean).
        x0 : float | None
            Starting value. Defaults to last non-NaN signal.
        sims : int
            Number of Monte-Carlo paths.
        steps : int
            Maximum simulation steps (paths not reaching target by step `steps`
            contribute `steps` to the average).
        """
        params = calibrate_ou(signal)
        if x0 is None:
            last = signal.dropna()
            x0 = float(last.iloc[-1]) if len(last) > 0 else float(params.get("mu", 0.0))
        return first_passage_time(float(x0), float(target), params, sims=sims, steps=steps)

    # ── regime_gate ──────────────────────────────────────────────────────────

    def regime_gate(
        positions: pd.Series,
        regime: pd.Series,
        allowed: list,
    ) -> pd.Series:
        """Tuckman macro gating: zero position where regime not in `allowed`.

        Parameters
        ----------
        positions : pd.Series
            Position series to gate.
        regime : pd.Series
            Series of regime labels aligned to (or a subset of) positions.index.
        allowed : list
            Regime labels that permit a non-zero position.
        """
        pos = pd.Series(positions).copy()
        reg = pd.Series(regime).reindex(pos.index)
        mask = ~reg.isin(allowed)
        pos[mask] = 0.0
        pos.name = "gated_position"
        return pos

    # ── get_data ─────────────────────────────────────────────────────────────

    def get_data():
        """Return the input (signal, ret) tuple."""
        return signal, ret

    return (
        forecast,
        zscore_signal,
        position,
        pnl,
        stats,
        ex_ante_sharpe,
        first_passage,
        regime_gate,
        get_data,
    )
