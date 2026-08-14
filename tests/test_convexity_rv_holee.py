"""Known-answer tests for the Ho-Lee convexity adjustment and its inversion.

Two planted answers, one per convention:

**Hull** (``convention="hull"``, ``1/2 sigma^2 T1 T2``). Hull's worked example
(*Options, Futures and Other Derivatives*, Eurodollar futures convexity
adjustment): sigma = 1.2%, a contract expiring in 8 years on a 3M rate
(T1 = 8, T2 = 8.25) gives ``0.5 * 0.012^2 * 8 * 8.25 = 0.004752 = 0.475%``,
which is what the textbook quotes.

**Citi** (``convention="citi"``, ``1/2 sigma^2 T1^2``, the default). Citi's
published SOFR screen, *Rates Vol Lab -- Forward steepener and vol divergence*,
12-Jun-2023, Figure 58, close 6/9/2023: 13 rolling 1y SOFR packs with both the
observed convexity adjustment and the implied vol Citi backed out of it. Feeding
the published CA through this module's inversion must reproduce the published
implied-vol column. That is a genuine external known-answer -- neither the
numbers nor the formula came from this codebase.

A checking tool that is itself wrong reports success and hides the thing it was
built to find, so both the pack-average identity and the convention *dis*tinction
are tested, not only round-trips.
"""

import datetime

import numpy as np
import pytest

from RVUtils.ConvexityRV.holee import (
    ACCRUAL_3M,
    ho_lee_ca,
    ho_lee_ca_bp,
    implied_vol_from_ca,
    implied_vol_from_ca_bp,
    pack_ca_bp,
    pack_time_weight,
)
from RVUtils.ConvexityRV.packs import (
    imm_date,
    pack_t1s,
    parse_contract_code,
    third_wednesday,
)

# --------------------------------------------------------------- Hull form


def test_hull_worked_example_decimal():
    """Hull: sigma=1.2%, T1=8, T2=8.25 -> CA = 0.475%."""
    ca = ho_lee_ca(sigma=0.012, t1=8.0, t2=8.25)
    assert ca == pytest.approx(0.004752, abs=1e-9)
    assert ca * 100 == pytest.approx(0.4752, abs=1e-6)  # percent, as Hull quotes


def test_hull_worked_example_bp():
    """Same number through the bp-unit boundary -- catches 1e4 slips."""
    assert ho_lee_ca_bp(sigma_bp=120.0, t1=8.0, t2=8.25) == pytest.approx(47.52, abs=1e-6)


def test_inversion_recovers_hull_vol():
    """A degenerate one-contract pack reduces to the single-contract formula."""
    t1s = [8.0]
    assert pack_time_weight(t1s, convention="hull") == pytest.approx(8.0 * 8.25)
    assert implied_vol_from_ca(0.004752, t1s, convention="hull") == pytest.approx(0.012, rel=1e-9)
    assert implied_vol_from_ca_bp(47.52, t1s, convention="hull") == pytest.approx(120.0, rel=1e-9)


# --------------------------------------------------------------- Citi form


def test_citi_convention_is_t1_squared_and_is_the_default():
    t1s = [1.0, 1.25, 1.5, 1.75]
    assert pack_time_weight(t1s, convention="citi") == pytest.approx(
        np.mean(np.array(t1s) ** 2)
    )
    assert pack_time_weight(t1s) == pack_time_weight(t1s, convention="citi")


def test_the_two_conventions_are_not_interchangeable():
    """Guards against a silent swap: Hull's T1*T2 exceeds Citi's T1^2 by
    accrual*T1, which is what produced the maturity-dependent bias that ruled
    Hull's form out against Citi's tables."""
    t1s = [2.0, 2.25, 2.5, 2.75]
    citi = pack_time_weight(t1s, convention="citi")
    hull = pack_time_weight(t1s, convention="hull")
    assert hull > citi
    assert hull - citi == pytest.approx(ACCRUAL_3M * np.mean(t1s))


def test_unknown_convention_raises():
    with pytest.raises(ValueError):
        pack_time_weight([1.0, 1.25, 1.5, 1.75], convention="vasicek")


# ---------------------------------------------- Citi SOFR screen tie-out

#: Citi, Rates Vol Lab (12-Jun-2023) Figure 58, close 6/9/2023.
#: (pack label, first contract, CA bp, published implied vol bp/yr)
CITI_SOFR_20230609 = [
    ("M4-H5", ("M", 4), 4.03, 199.5),
    ("U4-M5", ("U", 4), 4.41, 178.1),
    ("Z4-U5", ("Z", 4), 5.16, 167.7),
    ("H5-Z5", ("H", 5), 6.10, 161.6),
    ("M5-H6", ("M", 5), 8.24, 168.5),
    ("U5-M6", ("U", 5), 9.77, 166.3),
    ("Z5-U6", ("Z", 5), 11.70, 166.5),
    ("H6-Z6", ("H", 6), 13.70, 166.0),
    ("M6-H7", ("M", 6), 15.40, 163.1),  # Blues
    ("U6-M7", ("U", 6), 16.84, 159.0),
    ("Z6-U7", ("Z", 6), 18.27, 155.1),
    ("H7-Z7", ("H", 7), 20.08, 152.8),
    ("M7-H8", ("M", 7), 22.29, 151.9),  # Golds
]

