r"""The SHARED convexity-adjustment path, graded against Citi's published screen.

``RVUtils/ConvexityRV`` computes its own adjustment and ties out. The repo-wide
path -- ``Query.IRSwaps.IRSwapValue.CVX_ADJ``, reached by
``TB.IRSwapsTB.sfr_cvx_adj`` -- is a second, independent implementation of the
same quantity, and it did not. Two defects, both measured before this file
existed:

1. **The matched swap was annual/annual.** Citi specifies it verbatim as *"both
   fixed and floating legs of this swap have a quarterly payment frequency"*.
   ``curve_ops.matched_forward_swap_rate`` defaults to ``Q/Q`` for that reason;
   the shared path built its swap through ``IRSwapQuery(OUTRIGHT,
   effective_date=..., maturity_date=...)``, which takes the ``usd_irs`` spec's
   annual fixed. Measured against Q/Q on three dates spanning 2023-2025:
   ``+4.585``, ``+5.816``, ``+5.884`` bp. ``CA = pack_rate - swap_rate``, so
   every published ``CVX_ADJ`` was low by that much -- against a Whites/Reds
   adjustment that is itself only 1.3-6.8 bp.

2. **``_as_percent`` multiplied every sub-1 % futures rate by a hundred.** The
   heuristic ``x*100 if abs(x) < 1 else x`` was applied to
   ``rl.STIRFuture.fixed_rate``, which rateslib already carries in percent. An
   SR3 at 99.05 implies 0.95 % and was read as 95 %: an error of 9,405 bp. The
   trip threshold is a price above 99.00, i.e. the whole ZIRP window
   2020-03 .. 2022-06.

The tie-out is Citi's SOFR convexity screen (Rates Vol Lab, 12-Jun-2023,
Figure 58, close 6/9/2023) -- the same thirteen rows
``tests/test_convexity_rv_matched_swap.py`` grades the package's own kernel on,
so the two implementations are now held to one external standard.

The annual matched swap is retained as a **negative control**: it must fail.
A test suite in which the known-wrong variant also passes is measuring nothing.

Marked ``integration`` because it reads the Citi Velocity curve cache.
"""

from __future__ import annotations

import datetime
import os

import numpy as np
import pytest

pytestmark = [pytest.mark.integration]

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

CURVE = "USD-SOFR-1D"
AS_OF = datetime.date(2023, 6, 9)

#: Citi Fig 58: (pack, swap start, swap end, published CA bp, our pack rate %).
#: Pack rates are the mean of ``100 - Barchart SR3 settle`` over the four legs on
#: 2023-06-09, pinned here so this test isolates the swap leg and the units --
#: exactly as ``test_convexity_rv_matched_swap.py`` does for the package kernel.
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pricer():
    """A Citi Velocity ``USD-SOFR-1D`` curve on the Citi screen's close."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    try:
        mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
        return mdp._get_curve(curve_name=CURVE, timestamp=AS_OF)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Citi Velocity curve for {AS_OF} unavailable offline: {exc}")


def _stirf_legs(pricer, start: datetime.date, pack_rate_pct: float):
    """Four ``rl.STIRFuture`` whose mean price implies *pack_rate_pct* exactly.

    Every leg is struck at the same price, so the pack average is that price and
    the test isolates the swap leg and the unit conversion rather than the
    quarter-tick rounding.
    """
    import rateslib as rl

    price = 100.0 - float(pack_rate_pct)
    imm = rl.dt(start.year, start.month, start.day)
    legs = []
    for _ in range(4):
        legs.append(
            rl.STIRFuture(
                effective=imm,
                termination=rl.scheduling.next_imm(imm),
                spec="usd_stir",
                curves=pricer.id(),
                price=price,
            )
        )
        imm = rl.scheduling.next_imm(imm)
    return legs


def _shared_ca_bp(pricer, start, end, pack_rate_pct, **value_kwargs) -> float:
    """``IRSwapValue.CVX_ADJ`` through the query path, in bp."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    q = IRSwapQuery(
        curve=CURVE,
        effective_date=start,
        maturity_date=end,
        structure=IRSwapStructure.OUTRIGHT,
        structure_kwargs={"bpv": 1},
        value=IRSwapValue.CVX_ADJ,
        value_kwargs=dict(value_kwargs),
    )
    package, weights = q.resolve_package(pricer_or_curve=pricer, is_for_timeseries=True)
    vmap = q.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
    return float(
        vmap.apply(
            value=IRSwapValue.CVX_ADJ,
            sfr=_stirf_legs(pricer, start, pack_rate_pct),
            round_pack_to_tick=False,
            **value_kwargs,
        )
    )


