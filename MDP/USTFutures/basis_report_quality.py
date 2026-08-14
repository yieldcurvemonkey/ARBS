"""Consistency gate for UST futures basis reports.

WHY THIS EXISTS
---------------
Three defects in the shared UST futures data path went undetected for years because nothing on the
read path ever asked whether the numbers could be a market:

  * the Ultra Bond's "price" was the EUR/NOK exchange rate (a vendor root pointed at the wrong
    instrument), which produced a net basis of +571/32 and an implied repo of -154%;
  * the ZN deliverable basket admitted old 30-year bonds, which are not deliverable into a 10-year
    note contract, producing a median implied repo of 14.6% against funding of 0.05-5.3%;
  * a prior attempt at a check used GROSS basis, which flags any high-carry regime as broken --
    it rejected 58% of healthy ZB in 2021 purely because repo near zero against a 2-3% coupon
    makes carry large.

The lesson in the third bullet sets the design: **the invariant has to be carry-adjusted**. Gross
basis is not a defect detector; net basis and implied repo are, because carry is already in them.

WHAT IT CHECKS
--------------
1. Structure: non-empty, required columns, no NaN in the numbers everything else is derived from.
2. The futures price could be a UST futures price at all (wrong-instrument detection).
3. Conversion factors are in a sane range.
4. |net basis| of the cheapest bond is bounded. This is the primary check: it is carry-adjusted and,
   unlike implied repo, it is not annualised, so it does not blow up near delivery.
5. Implied repo sits near the funding rate -- secondary, and only away from delivery, because
   implied repo annualises a shrinking horizon and is legitimately noisy in the last few weeks.

CALIBRATION (measured 2026-08-14 on 1,905 ZB / 1,886 ZN / 1,669 UB daily reports, 2018-06..2026-08)
--------------------------------------------------------------------------------------------------
    rule                          ZB (healthy)   ZN (basket bug)   UB (wrong instrument)
    |net basis| > 3 points              1.0%            29.7%              86.7%
    ... within the COVID window         0.0%           100.0%             100.0%
ZB passes the February-June 2020 dislocation cleanly at these thresholds, which is the point: a gate
that cannot tell a stressed market from a broken feed makes the most interesting period unusable.

The thresholds are deliberately generous. This is a "that is not a market" detector, not a
richness screen. Tighten it and it starts rejecting real dislocations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional, Sequence

import numpy as np
import pandas as pd

from definitions.USTFutures import UST_FUTURE_PLAUSIBLE_PRICE_BAND, is_plausible_ust_future_price

_LOGGER = logging.getLogger(__name__)

OnBadData = Literal["raise", "warn", "ignore"]

# See CALIBRATION above.
DEFAULT_MAX_ABS_NET_BASIS_32NDS = 96.0  # 3 points
DEFAULT_MAX_IRR_GAP_PCT = 10.0  # percentage points of implied repo vs funding
DEFAULT_MIN_DAYS_TO_DELIVERY_FOR_IRR = 21
DEFAULT_CF_BAND = (0.1, 2.0)

_REQUIRED_COLUMNS = ("clean_price", "invoice_cf", "gross_basis", "bnoc", "irr", "futures_price")


class BasisReportQualityError(ValueError):
    """A basis report failed the consistency gate."""


@dataclass(frozen=True)
class BasisReportQuality:
    ok: bool
    reasons: tuple[str, ...] = ()
    metrics: Dict[str, Any] = field(default_factory=dict)

    def describe(self, symbol: Optional[str] = None) -> str:
        head = f"basis report failed the consistency gate" + (f" for {symbol}" if symbol else "")
        return f"{head}: " + "; ".join(self.reasons) if self.reasons else head


def _days_to_delivery(df: pd.DataFrame) -> Optional[int]:
    if "delivery_date" not in df.columns or "trading_date" not in df.columns:
        return None
    try:
        delivery = pd.to_datetime(df["delivery_date"].iloc[0])
        trading = pd.to_datetime(df["trading_date"].iloc[0])
    except (IndexError, ValueError, TypeError):
        return None
    if pd.isna(delivery) or pd.isna(trading):
        return None
    return int((delivery - trading).days)


def check_basis_report(
    df: Optional[pd.DataFrame],
    *,
    symbol: Optional[str] = None,
    max_abs_net_basis_32nds: float = DEFAULT_MAX_ABS_NET_BASIS_32NDS,
    max_irr_gap_pct: float = DEFAULT_MAX_IRR_GAP_PCT,
    min_days_to_delivery_for_irr: int = DEFAULT_MIN_DAYS_TO_DELIVERY_FOR_IRR,
    cf_band: Sequence[float] = DEFAULT_CF_BAND,
) -> BasisReportQuality:
    """Judge one day's basis report. Never raises; returns a verdict."""
    reasons: list[str] = []
    metrics: Dict[str, Any] = {"symbol": symbol}

    if df is None or len(df) == 0:
        return BasisReportQuality(False, ("report is empty",), metrics)

    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return BasisReportQuality(False, (f"missing columns: {', '.join(missing)}",), metrics)

    metrics["n_deliverable"] = int(len(df))

    futures_price = pd.to_numeric(df["futures_price"], errors="coerce").dropna()
    if futures_price.empty:
        reasons.append("futures_price is entirely NaN")
    else:
        px = float(futures_price.iloc[0])
        metrics["futures_price"] = px
        if not is_plausible_ust_future_price(px):
            reasons.append(
                f"futures_price {px:.6f} is outside the plausible band "
                f"{UST_FUTURE_PLAUSIBLE_PRICE_BAND} -- this is normally a vendor symbol resolving "
                f"to a different instrument"
            )

    for col in ("clean_price", "invoice_cf", "gross_basis", "bnoc", "irr"):
        n_bad = int(pd.to_numeric(df[col], errors="coerce").isna().sum())
        if n_bad:
            reasons.append(f"{col} has {n_bad} non-finite value(s) of {len(df)}")

    cf = pd.to_numeric(df["invoice_cf"], errors="coerce").dropna()
    if not cf.empty:
        metrics["cf_min"], metrics["cf_max"] = float(cf.min()), float(cf.max())
        lo, hi = float(cf_band[0]), float(cf_band[1])
        if cf.min() <= lo or cf.max() >= hi:
            reasons.append(f"conversion factors {cf.min():.4f}-{cf.max():.4f} outside ({lo}, {hi})")

    # --- primary, carry-adjusted invariant -------------------------------------------------
    bnoc = pd.to_numeric(df["bnoc"], errors="coerce").dropna()
    if not bnoc.empty:
        cheapest = float(bnoc.min())
        metrics["min_net_basis_32nds"] = cheapest * 32.0
        if abs(cheapest * 32.0) > max_abs_net_basis_32nds:
            reasons.append(
                f"cheapest net basis {cheapest * 32.0:.1f}/32 exceeds "
                f"+/-{max_abs_net_basis_32nds:.0f}/32; a net basis that large is an arbitrage, "
                f"not a market"
            )

    # --- secondary: implied repo vs funding, away from delivery -----------------------------
    irr = pd.to_numeric(df["irr"], errors="coerce").dropna()
    repo = pd.to_numeric(df.get("repo_rate"), errors="coerce").dropna() if "repo_rate" in df else pd.Series(dtype=float)
    dtd = _days_to_delivery(df)
    metrics["days_to_delivery"] = dtd
    if not irr.empty and not repo.empty:
        gap = float(irr.max()) - float(repo.iloc[0])
        metrics["irr_gap_pct"] = gap
        metrics["max_irr_pct"] = float(irr.max())
        metrics["repo_pct"] = float(repo.iloc[0])
        far_enough = dtd is None or dtd >= min_days_to_delivery_for_irr
        if far_enough and abs(gap) > max_irr_gap_pct:
            reasons.append(
                f"best implied repo {irr.max():.2f}% is {gap:+.2f}pp from funding "
                f"{float(repo.iloc[0]):.2f}% (limit +/-{max_irr_gap_pct:.1f}pp, "
                f"{dtd if dtd is not None else '?'} days to delivery)"
            )

    return BasisReportQuality(not reasons, tuple(reasons), metrics)


