"""The matched-maturity swap's payment frequency is not a detail.

Citi specifies it verbatim -- *"both fixed and floating legs of this swap have a
quarterly payment frequency"* -- while the ``usd_irs`` rateslib spec carried by
``USD-SOFR-1D`` quotes **annual** fixed. At a ~3.2% rate the compounding
difference is ~3q^2/8 ~ 3.8bp, the same order as the convexity adjustment being
measured. Using the spec default silently biases every SOFR pack adjustment.

This test pins the fix against Citi's published screen (Rates Vol Lab,
12-Jun-2023, Figure 58, close 6/9/2023) and keeps the annual variant as a
negative control, so a regression that reverts to the spec default fails loudly
rather than shifting every number by 4bp.

Marked ``integration`` because it reads the Citi Velocity curve cache.
"""

import datetime

import numpy as np
import pytest

pytestmark = [pytest.mark.integration]


#: Citi Fig 58: (pack, swap start, swap end, published CA bp, our pack rate)
#: Pack rates are the mean of (100 - Barchart SR3 settle) over the four legs on
#: 2023-06-09, recorded here so the test isolates the swap-leg question.
CITI_SOFR = [
    ("M4-H5", datetime.date(2024, 6, 19), datetime.date(2025, 6, 18), 4.03, 3.7787),
    ("U4-M5", datetime.date(2024, 9, 18), datetime.date(2025, 9, 17), 4.41, 3.5325),
    ("Z4-U5", datetime.date(2024, 12, 18), datetime.date(2025, 12, 17), 5.16, 3.3712),
    ("H5-Z5", datetime.date(2025, 3, 19), datetime.date(2026, 3, 18), 6.10, 3.2750),
    ("M5-H6", datetime.date(2025, 6, 18), datetime.date(2026, 6, 17), 8.24, 3.2225),
    ("U5-M6", datetime.date(2025, 9, 17), datetime.date(2026, 9, 16), 9.77, 3.1937),
    ("Z5-U6", datetime.date(2025, 12, 17), datetime.date(2026, 12, 16), 11.70, 3.1762),
    ("H6-Z6", datetime.date(2026, 3, 18), datetime.date(2027, 3, 17), 13.70, 3.1700),
    ("M6-H7", datetime.date(2026, 6, 17), datetime.date(2027, 6, 16), 15.40, 3.1725),
    ("U6-M7", datetime.date(2026, 9, 16), datetime.date(2027, 9, 15), 16.84, 3.1813),
    ("Z6-U7", datetime.date(2026, 12, 16), datetime.date(2027, 12, 15), 18.27, 3.1988),
    ("H7-Z7", datetime.date(2027, 3, 17), datetime.date(2028, 3, 15), 20.08, 3.2250),
    ("M7-H8", datetime.date(2027, 6, 16), datetime.date(2028, 6, 21), 22.29, 3.2575),
]

AS_OF = datetime.date(2023, 6, 9)
CURVE = "USD-SOFR-1D"


@pytest.fixture(scope="module")
def pricer():
    import contextlib
    import io
    import os

    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

    import pandas as pd

    from BT.data_handler import TimeGrid
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.RATE,
                    tenor="10Y", curve=CURVE, structure_kwargs={"bpv": 1.0})
    ts = pd.Timestamp(AS_OF)
    bt = QueryDrivenBacktest(time_grid=TimeGrid([ts]),
                             strategy=QueryStrategy(name="p", triggers=[]),
                             mdp=IRSwapsMDP(source="CITIVELO_EXCEL"), show_progress=False)
    bt._now = ts
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return bt._pricer_for_query(q, ts)
    except Exception as exc:  # pragma: no cover - cache-dependent
        pytest.skip(f"Citi Velocity curve unavailable for {AS_OF}: {exc}")


def _errors(pricer, **kw):
    from RVUtils.ConvexityRV.curve_ops import matched_forward_swap_rate

    out = []
    for _, s, e, ca_pub, pack_rate in CITI_SOFR:
        r = matched_forward_swap_rate(pricer, s, e, **kw)
        out.append((pack_rate - r) * 100.0 - ca_pub)
    return np.array(out)


def test_quarterly_matched_swap_reproduces_citi(pricer):
    """The whole point: quarterly/quarterly ties out to well inside a bp."""
    err = _errors(pricer)  # default is Q/Q
    assert abs(np.median(err)) < 1.0, f"median error {np.median(err):+.2f}bp"
    assert abs(err.mean()) < 1.0, f"mean error {err.mean():+.2f}bp"


def test_spec_default_annual_is_the_negative_control(pricer):
    """Reverting to the spec's annual fixed must reintroduce a ~4bp bias.

    If this ever passes-as-good, the frequency override has been lost and every
    convexity adjustment downstream is quietly 4bp light."""
    err = _errors(pricer, frequency=None, leg2_frequency=None)
    assert np.median(err) < -2.5, (
        f"expected the annual-fixed bias near -4bp, got {np.median(err):+.2f}bp"
    )


def test_quarterly_is_materially_better_than_the_spec_default(pricer):
    q_err = np.abs(_errors(pricer))
    a_err = np.abs(_errors(pricer, frequency=None, leg2_frequency=None))
    assert np.median(q_err) < 0.5 * np.median(a_err)
