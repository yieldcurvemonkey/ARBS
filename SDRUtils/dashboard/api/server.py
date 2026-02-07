# ABOUTME: FastAPI server exposing SOFR discount curve and vol surface engine endpoints.
# Run with: uvicorn api.server:app --host 0.0.0.0 --port 8100 --reload
# Or from the dashboard dir: python -m uvicorn api.server:app --host 0.0.0.0 --port 8100 --reload

import datetime
import math
import sys
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add project root to path so we can import MDP
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

app = FastAPI(title="Vol Grid API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ZeroRatePoint(BaseModel):
    tenor_years: float
    tenor_label: str
    zero_rate: float
    discount_factor: float


class SOFRCurveResponse(BaseModel):
    curve_name: str
    source: str
    timestamp: str
    reference_date: str
    zero_rates: list[ZeroRatePoint]


class AnnuityResponse(BaseModel):
    expiry_years: float
    tenor_years: float
    forward_rate: float
    annuity: float
    discount_factor_to_expiry: float


class BulkAnnuityResponse(BaseModel):
    curve_name: str
    source: str
    timestamp: str
    reference_date: str
    grid_points: list[AnnuityResponse]


# ---------------------------------------------------------------------------
# Cached curve state (rebuilt on request, cached for duration)
# ---------------------------------------------------------------------------

_cached_curve = None
_cached_curve_key = None

STANDARD_TENORS = {
    "1M": 1 / 12,
    "3M": 0.25,
    "6M": 0.5,
    "1Y": 1,
    "2Y": 2,
    "3Y": 3,
    "5Y": 5,
    "7Y": 7,
    "10Y": 10,
    "12Y": 12,
    "15Y": 15,
    "20Y": 20,
    "25Y": 25,
    "30Y": 30,
    "40Y": 40,
    "50Y": 50,
}


def _get_sofr_curve(source: str, date_str: Optional[str] = None):
    """Fetch or return cached SOFR curve."""
    global _cached_curve, _cached_curve_key

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    if date_str is None or date_str == "today":
        timestamp = datetime.date.today()
    else:
        timestamp = datetime.date.fromisoformat(date_str)

    cache_key = (source, str(timestamp))
    if _cached_curve_key == cache_key and _cached_curve is not None:
        return _cached_curve, timestamp

    mdp = IRSwapsMDP(source=source)
    pricer = mdp.get_pricer(request=dict(curve_name="USD-SOFR-1D", timestamp=timestamp))
    _cached_curve = pricer
    _cached_curve_key = cache_key
    return pricer, timestamp


@app.get("/api/sofr-curve", response_model=SOFRCurveResponse)
def get_sofr_curve(
    source: str = Query("ERIS_EOD_LIVE-QL_BASIC", description="MDP source for curve building"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format, or 'today'"),
):
    """
    Fetch SOFR discount curve data (zero rates and discount factors at standard tenors).

    Example:
        GET /api/sofr-curve?source=ERIS_EOD_LIVE-QL_BASIC&date=2026-02-06
    """
    try:
        pricer, timestamp = _get_sofr_curve(source, date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build SOFR curve: {str(e)}")

    handle = pricer.handle()
    ref_date = handle.referenceDate()

    # Check if this is a QuantLib-based curve
    is_ql = hasattr(handle, "discount")

    zero_rates = []
    for label, years in STANDARD_TENORS.items():
        try:
            if is_ql:
                import QuantLib as ql

                dc = ql.Actual365Fixed()
                target_date = ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(
                    ref_date, ql.Period(round(years * 12), ql.Months)
                )
                df = handle.discount(target_date)
                t = dc.yearFraction(ref_date, target_date)
                zr = -math.log(df) / t if t > 0 else 0.0
            else:
                # rateslib curve
                import rateslib as rl

                curve = pricer.rl_curve_handle
                target_dt = timestamp + datetime.timedelta(days=int(years * 365.25))
                df = float(curve[target_dt])
                t = years
                zr = -math.log(df) / t if t > 0 else 0.0

            zero_rates.append(
                ZeroRatePoint(
                    tenor_years=years,
                    tenor_label=label,
                    zero_rate=round(zr, 8),
                    discount_factor=round(df, 10),
                )
            )
        except Exception:
            continue

    ref_date_str = str(ref_date) if is_ql else str(timestamp)
    return SOFRCurveResponse(
        curve_name="USD-SOFR-1D",
        source=source,
        timestamp=str(timestamp),
        reference_date=ref_date_str,
        zero_rates=zero_rates,
    )


@app.get("/api/sofr-curve/annuities", response_model=BulkAnnuityResponse)
def get_annuities(
    source: str = Query("ERIS_EOD_LIVE-QL_BASIC"),
    date: Optional[str] = Query(None),
):
    """
    Compute forward swap rates and annuities for the full swaption grid.
    These are needed for premium computation (Bachelier formula).

    Returns forward_rate and annuity for each (expiry, tenor) pair on the standard grid.
    """
    try:
        pricer, timestamp = _get_sofr_curve(source, date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build SOFR curve: {str(e)}")

    handle = pricer.handle()
    is_ql = hasattr(handle, "discount")

    if not is_ql:
        raise HTTPException(status_code=400, detail="Annuity computation requires QuantLib curve source")

    import QuantLib as ql

    ql.Settings.instance().evaluationDate = handle.referenceDate()
    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    dc = ql.Actual365Fixed()
    ref_date = handle.referenceDate()

    expiry_map = {
        "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "2Y": 24, "3Y": 36,
        "5Y": 60, "7Y": 84, "10Y": 120, "15Y": 180, "20Y": 240, "30Y": 360,
    }
    tenor_map = {
        "1Y": 12, "2Y": 24, "3Y": 36, "5Y": 60, "7Y": 84,
        "10Y": 120, "15Y": 180, "20Y": 240, "25Y": 300, "30Y": 360,
    }

    expiry_years_map = {
        "1M": 1 / 12, "3M": 0.25, "6M": 0.5, "1Y": 1, "2Y": 2, "3Y": 3,
        "5Y": 5, "7Y": 7, "10Y": 10, "15Y": 15, "20Y": 20, "30Y": 30,
    }
    tenor_years_map = {
        "1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "7Y": 7,
        "10Y": 10, "15Y": 15, "20Y": 20, "25Y": 25, "30Y": 30,
    }

    grid_points = []
    sofr_index = ql.OvernightIndex(
        "SOFR", 0, ql.USDCurrency(), calendar, ql.Actual360(), handle
    )

    for exp_label, exp_months in expiry_map.items():
        expiry_date = calendar.advance(ref_date, ql.Period(exp_months, ql.Months))

        for tnr_label, tnr_months in tenor_map.items():
            try:
                swap_tenor = ql.Period(tnr_months, ql.Months)
                # Build a forward-starting OIS swap
                swap = ql.MakeOIS(
                    swap_tenor,
                    sofr_index,
                    0.0,  # placeholder rate
                    ql.Period(exp_months, ql.Months),  # forward start
                )
                fair_rate = swap.fairRate()

                # Annuity = sum of DF * accrual for fixed leg
                # For a $1 notional, annuity = |fixedLegBPS| / 0.0001
                annuity = abs(swap.fixedLegBPS()) / 0.0001

                # DF to expiry
                df_expiry = handle.discount(expiry_date)

                grid_points.append(
                    AnnuityResponse(
                        expiry_years=expiry_years_map[exp_label],
                        tenor_years=tenor_years_map[tnr_label],
                        forward_rate=round(fair_rate, 8),
                        annuity=round(annuity, 6),
                        discount_factor_to_expiry=round(df_expiry, 10),
                    )
                )
            except Exception:
                continue

    ref_date_str = str(ref_date)
    return BulkAnnuityResponse(
        curve_name="USD-SOFR-1D",
        source=source,
        timestamp=str(timestamp),
        reference_date=ref_date_str,
        grid_points=grid_points,
    )


@app.get("/health")
def health():
    return {"status": "ok"}