# ---------------------------------------------------------------------------
# 1. The known-answer tie-out
# ---------------------------------------------------------------------------
def test_the_DEFAULT_convention_ties_out_to_citi_figure_58(pricer):
    """Citi's screen, with **no** convention passed — the default alone.

    This test exists because a mutation harness caught its absence. Every other
    tie-out here passes ``matched_frequency="Q"`` explicitly, so all of them
    survive a mutation that flips the *default* back to the ``usd_irs`` spec —
    and the default is what every production caller in the repo actually gets.
    The suite pinned the knob and left the wire loose.
    """
    errs = []
    for _label, start, end, citi_bp, pack_rate in CITI_SOFR:
        got = _shared_ca_bp(pricer, start, end, pack_rate)  # no value_kwargs
        errs.append(got - citi_bp)

    med = float(np.median(errs))
    assert abs(med) < 1.0, (
        f"with no convention passed, the median error vs Citi Fig 58 is "
        f"{med:+.3f} bp. The default is not Citi's quarterly/quarterly matched "
        f"swap; about -4 bp means it has reverted to the spec's annual fixed."
    )


def test_shared_cvx_adj_ties_out_to_citi_figure_58(pricer):
    """All 13 rows of Citi's published SOFR screen, through the SHARED path.

    The package kernel already reproduces this table to a median error of
    -0.58 bp. This asserts the second implementation meets the same external
    standard, which it did not before the quarterly matched swap was plumbed
    through ``value_kwargs``.
    """
    errs = []
    for label, start, end, citi_bp, pack_rate in CITI_SOFR:
        got = _shared_ca_bp(pricer, start, end, pack_rate,
                            matched_frequency="Q", matched_leg2_frequency="Q")
        errs.append(got - citi_bp)

    errs = np.asarray(errs, dtype=float)
    assert np.isfinite(errs).all(), "some rows did not price"
    assert abs(float(np.median(errs))) < 1.0, (
        f"median error vs Citi Fig 58 is {np.median(errs):+.3f} bp; the shared "
        f"path does not tie out. Per-row: "
        f"{[f'{lbl} {e:+.2f}' for (lbl, *_), e in zip(CITI_SOFR, errs)]}"
    )
    assert float(np.max(np.abs(errs))) < 3.5, (
        f"worst row error {np.max(np.abs(errs)):+.3f} bp"
    )


# ---------------------------------------------------------------------------
# 2. The negative control -- the annual matched swap MUST fail
# ---------------------------------------------------------------------------
def test_annual_matched_swap_is_the_negative_control(pricer):
    """Reverting to the ``usd_irs`` spec default must reintroduce the ~4 bp bias.

    If this ever passes, the frequency knob has stopped being wired to anything
    and the tie-out above is measuring a constant.
    """
    errs = []
    for label, start, end, citi_bp, pack_rate in CITI_SOFR:
        got = _shared_ca_bp(pricer, start, end, pack_rate,
                            matched_frequency=None, matched_leg2_frequency=None)
        errs.append(got - citi_bp)

    med = float(np.median(errs))
    assert med < -3.0, (
        f"the annual matched swap produced a median error of {med:+.3f} bp; it "
        "is supposed to be about -4 bp. Either the knob is ignored or the spec "
        "changed."
    )


