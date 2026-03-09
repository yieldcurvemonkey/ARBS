from __future__ import annotations

import datetime as dt
import math
from typing import Any

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta
from scipy.optimize import brentq
from scipy.stats import norm


def _coerce_datetime(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().replace(tzinfo=None)
    ts = pd.to_datetime(value, errors="raise")
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is not None:
            ts = ts.tz_convert(None)
        return ts.to_pydatetime()
    raise TypeError(f"Unsupported datetime value: {value!r}")


def _clean_numeric(value: Any) -> float:
    if value is None:
        return float("nan")
    if isinstance(value, (int, float, np.integer, np.floating)) and not pd.isna(value):
        return float(value)
    text = str(value).strip()
    if not text:
        return float("nan")
    text = text.replace("$", "").replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    return float(text)


def _normalize_strike(value: Any, notation: Any) -> float:
    strike = _clean_numeric(value)
    notation_value = _clean_numeric(notation)
    if math.isnan(strike):
        return strike
    if not math.isnan(notation_value) and abs(notation_value - 3.0) < 1e-9 and strike >= 1.0:
        return strike / 100.0
    if strike > 1.0:
        return strike / 100.0
    return strike


def _infer_cap_floor_type(trade: dict[str, Any]) -> str:
    product_type = str(trade.get("product_type", "")).strip().upper()
    if product_type in {"CAP", "FLOOR"}:
        return product_type
    fisn = str(trade.get("UPI FISN", trade.get("upi_fisn", ""))).upper()
    if "CALL" in fisn:
        return "CAP"
    if " P " in fisn or "PUT" in fisn or "NA/O P" in fisn:
        return "FLOOR"
    raise ValueError(f"Unable to infer cap/floor type from FISN: {fisn}")


def bachelier_caplet(F: float, K: float, sigma: float, T: float, tau: float, DF: float, N: float) -> float:
    """Price a single caplet under the Bachelier model."""
    if T < 1e-10 or sigma <= 0:
        return N * tau * DF * max(F - K, 0.0)
    sqrt_T = np.sqrt(T)
    d = (F - K) / (sigma * sqrt_T)
    return float(N * tau * DF * (sigma * sqrt_T * norm.pdf(d) + (F - K) * norm.cdf(d)))


def bachelier_floorlet(F: float, K: float, sigma: float, T: float, tau: float, DF: float, N: float) -> float:
    """Price a single floorlet under the Bachelier model."""
    if T < 1e-10 or sigma <= 0:
        return N * tau * DF * max(K - F, 0.0)
    sqrt_T = np.sqrt(T)
    d = (F - K) / (sigma * sqrt_T)
    return float(N * tau * DF * (sigma * sqrt_T * norm.pdf(d) - (F - K) * norm.cdf(-d)))


def build_caplet_schedule(
    effective: dt.datetime | dt.date | pd.Timestamp | str,
    expiration: dt.datetime | dt.date | pd.Timestamp | str,
    freq_months: int = 1,
) -> list[tuple[dt.datetime, dt.datetime]]:
    """Generate accrual periods from effective to expiration."""
    start = _coerce_datetime(effective)
    end = _coerce_datetime(expiration)
    if end <= start:
        return []

    months = max(int(freq_months or 1), 1)
    periods: list[tuple[dt.datetime, dt.datetime]] = []
    current = start
    while current < end:
        nxt = current + relativedelta(months=months)
        if nxt > end:
            nxt = end
        periods.append((current, nxt))
        current = nxt
    return periods


def strip_cap_vol(
    trade: dict[str, Any],
    curve: Any,
    valuation_date: dt.datetime | dt.date | pd.Timestamp | str | None = None,
) -> dict[str, Any]:
    """
    Back out a flat normal vol from an SDR cap/floor trade.

    Returns a diagnostics payload suitable for storage in leg_metrics.
    """
    effective = _coerce_datetime(trade["Effective Date"])
    expiration = _coerce_datetime(trade["Expiration Date"])
    notional = _clean_numeric(trade.get("Notional amount-Leg 1"))
    strike = _normalize_strike(trade.get("Strike Price"), trade.get("Strike price notation"))
    premium = _clean_numeric(trade.get("Option Premium Amount"))
    freq_months_raw = _clean_numeric(
        trade.get("Floating rate reset frequency period multiplier-leg 1")
    )
    freq_months = (
        int(round(freq_months_raw))
        if math.isfinite(freq_months_raw) and freq_months_raw > 0
        else 1
    )
    cap_floor_type = _infer_cap_floor_type(trade)

    if not math.isfinite(notional) or notional <= 0:
        raise ValueError(f"Invalid notional for cap/floor trade: {trade.get('Notional amount-Leg 1')!r}")
    if not math.isfinite(strike):
        raise ValueError(f"Invalid strike for cap/floor trade: {trade.get('Strike Price')!r}")
    if not math.isfinite(premium) or premium <= 0:
        raise ValueError(f"Invalid option premium for cap/floor trade: {trade.get('Option Premium Amount')!r}")

    if valuation_date is None:
        valuation_date = trade.get("Event timestamp") or trade.get("Execution Timestamp") or dt.datetime.utcnow()
    valuation_dt = _coerce_datetime(valuation_date)

    periods = build_caplet_schedule(effective, expiration, freq_months=freq_months)
    if not periods:
        raise ValueError("Cap/floor schedule is empty")

    try:
        base_df = float(curve[valuation_dt])
    except Exception:
        base_df = 1.0
    if not math.isfinite(base_df) or base_df == 0:
        base_df = 1.0

    caplets: list[dict[str, Any]] = []
    for accrual_start, accrual_end in periods:
        if accrual_end <= valuation_dt:
            continue

        forward_pct: float | None = None
        rate_attempts = [(accrual_start, accrual_end)]
        if accrual_start < valuation_dt:
            rate_attempts.insert(0, (valuation_dt, accrual_end))

        for rate_start, rate_end in rate_attempts:
            try:
                rate_value = curve.rate(rate_start, rate_end)
                if rate_value is None:
                    continue
                forward_pct = float(rate_value)
                break
            except Exception:
                continue

        if forward_pct is None:
            raise ValueError(
                f"Unable to resolve forward for period {accrual_start:%Y-%m-%d}->{accrual_end:%Y-%m-%d}"
            )

        forward = forward_pct / 100.0
        df_value = curve[accrual_end]
        if df_value is None:
            raise ValueError(
                f"Unable to resolve discount factor for period end {accrual_end:%Y-%m-%d}"
            )
        df_pay = float(df_value) / base_df
        tau = max((accrual_end - accrual_start).days / 360.0, 0.0)
        t_fix = max((accrual_start - valuation_dt).days / 365.0, 0.0)
        caplets.append(
            {
                "accrual_start": accrual_start,
                "accrual_end": accrual_end,
                "forward": forward,
                "discount_factor": df_pay,
                "tau": tau,
                "T_fix": t_fix,
                "days_to_fix": (accrual_start - valuation_dt).days,
            }
        )

    if not caplets:
        raise ValueError("Cap/floor schedule has no future cashflows after valuation date")

    premium_bps_of_notional = (premium / notional) * 10_000
    warnings: list[str] = []
    if premium_bps_of_notional < 0.5 or premium_bps_of_notional > 500:
        warnings.append(
            f"premium_outside_nominal_band:{premium_bps_of_notional:.4f}bp_of_notional"
        )

    pricer = bachelier_caplet if cap_floor_type == "CAP" else bachelier_floorlet

    def price_option(sigma: float) -> float:
        return float(
            sum(
                pricer(
                    c["forward"],
                    strike,
                    sigma,
                    c["T_fix"],
                    c["tau"],
                    c["discount_factor"],
                    notional,
                )
                for c in caplets
            )
        )

    intrinsic = price_option(0.0)

    def objective(sigma: float) -> float:
        return price_option(sigma) - premium

    sigma_lo = 1e-8
    sigma_hi = 0.05
    p_lo = objective(sigma_lo)
    p_hi = objective(sigma_hi)
    if p_lo == 0:
        implied_sigma = sigma_lo
    elif p_lo * p_hi > 0:
        if premium <= intrinsic + 1e-2:
            implied_sigma = 0.0
            warnings.append("premium_at_or_below_intrinsic")
        else:
            raise ValueError(
                f"Cannot bracket implied vol root: intrinsic={intrinsic:,.2f}, market={premium:,.2f}"
            )
    else:
        implied_sigma = float(brentq(objective, sigma_lo, sigma_hi, xtol=1e-12, maxiter=200))

    implied_vol_bps = implied_sigma * 10_000
    if implied_vol_bps < 30 or implied_vol_bps > 200:
        warnings.append(f"vol_outside_nominal_band:{implied_vol_bps:.4f}bp")

    for c in caplets:
        c["caplet_price"] = pricer(
            c["forward"],
            strike,
            implied_sigma,
            c["T_fix"],
            c["tau"],
            c["discount_factor"],
            notional,
        )
        c["moneyness_bps"] = (c["forward"] - strike) * 10_000

    return {
        "cap_floor_type": cap_floor_type,
        "implied_vol_bps": implied_vol_bps,
        "implied_vol_dec": implied_sigma,
        "bpvol": implied_vol_bps,
        "model_premium": price_option(implied_sigma),
        "market_premium": premium,
        "strike": strike,
        "notional": notional,
        "num_caplets": len(caplets),
        "moneyness_bps": caplets[0]["moneyness_bps"] if caplets else None,
        "caplet_details": caplets,
        "warnings": warnings,
    }
