"""Date sampler for SR3 vs ZQ distribution-comparison backfill.

For each ``as_of``, auto-resolve:
    - the SR3 quarterly contract whose option-expiry sits in [DTE_lo, DTE_hi]
    - the SR3 reference period [expiry, +91 days]
    - the ZQ months range covering ref period plus padding for FedWatch
      anchor non-FOMC months on each side

Returns a list of ``DateSample`` dataclasses ready to feed
``compute_distribution_signals``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import List, Optional, Tuple

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _imm_cutoff, _next_contracts
from MDP.STIRFutures._sofr_option_contracts import _contract_expiry_date


@dataclass(frozen=True)
class DateSample:
    as_of: datetime.date
    regime_label: str
    sr3_contract: str
    ref_start: datetime.date
    ref_end: datetime.date
    zq_months_range: Tuple[Tuple[int, int], Tuple[int, int]]
    sr3_dte: int


# Curated regime calendar — known macro events bookend the labels.
# Reduced to 12 strategic dates (down from 35) to stay within Barchart
# rate-limit feasibility. Each regime quadrant gets 2-4 representatives;
# dates already cached from earlier 5-date backfill (2023-02-21, 2023-03-13,
# 2024-08-15, 2024-09-19, 2026-05-04) are kept first to maximize cache reuse.
REGIME_CALENDAR: List[Tuple[datetime.date, str]] = [
    # === Cached from earlier 12-date backfill ===
    (datetime.date(2023, 2, 21), "pre-SVB calm"),
    (datetime.date(2023, 3, 13), "post-SVB stress peak"),
    (datetime.date(2024, 8, 15), "pre-Sep24 cut"),
    (datetime.date(2024, 9, 19), "post-50bp cut"),
    (datetime.date(2026, 5, 4), "current"),
    (datetime.date(2022, 12, 1), "Dec22 cycle peak"),
    (datetime.date(2023, 3, 20), "SVB+1w recovering"),
    (datetime.date(2024, 12, 19), "Dec24 hawkish SEP"),
    (datetime.date(2025, 4, 4), "post-tariff shock"),
    (datetime.date(2025, 6, 16), "summer 2025"),
    (datetime.date(2025, 9, 17), "Sep25 cut restart"),
    (datetime.date(2026, 2, 17), "early-2026 calm"),

    # === New hike-cycle dates (fill n=1 gap in hike regime) ===
    # 2022 ramping cycle: 75bp era from Jun 2022 onward
    (datetime.date(2022, 6, 16), "Jun22 first 75bp"),
    (datetime.date(2022, 7, 28), "Jul22 75bp follow-up"),
    (datetime.date(2022, 9, 22), "Sep22 75bp"),
    (datetime.date(2022, 11, 3), "Nov22 75bp"),
    (datetime.date(2023, 1, 12), "early-2023 hike pause expectation"),
    (datetime.date(2023, 5, 4), "May23 25bp + pause guidance"),
]


def _resolve_sr3_contract(as_of: datetime.date, *, dte_lo: int = 60, dte_hi: int = 200) -> Optional[str]:
    """Pick the first SR3 quarterly whose option expiry is in [as_of+dte_lo, as_of+dte_hi]."""
    contracts = _next_contracts(
        start_date=as_of,
        prefix="SFR",
        count=8,
        valid_months=[3, 6, 9, 12],
        cutoff_fn=_imm_cutoff,
    )
    for c in contracts:
        try:
            expiry = _contract_expiry_date(c[-3:])
        except Exception:
            continue
        dte = (expiry - as_of).days
        if dte_lo <= dte <= dte_hi:
            return c
    return None


def _zq_months_for_ref(as_of: datetime.date, ref_start: datetime.date, ref_end: datetime.date) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Build a months-range covering as_of through ref_end + a 1-month
    pad on each side (FedWatch needs anchor non-FOMC months)."""
    start = (as_of.year, as_of.month)
    # Pad ref_end by one month on the right
    y, m = ref_end.year, ref_end.month + 1
    if m == 13:
        m = 1
        y += 1
    end = (y, m)
    return start, end


def build_samples(
    *,
    dte_lo: int = 60,
    dte_hi: int = 200,
) -> List[DateSample]:
    out: List[DateSample] = []
    for as_of, regime in REGIME_CALENDAR:
        contract = _resolve_sr3_contract(as_of, dte_lo=dte_lo, dte_hi=dte_hi)
        if contract is None:
            continue
        try:
            expiry = _contract_expiry_date(contract[-3:])
        except Exception:
            continue
        ref_start = expiry
        ref_end = expiry + datetime.timedelta(days=91)
        zq_range = _zq_months_for_ref(as_of, ref_start, ref_end)
        out.append(
            DateSample(
                as_of=as_of,
                regime_label=regime,
                sr3_contract=contract,
                ref_start=ref_start,
                ref_end=ref_end,
                zq_months_range=zq_range,
                sr3_dte=(expiry - as_of).days,
            )
        )
    return out


if __name__ == "__main__":
    samples = build_samples()
    print(f"{len(samples)} dates resolved\n")
    for s in samples:
        print(
            f"  {s.as_of}  {s.regime_label:<28}  {s.sr3_contract}  dte={s.sr3_dte:>3}  "
            f"ref=[{s.ref_start} .. {s.ref_end}]  zq={s.zq_months_range[0]}-{s.zq_months_range[1]}"
        )