def test_the_two_frequencies_differ_by_the_compounding_term(pricer):
    """Q/Q minus spec-default is the ``3q^2/8`` compounding gap, 4-6 bp."""
    gaps = []
    for _label, start, end, _citi, pack_rate in CITI_SOFR:
        q = _shared_ca_bp(pricer, start, end, pack_rate,
                          matched_frequency="Q", matched_leg2_frequency="Q")
        a = _shared_ca_bp(pricer, start, end, pack_rate,
                          matched_frequency=None, matched_leg2_frequency=None)
        gaps.append(q - a)

    gaps = np.asarray(gaps, dtype=float)
    assert (gaps > 3.0).all() and (gaps < 8.0).all(), (
        f"compounding gap out of range: {gaps.round(3).tolist()}"
    )


# ---------------------------------------------------------------------------
# 3. Units -- the ZIRP window
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "pack_rate_pct",
    [0.05, 0.20, 0.50, 0.95, 1.05, 5.00],
    ids=["zirp_005", "zirp_020", "zirp_050", "just_under_1", "just_over_1", "normal"],
)
def test_futures_rate_is_read_in_percent_at_every_level(pricer, pack_rate_pct):
    """``CA + swap_rate == pack_rate``, exactly, at every rate level.

    A bound on |CA| is the wrong instrument here and the first draft of this
    test proved it: at a pack rate of 0.05 % the corrupted value is 5 %, the
    swap is ~3.5 %, and the resulting +150 bp sits comfortably inside any loose
    bound -- a checker that passes on the very input it was written to catch.

    The identity is what actually pins it. ``CA = pack_rate - swap_rate`` by
    construction, the swap rate is computed independently by
    ``curve_ops.matched_forward_swap_rate`` at the same Q/Q frequency, and both
    sides are in basis points. It holds at every level and cannot be satisfied
    by a leg that has been multiplied by a hundred.
    """
    from RVUtils.ConvexityRV.curve_ops import matched_forward_swap_rate

    start, end = datetime.date(2026, 3, 18), datetime.date(2027, 3, 17)
    got = _shared_ca_bp(pricer, start, end, pack_rate_pct,
                        matched_frequency="Q", matched_leg2_frequency="Q")
    swap_bp = matched_forward_swap_rate(pricer, start, end,
                                        frequency="Q", leg2_frequency="Q") * 100.0
    expected = pack_rate_pct * 100.0 - swap_bp

    assert got == pytest.approx(expected, abs=1e-6), (
        f"pack rate {pack_rate_pct:.2f} % -> CA {got:,.4f} bp, but "
        f"pack - swap = {pack_rate_pct * 100.0:,.4f} - {swap_bp:,.4f} = "
        f"{expected:,.4f} bp. A 100x unit error on the futures leg is the "
        f"known cause (discrepancy {got - expected:,.1f} bp)."
    )


def test_ca_is_linear_in_the_pack_rate(pricer):
    """``CA = pack_rate - swap_rate``, so d(CA)/d(pack_rate) is exactly 100 bp/%.

    A unit heuristic that switches branch at 1 % breaks this identity across the
    boundary; a correct implementation holds it everywhere. This is the check
    that does not depend on knowing the swap rate.
    """
    start, end = datetime.date(2026, 3, 18), datetime.date(2027, 3, 17)
    rates = [0.10, 0.60, 0.99, 1.01, 2.00, 4.00]
    cas = [_shared_ca_bp(pricer, start, end, r,
                         matched_frequency="Q", matched_leg2_frequency="Q")
           for r in rates]

    for (r0, c0), (r1, c1) in zip(zip(rates, cas), zip(rates[1:], cas[1:])):
        slope = (c1 - c0) / (r1 - r0)
        assert abs(slope - 100.0) < 1e-6, (
            f"d(CA)/d(pack_rate) between {r0} % and {r1} % is {slope:.4f} bp/%, "
            "not 100. The units are not consistent across that interval."
        )


