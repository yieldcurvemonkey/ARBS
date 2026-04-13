"""
FOMC-dated swap analytics: meeting schedules, implied rates, and probabilities.

Provides both standalone functions and the FOMCAnalyzer class for comprehensive
meeting-by-meeting analysis of FOMC-dated swaps with dual-curve (SOFR/OIS) support.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ._base import SDRAnalyzer
from .filters import vwap

# ---------------------------------------------------------------------------
# Standalone helpers
# ---------------------------------------------------------------------------


def load_fomc_schedule(curve_name: str = "USD-SOFR-1D") -> pd.DataFrame:
    """Load FOMC meeting schedule from the central bank dates registry.

    Reads ``_CENTRAL_BANK_DATES`` for the given curve and returns a tidy
    DataFrame with one row per meeting.

    Args:
        curve_name: Curve key in ``_CENTRAL_BANK_DATES``
            (default ``"USD-SOFR-1D"``).

    Returns:
        DataFrame with columns ``[meeting_label, effective_date,
        maturity_date, period_days]`` sorted by effective date.
    """
    from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES

    sched = _CENTRAL_BANK_DATES.get(curve_name, {})
    rows = []
    for label, (eff, mat) in sorted(sched.items(), key=lambda x: x[1][0]):
        rows.append({
            "meeting_label": label,
            "effective_date": eff,
            "maturity_date": mat,
            "period_days": (mat - eff).days,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["effective_date"] = pd.to_datetime(df["effective_date"])
        df["maturity_date"] = pd.to_datetime(df["maturity_date"])
    return df


def classify_rate_index(upi_underlier: str) -> str:
    """Classify a UPI underlier name into a rate-index bucket.

    Args:
        upi_underlier: Raw UPI underlier name string from SDR data.

    Returns:
        ``"FED_FUNDS"`` if the name contains *FEDERAL FUNDS* or *FED FUND*,
        ``"SOFR"`` if it contains *SOFR*, otherwise ``"OTHER"``.
    """
    s = str(upi_underlier).upper()
    if "FEDERAL FUNDS" in s or "FED FUND" in s:
        return "FED_FUNDS"
    if "SOFR" in s:
        return "SOFR"
    return "OTHER"


def assign_fomc_meeting(row, schedule_df: pd.DataFrame) -> str:
    """Map a single trade row to an FOMC meeting label.

    Matching logic:

    1. If the trade's ``expiration_date`` matches a meeting's
       ``maturity_date``, that meeting is returned.
    2. Else if the trade's ``effective_date`` matches a meeting's
       ``effective_date``, that meeting is returned.
    3. Otherwise ``"UNKNOWN"``.

    Args:
        row: A Series (or dict-like) with ``expiration_date`` and
            ``effective_date`` fields.
        schedule_df: DataFrame produced by :func:`load_fomc_schedule`.

    Returns:
        The meeting label string, or ``"UNKNOWN"``.
    """
    mat_to_label = dict(
        zip(schedule_df["maturity_date"].dt.date, schedule_df["meeting_label"])
    )
    eff_to_label = dict(
        zip(schedule_df["effective_date"].dt.date, schedule_df["meeting_label"])
    )

    exp = pd.to_datetime(row.get("expiration_date"))
    eff = pd.to_datetime(row.get("effective_date"))

    if pd.notna(exp):
        d = exp.date() if hasattr(exp, "date") else exp
        lbl = mat_to_label.get(d)
        if lbl:
            return lbl

    if pd.notna(eff):
        d = eff.date() if hasattr(eff, "date") else eff
        lbl = eff_to_label.get(d)
        if lbl:
            return lbl

    return "UNKNOWN"


def classify_meeting_proximity(row, schedule_df: pd.DataFrame) -> str:
    """Classify how far ahead a traded meeting is from execution date.

    Counts how many FOMC meetings fall between the trade's execution date
    and the meeting it references.

    Args:
        row: A Series with ``execution_timestamp`` and a ``meeting_eff``
            column (the meeting's effective date).
        schedule_df: DataFrame produced by :func:`load_fomc_schedule`.

    Returns:
        ``"Near (1-3)"``, ``"Mid (4-6)"``, or ``"Far (7+)"``.
    """
    exec_date = pd.to_datetime(row["execution_timestamp"]).date()
    meeting_eff = row.get("meeting_eff")
    if pd.isna(meeting_eff):
        return "Far (7+)"
    meeting_date = (
        meeting_eff.date() if hasattr(meeting_eff, "date") else meeting_eff
    )
    upcoming = sorted(
        m for m in schedule_df["effective_date"].dt.date if m >= exec_date
    )
    try:
        rank = upcoming.index(meeting_date) + 1
    except ValueError:
        rank = 99

    if rank <= 3:
        return "Near (1-3)"
    if rank <= 6:
        return "Mid (4-6)"
    return "Far (7+)"


def compute_calendar_spreads(
    implied_df: pd.DataFrame,
    sofr_col: str = "sofr_implied_rate",
    ois_col: str = "ois_implied_rate",
) -> pd.DataFrame:
    """Compute consecutive-meeting rate differences (calendar spreads).

    ``spread(N, N+1) = implied(N+1) - implied(N)``

    A negative spread implies the market expects a cut at meeting N+1
    relative to N.

    Args:
        implied_df: DataFrame with ``meeting_label`` and implied-rate
            columns (must be sorted by meeting date).
        sofr_col: Column name for SOFR implied rates.
        ois_col: Column name for OIS implied rates.

    Returns:
        DataFrame with ``[spread_label, front_meeting, back_meeting,
        sofr_spread_bps, ois_spread_bps]``.
    """
    spreads = []
    for i in range(len(implied_df) - 1):
        curr = implied_df.iloc[i]
        nxt = implied_df.iloc[i + 1]
        rec = {
            "spread_label": f"{curr['meeting_label']} / {nxt['meeting_label']}",
            "front_meeting": curr["meeting_label"],
            "back_meeting": nxt["meeting_label"],
        }
        for prefix, col in [("sofr", sofr_col), ("ois", ois_col)]:
            c_rate = curr.get(col)
            n_rate = nxt.get(col)
            if pd.notna(c_rate) and pd.notna(n_rate):
                rec[f"{prefix}_spread_bps"] = (n_rate - c_rate) * 10_000
            else:
                rec[f"{prefix}_spread_bps"] = np.nan
        spreads.append(rec)
    return pd.DataFrame(spreads)


def compute_cut_probabilities(
    implied_df: pd.DataFrame,
    current_sofr: float,
    current_effr: Optional[float] = None,
    bp25: float = 0.0025,
) -> pd.DataFrame:
    """Add cut-probability and cumulative-cut columns to an implied-rate table.

    Standard formula:
    ``P(25bp cut) = (current_rate - implied_forward_rate) / 25bp * 100``

    Positive probability means the market expects a cut.  Values above
    100 % imply the market prices more than one 25 bp cut.

    Args:
        implied_df: DataFrame with ``sofr_implied_rate`` and optionally
            ``ois_implied_rate`` columns.
        current_sofr: Current SOFR fixing (decimal, e.g. 0.043).
        current_effr: Current EFFR fixing.  If *None*, OIS columns are
            filled with NaN.
        bp25: Size of one standard policy move (default 25 bp).

    Returns:
        Copy of *implied_df* with added columns ``p_cut_sofr``,
        ``p_cut_ois``, ``cumulative_cuts_sofr``, ``cumulative_cuts_ois``.
    """
    df = implied_df.copy()

    # SOFR
    df["p_cut_sofr"] = (
        (current_sofr - df["sofr_implied_rate"]) / bp25 * 100
    ).clip(-50, 200)
    df["cumulative_cuts_sofr"] = (
        (current_sofr - df["sofr_implied_rate"]) / bp25
    )

    # OIS
    if current_effr is not None and "ois_implied_rate" in df.columns:
        df["p_cut_ois"] = (
            (current_effr - df["ois_implied_rate"]) / bp25 * 100
        ).clip(-50, 200)
        df["cumulative_cuts_ois"] = (
            (current_effr - df["ois_implied_rate"]) / bp25
        )
    else:
        df["p_cut_ois"] = np.nan
        df["cumulative_cuts_ois"] = np.nan

    return df


# ---------------------------------------------------------------------------
# Curve helpers (moved from _sdr_common.py)
# ---------------------------------------------------------------------------


def get_current_fixing(
    curve_name: str = "USD-SOFR-1D",
    as_of_date: Optional[datetime.date] = None,
) -> float:
    """Fetch the latest overnight fixing rate dynamically.

    Uses NY Fed API (primary) with FRED fallback via the fixings cache.

    Args:
        curve_name: ``"USD-SOFR-1D"`` for SOFR, ``"USD-OIS"`` for EFFR.
        as_of_date: Date to fetch fixing for (default: today).

    Returns:
        Latest fixing as decimal (e.g. 0.043 for 4.30 %).

    Raises:
        ValueError: If no fixings are available for the requested date/curve.
    """
    from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings

    if as_of_date is None:
        as_of_date = datetime.date.today()

    fixings = _fetch_fixings(as_of_date=as_of_date, curve_name=curve_name)
    if fixings is None or fixings.empty:
        raise ValueError(
            f"No fixings available for {curve_name} as of {as_of_date}"
        )

    # fixings is a Series indexed by date, values in decimal (e.g. 0.043)
    valid = fixings[fixings.index <= pd.Timestamp(as_of_date)]
    if valid.empty:
        raise ValueError(
            f"No fixings on or before {as_of_date} for {curve_name}"
        )

    latest_date = valid.index.max()
    return float(valid.loc[latest_date])


def build_fomc_curves(
    pricing_date: Optional[datetime.date] = None,
    sofr_curve_name: str = "USD-SOFR-1D-Q12xM12STIRT",
    ois_curve_name: str = "USD-OIS-Q12xM12STIRT-SERFFX-MIX23",
) -> dict:
    """Build both SOFR and OIS (Fed Funds) short-end curves for FOMC pricing.

    Uses ``BARCHART_STIRF-RL`` source -- purpose-built STIR futures curves.

    Args:
        pricing_date: Curve build date (default: latest business day).
        sofr_curve_name: SOFR curve identifier.
        ois_curve_name: OIS curve identifier.

    Returns:
        ``{"SOFR": pricer, "OIS": pricer, "pricing_date": date}`` where
        each pricer may be *None* if the build failed.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    if pricing_date is None:
        pricing_date = (
            pd.Timestamp(datetime.date.today())
            - pd.tseries.offsets.BDay(0)
        )
        if pricing_date.date() > datetime.date.today():
            pricing_date = (
                pd.Timestamp(datetime.date.today())
                - pd.tseries.offsets.BDay(1)
            )
        pricing_date = pricing_date.date()

    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    result: Dict[str, Any] = {
        "SOFR": None,
        "OIS": None,
        "pricing_date": pricing_date,
    }

    for key, curve_name in [("SOFR", sofr_curve_name), ("OIS", ois_curve_name)]:
        try:
            result[key] = mdp.get_pricer(dict(
                curve_name=curve_name,
                timestamp=pricing_date,
            ))
        except Exception as e:
            print(f"  WARNING: Failed to build {key} curve ({curve_name}): {e}")

    return result


def _strip_accrued_fixings(
    rates_df: pd.DataFrame,
    fomc_df: pd.DataFrame,
    curves_dict: dict,
) -> pd.DataFrame:
    """Decompose blended implied rates into accrued and forward-only parts.

    For in-progress meetings (``eff < today < mat``), the full-period rate
    mixes realized fixings with forward expectations.  This function
    strips out the accrued (known) portion so that the resulting
    forward-only rate reflects actionable expectations.

    Adds columns: ``sofr_fwd_rate``, ``ois_fwd_rate``, ``accrued_days``,
    ``remaining_days``.

    Args:
        rates_df: DataFrame with ``meeting_label``, ``sofr_implied_rate``,
            ``ois_implied_rate``.
        fomc_df: Meeting schedule DataFrame with ``effective_date`` and
            ``maturity_date``.
        curves_dict: Output of :func:`build_fomc_curves` (used for
            ``pricing_date``).

    Returns:
        *rates_df* with forward-rate and day-count columns added.
    """
    from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings

    pricing_date = curves_dict.get("pricing_date", datetime.date.today())

    # Fetch fixings for decomposition
    fixing_series: Dict[str, pd.Series] = {}
    for curve_key, fixing_curve in [("SOFR", "USD-SOFR-1D"), ("OIS", "USD-OIS")]:
        try:
            f = _fetch_fixings(as_of_date=pricing_date, curve_name=fixing_curve)
            fixing_series[curve_key] = (
                f.sort_index() if f is not None else pd.Series(dtype=float)
            )
        except Exception:
            fixing_series[curve_key] = pd.Series(dtype=float)

    # Build schedule lookup
    schedule = fomc_df.set_index("meeting_label")[
        ["effective_date", "maturity_date"]
    ]

    for col_prefix, curve_key in [("sofr", "SOFR"), ("ois", "OIS")]:
        implied_col = f"{col_prefix}_implied_rate"
        fwd_col = f"{col_prefix}_fwd_rate"
        rates_df[fwd_col] = np.nan

        fixings = fixing_series.get(curve_key, pd.Series(dtype=float))

        for idx, row in rates_df.iterrows():
            label = row["meeting_label"]
            full_rate = row.get(implied_col)
            if pd.isna(full_rate) or label not in schedule.index:
                rates_df.loc[idx, fwd_col] = full_rate
                continue

            eff = schedule.loc[label, "effective_date"]
            mat = schedule.loc[label, "maturity_date"]
            if hasattr(eff, "date"):
                eff = eff.date()
            if hasattr(mat, "date"):
                mat = mat.date()

            total_days = (mat - eff).days
            if total_days <= 0 or eff >= pricing_date or fixings.empty:
                rates_df.loc[idx, fwd_col] = full_rate
                continue

            # In-progress: strip accrued fixings
            accrued = fixings[
                (fixings.index >= pd.Timestamp(eff))
                & (fixings.index < pd.Timestamp(pricing_date))
            ]
            accrued_n = len(accrued)
            remaining = total_days - accrued_n

            if accrued_n > 0 and remaining > 0:
                accrued_avg = accrued.mean()
                fwd_rate = (
                    full_rate * total_days - accrued_avg * accrued_n
                ) / remaining
                rates_df.loc[idx, fwd_col] = fwd_rate
            else:
                rates_df.loc[idx, fwd_col] = full_rate

    # Add day counts
    rates_df["accrued_days"] = 0
    rates_df["remaining_days"] = 0
    for idx, row in rates_df.iterrows():
        label = row["meeting_label"]
        if label not in schedule.index:
            continue
        eff = schedule.loc[label, "effective_date"]
        mat = schedule.loc[label, "maturity_date"]
        if hasattr(eff, "date"):
            eff = eff.date()
        if hasattr(mat, "date"):
            mat = mat.date()
        total = (mat - eff).days
        if eff < pricing_date:
            sofr_fix = fixing_series.get("SOFR", pd.Series(dtype=float))
            accrued_n = len(
                sofr_fix[
                    (sofr_fix.index >= pd.Timestamp(eff))
                    & (sofr_fix.index < pd.Timestamp(pricing_date))
                ]
            )
            rates_df.loc[idx, "accrued_days"] = accrued_n
            rates_df.loc[idx, "remaining_days"] = total - accrued_n
        else:
            rates_df.loc[idx, "remaining_days"] = total

    return rates_df


def price_fomc_meetings(
    fomc_df: pd.DataFrame,
    curves_dict: dict,
    schedule_key: str = "USD-SOFR-1D",
) -> pd.DataFrame:
    """Price each FOMC meeting period on both SOFR and OIS curves.

    For each meeting defined in *fomc_df*, queries the pricer objects in
    *curves_dict* for the fair rate of a swap spanning the meeting period.
    After pricing, :func:`_strip_accrued_fixings` is called to decompose
    in-progress meetings into accrued and forward components.

    Args:
        fomc_df: DataFrame with ``meeting_label``, ``effective_date``,
            ``maturity_date``.
        curves_dict: Output of :func:`build_fomc_curves`.
        schedule_key: Curve key passed to ``IRSwapQuery``
            (both curves share the FOMC schedule).

    Returns:
        DataFrame with ``meeting_label``, ``sofr_implied_rate``,
        ``ois_implied_rate``, plus forward-rate and day-count columns.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    records = []
    pricing_errors = []

    for _, row in fomc_df.iterrows():
        label = row["meeting_label"]
        eff = row["effective_date"]
        mat = row["maturity_date"]

        if hasattr(eff, "date"):
            eff = eff.date()
        if hasattr(mat, "date"):
            mat = mat.date()

        # Skip expired meetings
        if mat < datetime.date.today():
            continue

        rec = {"meeting_label": label}

        for curve_key, col_name in [
            ("SOFR", "sofr_implied_rate"),
            ("OIS", "ois_implied_rate"),
        ]:
            curve = curves_dict.get(curve_key)
            if curve is None:
                rec[col_name] = np.nan
                continue
            try:
                query = IRSwapQuery(
                    curve=schedule_key,
                    effective_date=eff,
                    maturity_date=mat,
                    value=IRSwapValue.RATE,
                )
                package, _ = query.resolve_package(pricer_or_curve=curve)
                rec[col_name] = curve.fair_rate(package[0])
            except Exception as e:
                rec[col_name] = np.nan
                pricing_errors.append((label, curve_key, str(e)))

        records.append(rec)

    if pricing_errors:
        n = len(pricing_errors)
        print(f"  {n} pricing error(s):")
        for label, key, err in pricing_errors[:5]:
            print(f"    {label} ({key}): {err}")

    result = pd.DataFrame(records)

    # Strip accrued fixings from in-progress meetings
    if not result.empty:
        result = _strip_accrued_fixings(result, fomc_df, curves_dict)

    return result


# ---------------------------------------------------------------------------
# FOMCAnalyzer class
# ---------------------------------------------------------------------------


class FOMCAnalyzer(SDRAnalyzer):
    """FOMC meeting-swap analytics with dual-curve support.

    Combines SDR trade-flow analysis with curve-based implied-rate
    extraction to produce a comprehensive meeting-by-meeting view of
    FOMC expectations.

    Parameters
    ----------
    df : pd.DataFrame
        Classified SDR trades (should include FOMC-dated swaps with
        ``special_tenor_type == "FOMC"``).
    curve_name : str
        Schedule lookup key in ``_CENTRAL_BANK_DATES``.
    sofr_curve_name : str
        SOFR STIR curve identifier for pricing.
    ois_curve_name : str
        OIS STIR curve identifier for pricing.
    current_sofr : float or None
        Current SOFR fixing.  If *None*, fetched dynamically.
    current_effr : float or None
        Current EFFR fixing.  If *None*, fetched dynamically.
    pricing_date : date or None
        Curve build date.  If *None*, uses latest business day.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        *,
        curve_name: str = "USD-SOFR-1D",
        sofr_curve_name: str = "USD-SOFR-1D-Q12xM12STIRT",
        ois_curve_name: str = "USD-OIS-Q12xM12STIRT-SERFFX-MIX23",
        current_sofr: Optional[float] = None,
        current_effr: Optional[float] = None,
        pricing_date: Optional[datetime.date] = None,
    ) -> None:
        super().__init__(df)
        self._curve_name = curve_name
        self._sofr_curve_name = sofr_curve_name
        self._ois_curve_name = ois_curve_name
        self._current_sofr = (
            current_sofr if current_sofr is not None
            else get_current_fixing("USD-SOFR-1D")
        )
        self._current_effr = (
            current_effr if current_effr is not None
            else get_current_fixing("USD-OIS")
        )
        self._pricing_date = pricing_date
        self._schedule = load_fomc_schedule(curve_name)
        self._curves: Optional[dict] = None
        self._fomc_trades_df: Optional[pd.DataFrame] = None

    # -- properties --------------------------------------------------------

    @property
    def schedule(self) -> pd.DataFrame:
        """FOMC meeting schedule DataFrame."""
        return self._schedule

    @property
    def current_sofr(self) -> float:
        """Current SOFR overnight fixing (decimal)."""
        return self._current_sofr

    @property
    def current_effr(self) -> float:
        """Current EFFR overnight fixing (decimal)."""
        return self._current_effr

    @property
    def fomc_trades(self) -> pd.DataFrame:
        """FOMC-dated trades filtered from the input DataFrame.

        Filters to ``special_tenor_type == "FOMC"`` and assigns each trade
        a ``meeting_label`` via :func:`assign_fomc_meeting`.  Trades that
        cannot be matched are dropped.
        """
        if self._fomc_trades_df is not None:
            return self._fomc_trades_df

        df = self._df
        if df.empty:
            self._fomc_trades_df = pd.DataFrame()
            return self._fomc_trades_df

        fomc = df[df["special_tenor_type"].astype(str) == "FOMC"].copy()
        if fomc.empty:
            self._fomc_trades_df = pd.DataFrame()
            return self._fomc_trades_df

        # Build lookup dicts once
        mat_to_label = dict(
            zip(self._schedule["maturity_date"].dt.date, self._schedule["meeting_label"])
        )
        eff_to_label = dict(
            zip(self._schedule["effective_date"].dt.date, self._schedule["meeting_label"])
        )

        def _assign(row):
            exp = pd.to_datetime(row.get("expiration_date"))
            eff = pd.to_datetime(row.get("effective_date"))
            if pd.notna(exp):
                d = exp.date() if hasattr(exp, "date") else exp
                lbl = mat_to_label.get(d)
                if lbl:
                    return lbl
            if pd.notna(eff):
                d = eff.date() if hasattr(eff, "date") else eff
                lbl = eff_to_label.get(d)
                if lbl:
                    return lbl
            return "UNKNOWN"

        fomc["meeting_label"] = fomc.apply(_assign, axis=1)
        fomc = fomc[fomc["meeting_label"] != "UNKNOWN"].copy()

        # Merge meeting schedule info
        if not fomc.empty:
            fomc = fomc.merge(
                self._schedule[
                    ["meeting_label", "effective_date", "maturity_date", "period_days"]
                ].rename(columns={
                    "effective_date": "meeting_eff",
                    "maturity_date": "meeting_mat",
                }),
                on="meeting_label",
                how="left",
            )

        self._fomc_trades_df = fomc
        return self._fomc_trades_df

    # -- computation -------------------------------------------------------

    def compute(self) -> pd.DataFrame:
        """Run the full FOMC analytics pipeline.

        Steps:
        1. Build SOFR and OIS curves.
        2. Price each upcoming meeting on both curves.
        3. Merge SDR VWAP rates from :meth:`compute_sdr_implied`.
        4. Compute rate moves relative to current fixings and
           SOFR-OIS basis.
        5. Compute cut probabilities via :func:`compute_cut_probabilities`.

        Returns:
            DataFrame indexed by meeting with implied rates, moves,
            basis, and cut probabilities.
        """
        # Curve-based implied rates
        curve_implied = self.compute_curve_implied()

        # SDR VWAP rates
        sdr_implied = self.compute_sdr_implied()

        # Start from the schedule
        result = self._schedule[
            ["meeting_label", "effective_date", "maturity_date", "period_days"]
        ].copy()

        # Merge curve-based rates
        if not curve_implied.empty:
            result = result.merge(curve_implied, on="meeting_label", how="left")
        else:
            for col in (
                "sofr_implied_rate", "ois_implied_rate",
                "sofr_fwd_rate", "ois_fwd_rate",
                "accrued_days", "remaining_days",
            ):
                result[col] = np.nan

        # Merge SDR VWAP
        if not sdr_implied.empty:
            sdr_df = sdr_implied.reset_index()
            sdr_df.columns = ["meeting_label", "sdr_implied_rate"]
            result = result.merge(sdr_df, on="meeting_label", how="left")
        else:
            result["sdr_implied_rate"] = np.nan

        # Keep only meetings with at least one rate
        has_rate = (
            result["sofr_implied_rate"].notna()
            | result["ois_implied_rate"].notna()
            | result["sdr_implied_rate"].notna()
        )
        result = result[has_rate].reset_index(drop=True)

        # Compute moves and basis
        result["sofr_move"] = (
            (result["sofr_implied_rate"] - self._current_sofr) * 10_000
        )
        result["ois_move"] = (
            (result["ois_implied_rate"] - self._current_effr) * 10_000
        )
        result["basis"] = (
            (result["sofr_implied_rate"] - result["ois_implied_rate"]) * 10_000
        )

        # Cut probabilities
        result = compute_cut_probabilities(
            result,
            current_sofr=self._current_sofr,
            current_effr=self._current_effr,
        )

        self._result = result
        return result

    def compute_sdr_implied(self) -> pd.Series:
        """VWAP of fixed_rate per meeting from FOMC-dated SDR trades.

        Returns:
            Series indexed by ``meeting_label`` with VWAP rates, or
            empty Series if no trades are available.
        """
        trades = self.fomc_trades
        if trades.empty:
            return pd.Series(dtype=float, name="sdr_implied_rate")

        rates = trades[
            pd.to_numeric(trades["fixed_rate"], errors="coerce").notna()
        ].copy()
        if rates.empty:
            return pd.Series(dtype=float, name="sdr_implied_rate")

        rates["fixed_rate"] = pd.to_numeric(rates["fixed_rate"])
        return (
            rates.groupby("meeting_label")
            .apply(lambda g: vwap(g, rate_col="fixed_rate", weight_col="dv01"))
            .rename("sdr_implied_rate")
        )

    def compute_curve_implied(self) -> pd.DataFrame:
        """Build curves and price each upcoming meeting on SOFR and OIS.

        Lazily builds curves on first call and caches them.

        Returns:
            DataFrame with ``meeting_label``, ``sofr_implied_rate``,
            ``ois_implied_rate``, and forward-rate columns.
        """
        if self._curves is None:
            self._curves = build_fomc_curves(
                pricing_date=self._pricing_date,
                sofr_curve_name=self._sofr_curve_name,
                ois_curve_name=self._ois_curve_name,
            )
        return price_fomc_meetings(
            self._schedule,
            self._curves,
            schedule_key=self._curve_name,
        )

    def calendar_spreads(self) -> pd.DataFrame:
        """Compute calendar spreads from the full result.

        Calls :meth:`compute` if needed, then delegates to
        :func:`compute_calendar_spreads`.

        Returns:
            Calendar-spread DataFrame.
        """
        if self._result is None:
            self.compute()
        return compute_calendar_spreads(self._result)

    def summary(self) -> Dict[str, Any]:
        """Key metrics for a trading-desk summary.

        Returns:
            Dict with ``n_meetings``, ``n_traded``, ``total_fomc_dv01``,
            ``next_meeting``, ``next_p_cut_sofr``,
            ``cumulative_easing_sofr``, ``sofr_ois_basis_range``.
        """
        if self._result is None:
            self.compute()

        result = self._result
        trades = self.fomc_trades

        n_meetings = len(result)
        n_traded = (
            trades["meeting_label"].nunique() if not trades.empty else 0
        )
        total_dv01 = trades["dv01"].sum() if not trades.empty else 0.0

        # Next meeting
        next_meeting = (
            result["meeting_label"].iloc[0] if n_meetings > 0 else None
        )
        next_p_cut = (
            float(result["p_cut_sofr"].iloc[0])
            if n_meetings > 0 and pd.notna(result["p_cut_sofr"].iloc[0])
            else None
        )

        # Cumulative easing (last meeting in the horizon)
        cum_easing = (
            float(result["cumulative_cuts_sofr"].iloc[-1])
            if n_meetings > 0
            and pd.notna(result["cumulative_cuts_sofr"].iloc[-1])
            else None
        )

        # Basis range
        basis_vals = result["basis"].dropna()
        basis_range = (
            (float(basis_vals.min()), float(basis_vals.max()))
            if not basis_vals.empty
            else None
        )

        return {
            "n_meetings": n_meetings,
            "n_traded": n_traded,
            "total_fomc_dv01": total_dv01,
            "next_meeting": next_meeting,
            "next_p_cut_sofr": next_p_cut,
            "cumulative_easing_sofr": cum_easing,
            "sofr_ois_basis_range": basis_range,
        }