def enforce_basis_report_quality(
    df: pd.DataFrame,
    *,
    symbol: Optional[str] = None,
    on_bad_data: OnBadData = "raise",
    annotate: bool = True,
    **check_kwargs: Any,
) -> pd.DataFrame:
    """Apply the gate at a read boundary.

    ``on_bad_data``:
      ``"raise"``  -- default. A caller that does nothing still cannot consume a broken report.
      ``"warn"``   -- log and carry on. For backfills that would rather record a bad day than die.
      ``"ignore"`` -- annotate only.

    With ``annotate``, ``data_ok`` and ``data_quality_reason`` columns are attached, so a consumer
    that chose ``"warn"`` still has the verdict in the data rather than only in a log line.
    """
    verdict = check_basis_report(df, symbol=symbol, **check_kwargs)
    if annotate and df is not None and len(df):
        df = df.copy()
        df["data_ok"] = verdict.ok
        df["data_quality_reason"] = "" if verdict.ok else "; ".join(verdict.reasons)
    if verdict.ok:
        return df
    message = verdict.describe(symbol)
    if on_bad_data == "raise":
        raise BasisReportQualityError(message)
    if on_bad_data == "warn":
        _LOGGER.warning("%s", message)
    return df


__all__ = [
    "BasisReportQuality",
    "BasisReportQualityError",
    "DEFAULT_CF_BAND",
    "DEFAULT_MAX_ABS_NET_BASIS_32NDS",
    "DEFAULT_MAX_IRR_GAP_PCT",
    "DEFAULT_MIN_DAYS_TO_DELIVERY_FOR_IRR",
    "check_basis_report",
    "enforce_basis_report_quality",
]