AS_OF_20230609 = datetime.date(2023, 6, 9)


def _pack_contracts(first_code: str) -> list:
    """The four (year, month) legs of a pack given its first contract code."""
    y, m = parse_contract_code(first_code, AS_OF_20230609)
    out = [(y, m)]
    for _ in range(3):
        m += 3
        if m > 12:
            m -= 12
            y += 1
        out.append((y, m))
    return out


def test_imm_dates_are_third_wednesdays():
    """Anchor the IMM helper on dates stated verbatim in Citi's own trade
    recommendation: the H0-Z0 matched swap ran 3/18/20 to 3/17/21."""
    assert imm_date(2020, 3) == datetime.date(2020, 3, 18)
    assert imm_date(2021, 3) == datetime.date(2021, 3, 17)
    assert third_wednesday(2024, 6) == datetime.date(2024, 6, 19)
    assert third_wednesday(2023, 6) == datetime.date(2023, 6, 21)


def test_pack_contract_expansion():
    assert _pack_contracts("M4") == [(2024, 6), (2024, 9), (2024, 12), (2025, 3)]
    assert _pack_contracts("M6") == [(2026, 6), (2026, 9), (2026, 12), (2027, 3)]


@pytest.mark.parametrize("label,first,ca_bp,iv_pub", CITI_SOFR_20230609)
def test_citi_sofr_implied_vol_row_by_row(label, first, ca_bp, iv_pub):
    """Every published row must reproduce to better than 1%."""
    contracts = _pack_contracts(f"{first[0]}{first[1]}")
    t1s = pack_t1s(AS_OF_20230609, contracts)
    iv = implied_vol_from_ca_bp(ca_bp, t1s)  # citi convention by default
    assert iv == pytest.approx(iv_pub, rel=0.01), f"{label}: got {iv:.1f} vs published {iv_pub}"


def test_citi_sofr_implied_vol_is_unbiased_across_the_table():
    """The whole-table statistic is the real test: a wrong time-weighting shows
    up as a *drift* in the ratio across maturities, not as one bad row."""
    ratios = []
    for label, first, ca_bp, iv_pub in CITI_SOFR_20230609:
        t1s = pack_t1s(AS_OF_20230609, _pack_contracts(f"{first[0]}{first[1]}"))
        ratios.append(implied_vol_from_ca_bp(ca_bp, t1s) / iv_pub)
    ratios = np.array(ratios)
    assert np.median(ratios) == pytest.approx(1.0, abs=0.005)
    assert ratios.max() - ratios.min() < 0.01, "ratio drifts across maturity"


def test_hull_convention_is_rejected_by_the_citi_table():
    """The negative control. Hull's T1*T2 must FAIL to reproduce Citi's column,
    with a monotone maturity drift -- which is the evidence that made T1^2 the
    right choice. If this ever passes, the two conventions have been conflated."""
    ratios = []
    for label, first, ca_bp, iv_pub in CITI_SOFR_20230609:
        t1s = pack_t1s(AS_OF_20230609, _pack_contracts(f"{first[0]}{first[1]}"))
        ratios.append(implied_vol_from_ca_bp(ca_bp, t1s, convention="hull") / iv_pub)
    ratios = np.array(ratios)
    assert ratios.max() < 0.99, "Hull form should undershoot Citi's implied vols"
    # and the miss should get *smaller* with maturity (accrual/T1 shrinks)
    assert ratios[-1] > ratios[0], "expected a monotone maturity drift"


# ------------------------------------------------------------ structural


def test_pack_average_matches_mean_of_contract_adjustments():
    """A pack's model CA is the mean of its four contract CAs, by construction."""
    sigma_bp = 90.0
    t1s = [2.00, 2.25, 2.50, 2.75]
    by_contract = np.mean([ho_lee_ca_bp(sigma_bp, t, t) for t in t1s])  # citi: T2=T1
    assert pack_ca_bp(sigma_bp, t1s) == pytest.approx(by_contract, rel=1e-12)


@pytest.mark.parametrize("conv", ["citi", "hull"])
def test_pack_roundtrip_is_exact(conv):
    sigma_bp = 75.0
    t1s = [1.0, 1.25, 1.5, 1.75]
    ca_bp = pack_ca_bp(sigma_bp, t1s, convention=conv)
    assert implied_vol_from_ca_bp(ca_bp, t1s, convention=conv) == pytest.approx(sigma_bp, rel=1e-10)


def test_adjustment_grows_with_expiry_and_vol():
    assert ho_lee_ca_bp(100.0, 5.0, 5.25) > ho_lee_ca_bp(100.0, 2.0, 2.25)
    assert ho_lee_ca_bp(120.0, 5.0, 5.25) > ho_lee_ca_bp(100.0, 5.0, 5.25)


@pytest.mark.parametrize("bad_ca", [0.0, -1e-6, float("nan")])
def test_non_positive_ca_is_not_invertible(bad_ca):
    """Citi prints n/a for these; we must return NaN, not a complex number and
    not a silent zero."""
    assert np.isnan(implied_vol_from_ca(bad_ca, [2.0, 2.25, 2.5, 2.75]))


def test_empty_pack_is_nan():
    assert np.isnan(pack_time_weight([]))