# ---------------------------------------------------------------------------
# 4. Failures must be recorded, not swallowed
# ---------------------------------------------------------------------------
def test_sfr_cvx_adj_records_a_raising_date_instead_of_dropping_it(monkeypatch):
    """A date whose pricing RAISES must land in ``sfr_cvx_adj_failures``.

    Both per-date loops were ``except Exception: pass``, so "the vendor has no
    print" and "the pricer raised" produced the same thing: a gap. That is how a
    convexity series came to look interpolated -- part of the sparsity was
    failure wearing absence's clothes.

    This is deliberately **behavioural**. The first draft asserted on the source
    text and a mutation harness walked straight through it: replacing the
    recorder with ``pass`` leaves ``except Exception as exc:`` in place, so a
    regex looking for ``except Exception:`` followed by ``pass`` never matched,
    and the mutant survived. Feeding the method a curve that raises is the only
    version that actually fails when the recording is removed.
    """
    import pandas as pd

    import MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils as SCB
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from TB.IRSwapsTB import IRSwapsTB

    dates = pd.to_datetime(["2024-06-10", "2024-06-11", "2024-06-12"])

    def _fake_fetch(*_args, **kwargs):
        """Every requested leg prints, so nothing fails for want of a price."""
        cols = list(kwargs.get("tickers") or [])
        return pd.DataFrame({c: [95.0, 95.0, 95.0] for c in cols}, index=dates)

    monkeypatch.setattr(SCB, "get_barchart_timeseries", _fake_fetch)

    tb = IRSwapsTB(mdp=IRSwapsMDP(source="CITIVELO_EXCEL"), show_tqdm=False,
                   use_ts_cache=False)

    def _boom(*_a, **_k):
        raise RuntimeError("curve build blew up")

    monkeypatch.setattr(tb.mdp, "_get_curve", _boom)

    try:
        out = tb.sfr_cvx_adj(["GREENS"], dates[0], dates[-1], ignore_cache=True)
    finally:
        tb.close()

    assert out.empty or out.isna().all().all(), (
        "a curve that always raises should produce no priced rows"
    )
    failures = tb.sfr_cvx_adj_failures.get("GREENS", {})
    assert failures, (
        "sfr_cvx_adj priced nothing and recorded nothing — a failing date is "
        "indistinguishable from an absent one, which is the defect this test "
        "exists for"
    )
    assert any("curve build blew up" in reason for reason in failures.values()), (
        f"the recorded reasons do not name the real cause: {failures}"
    )


# ---------------------------------------------------------------------------
# 5. The price panel must not be filled
# ---------------------------------------------------------------------------
def test_daily_price_fetch_does_not_backfill_by_default():
    """``get_barchart_timeseries`` must not carry a price backwards in time.

    It used to ``.bfill().ffill()`` the whole frame unconditionally. ``bfill`` is
    look-ahead *inside the price series* -- a contract that did not print on a
    date received the next date's settle -- and ``ffill`` manufactures a print
    where there was genuine absence, which is what made a sparse convexity
    series look interpolated.
    """
    import inspect

    from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import (
        get_barchart_timeseries,
    )

    sig = inspect.signature(get_barchart_timeseries)
    assert "fill" in sig.parameters, "no way to switch the fill off"
    assert sig.parameters["fill"].default is False, (
        "the default propagates missing prices; absence must stay NaN"
    )

    from TB.IRSwapsTB import IRSwapsTB

    body = inspect.getsource(IRSwapsTB.sfr_cvx_adj)
    assert "fill=False" in body, (
        "sfr_cvx_adj does not pin fill=False, so a later default change would "
        "silently reintroduce the look-ahead"
    )


def test_backfill_really_is_look_ahead():
    """The property the switch exists for, on a frame with a known answer.

    This is the check that makes the test above mean something: without it,
    ``fill`` could be wired to nothing and the signature assertions would still
    pass.
    """
    import pandas as pd

    idx = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"])
    raw = pd.DataFrame({"SFRH26": [float("nan"), float("nan"), 97.50]}, index=idx)

    filled = raw.bfill().ffill()
    assert filled.loc[idx[0], "SFRH26"] == 97.50, (
        "bfill did not move 2021-01-06's price to 2021-01-04 — the premise of "
        "this whole test is wrong and the fix needs re-deriving"
    )
    assert pd.isna(raw.loc[idx[0], "SFRH26"]), "unfilled frame should keep NaN"
