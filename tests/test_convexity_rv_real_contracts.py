"""Known-answer tests for strategy 1 on REAL LISTED CONTRACTS.

Three tiers, so the fast gate stays fast:

* **Hand-computed / synthetic** (no I/O). A tiny contract ladder whose selected
  expiry, gap, roll count and straddle size are known on paper before the code
  runs.
* **Algebraic identities** (no I/O). The Bachelier straddle premium against its
  closed form; the 25-delta strike geometry and its SIGN; the density's
  normalisation; the CM/real join key.
* **Data-backed** (``@pytest.mark.slow``, skipped when the parquets are absent).
  The tie-outs that make the study trustworthy: the real-contract panel's
  breakeven column must equal strategy 1's stored one row for row, the CM
  control and the real run must share their curve rows exactly, and the
  ``swaption_only`` gate must be IDENTICAL between the two runs (it does not
  touch the listed benchmark, so any difference there means the two frames are
  misaligned and every other number in the study is suspect).

**Verifying the checker itself.** A test that passes against mutated code is a
test that does not test, so eleven plausible wrong implementations were planted
in ``strat1_real_contracts.py`` and the suite re-run against each. **Measured
log** (see ``MUTATION_LOG`` below for the machine-readable version):

=====================================================  ========  ===================================
mutation                                               result    caught by
=====================================================  ========  ===================================
``listed_gap_days`` unsigned (``abs``)                 CAUGHT    gap_is_signed_and_negative
25-delta strikes placed with the ATM vol, not each     CAUGHT    strike_offsets_use_own_vol
  quote's own
25-delta call placed ABOVE the forward yield           CAUGHT    strike_offset_signs
straddle premium ``sigma*sqrt(T)`` (drop sqrt(2/pi))   CAUGHT    straddle_premium_closed_form
straddle sized off the FULL 1y carry, not pro-rated    CAUGHT    straddle_scales_with_tte
``listed_symbol`` set to the contract code             CAUGHT    horizon_rule_picks_the_longest [*]
CM/real comparison joined on ``date`` alone            CAUGHT    pooled_join_is_by_date_and_structure
``listed_cm_days`` set to the ACHIEVED tte             CAUGHT    cm_days_is_the_target
roll counted on every date, not on changes             CAUGHT    roll_report_counts_changes
``select_by_tte`` default gap left in place at 365d    CAUGHT    horizon_target_has_no_gap_cap
``real_shift_density`` returns a spike unchecked       CAUGHT    density_rejects_degenerate
``cm_gap_days`` computed as ``target - 365``          CAUGHT    cm_gap_names_a_series_that_exists
=====================================================  ========  ===================================

Twelve of twelve caught. The mutations were applied one at a time to the
installed module, the fast suite re-run under ``-x``, then reverted, and the
module was compared byte-for-byte against its original afterwards.
``MUTATION_LOG`` records the test that actually fired so a future edit that
removes the test also removes the evidence for it.

``[*]`` the run is ``-x``, so what is recorded is the FIRST test to fail, not
necessarily the most specific one. ``test_benchmark_symbol_is_stable`` fails on
that mutation too; ``test_horizon_rule_picks_the_longest_contract`` simply sorts
earlier. Recording what fired rather than what "should have" is the point -- the
alternative is a log that describes an intention.

The straddle-premium mutation is the one planted in SHARED code
(``strat1_curve_gamma.atmf_straddle_premium_bp``), because that is where the
sizing kernel lives and this module reuses it rather than reimplementing it.
"""

from __future__ import annotations

import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import strat1_real_contracts as rc
from RVUtils.ConvexityRV import strat1_threeway as tw

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "data" / "convexity_rv"
PANEL = DATA / "strat1_contracts_panel.parquet"
CM_CONTROL = DATA / "strat1_contracts_cm_control.parquet"
CONTRACTS = DATA / "listed_contract_vol.parquet"
S1 = DATA / "strat1_signal_panel.parquet"

#: Machine-readable version of the mutation log in the module docstring. Kept as
#: data so ``test_mutation_log_is_complete`` can assert every entry names a test
#: that still exists -- deleting a test would otherwise silently delete the
#: evidence that the suite catches that mutation.
MUTATION_LOG = {
    "gap_days_unsigned": "test_gap_is_signed_and_negative",
    "strikes_use_atm_vol": "test_strike_offsets_use_own_vol",
    "call_strike_above_forward": "test_strike_offset_signs",
    "premium_drops_sqrt_2_over_pi": "test_straddle_premium_closed_form",
    "straddle_uses_full_carry": "test_straddle_scales_with_tte",
    "symbol_is_contract_code": "test_horizon_rule_picks_the_longest_contract",
    "join_on_date_only": "test_pooled_join_is_by_date_and_structure",
    "cm_days_is_achieved_tte": "test_cm_days_is_the_target",
    "roll_counts_every_date": "test_roll_report_counts_changes",
    "horizon_target_capped": "test_horizon_target_has_no_gap_cap",
    "density_spike_accepted": "test_density_rejects_degenerate",
    "cm_gap_is_target_minus_365": "test_cm_gap_names_a_series_that_exists",
}


# --------------------------------------------------------------------- fixtures


def _ladder() -> pd.DataFrame:
    """A four-contract US ladder on three dates, with every answer planted.

    Expiries are chosen so the horizon rule (365-day target) MUST pick ``USZ26``
    on the first two dates and ``USH27`` on the third -- i.e. exactly one roll --
    and so the 30-day rule picks a different contract on every date.

    ==========  =======  ==========  =========  ==================================
    date        code     expiry      tte_days   planted
    ==========  =======  ==========  =========  ==================================
    2026-01-05  USG26    2026-01-23        18   nearest to 30d on d0 (gap -12)
    2026-01-05  USH26    2026-02-20        46   nearest to 30d is USG26, not this
    2026-01-05  USZ26    2026-11-20       319   longest -> the H365 pick
    2026-02-02  USH26    2026-02-20        18   nearest to 30d on d1
    2026-02-02  USZ26    2026-11-20       291   longest -> the H365 pick (no roll)
    2026-03-02  USZ26    2026-11-20       263   NOT longest any more
    2026-03-02  USH27    2027-02-19       354   longest -> the H365 pick (ROLL)
    ==========  =======  ==========  =========  ==================================
    """
    rows = [
        ("2026-01-05", "USG26", "2026-01-23", "serial", 80.0),
        ("2026-01-05", "USH26", "2026-02-20", "quarterly", 82.0),
        ("2026-01-05", "USZ26", "2026-11-20", "quarterly", 90.0),
        ("2026-02-02", "USH26", "2026-02-20", "quarterly", 84.0),
        ("2026-02-02", "USZ26", "2026-11-20", "quarterly", 92.0),
        ("2026-03-02", "USZ26", "2026-11-20", "quarterly", 88.0),
        ("2026-03-02", "USH27", "2027-02-19", "quarterly", 96.0),
    ]
    out = []
    for d, code, exp, kind, v in rows:
        ts, ex = pd.Timestamp(d), pd.Timestamp(exp)
        out.append({
            "date": ts, "symbol": code, "vendor_column": f"{code} ABPV",
            "root": "US", "asset": "UST", "contract_code": code,
            "contract_kind": kind, "expiry_date": ex,
            "tte_years": (ex - ts).days / 365.0,
            "value_type": "ABPV", "value": v,
        })
    return pd.DataFrame(out)


def _curve_panel() -> pd.DataFrame:
    """Three dates x one structure of a stored-strategy-1-shaped signal panel."""
    rows = []
    for d, be, atmf, carry in (("2026-01-05", 3.0, 5.0, -0.8),
                               ("2026-02-02", 6.5, 5.0, -0.4),
                               ("2026-03-02", 4.0, 5.0, +0.2)):
        r = {"date": pd.Timestamp(d), "structure": "5Y/30Y",
             "breakeven_vol_bp_day": be, "breakeven_status": "root",
             "atmf_vol_bp_day": atmf, "carry_roll_bp": carry}
        for s in (-250, -200, -150, -100, -50, -25, 0, 25, 50, 100, 150, 200, 250):
            r[f"payoff_bp_{s:+d}"] = float(abs(s)) / 100.0 + carry
        rows.append(r)
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def synth_panel() -> pd.DataFrame:
    return rc.build_longend_contract_panel(
        _curve_panel(), _ladder(), rc.RealContractConfig(),
        structures=["5Y/30Y"], roots=["US"], targets=["H365", "D30"])


# ============================================================ selection / geometry


def test_horizon_rule_picks_the_longest_contract(synth_panel):
    """The 365-day target is beyond every listed expiry, so nearest == longest.

    Planted: ``USZ26`` on the first two dates, ``USH27`` on the third.
    """
    h = synth_panel.reset_index()
    h = h[h["listed_symbol"] == "US@H365"].sort_values("date")
    assert list(h["listed_contract_code"]) == ["USZ26", "USZ26", "USH27"]


def test_thirty_day_rule_picks_a_different_contract(synth_panel):
    """The two targets must not degenerate to the same series, or the CM-vs-real
    comparison would be comparing a benchmark to itself."""
    d = synth_panel.reset_index()
    d = d[d["listed_symbol"] == "US@D30"].sort_values("date")
    assert list(d["listed_contract_code"])[:2] == ["USG26", "USH26"]


def test_gap_is_signed_and_negative(synth_panel):
    """``listed_gap_days`` is expiry-minus-horizon and is NEGATIVE here by
    construction -- every listed expiry falls before the one-year horizon.

    An unsigned gap would read as "the option expires after the horizon" and
    would invert the term-structure argument that follows from it.
    """
    h = synth_panel.reset_index()
    h = h[h["listed_symbol"] == "US@H365"].sort_values("date")
    gaps = h["listed_gap_days"].to_numpy(dtype=float)
    assert (gaps < 0).all()
    # 2026-01-05 -> 2026-11-20 is 319 days, horizon 365 => -46
    assert gaps[0] == pytest.approx(319.0 - 365.0, abs=1e-9)


def test_cm_days_is_the_target(synth_panel):
    """``listed_cm_days`` carries the TARGET, not the achieved time to expiry.

    Downstream, ``select_longend_benchmark(cm_days=...)`` and every per-benchmark
    groupby key on it. Filling it with the achieved tte would make it change
    every day and shatter one benchmark into hundreds.
    """
    d = synth_panel.reset_index()
    for sym, want in (("US@H365", 365), ("US@D30", 30)):
        g = d[d["listed_symbol"] == sym]
        assert set(g["listed_cm_days"].astype(int)) == {want}


def test_benchmark_symbol_is_stable(synth_panel):
    """``listed_symbol`` identifies the BENCHMARK and must not roll with the
    contract -- ``longend_basis_frame`` and ``basis_persistence`` group by it to
    build a time series, and a per-contract symbol would fragment it."""
    d = synth_panel.reset_index()
    h = d[d["listed_symbol"] == "US@H365"]
    assert h["listed_symbol"].nunique() == 1
    assert h["listed_contract_code"].nunique() == 2      # it DID roll


def test_horizon_target_has_no_gap_cap():
    """The 365-day rule must not inherit ``select_by_tte``'s 20-day default cap.

    The longest listed UST option expiry is 241 days, so a finite cap at a
    365-day target matches NOTHING -- and would return an empty study rather
    than an honest one. Pinned as a property of :data:`TARGETS`.
    """
    cap = next(g for n, _d, g in rc.TARGETS if n == "H365")
    assert not np.isfinite(cap)
    for name, _days, g in rc.TARGETS:
        if name != "H365":
            assert np.isfinite(g), f"{name} must keep a finite cap"


def test_strike_offset_signs():
    """The 25-delta CALL sits BELOW the forward yield and the PUT above it.

    These are options on the futures PRICE and the panel is a YIELD vol, so a
    call on price is a call on -yield. Getting this backwards mirrors the skew
    and turns a put-bid smile into a call-bid one -- the single most damaging
    silent error available in this file.
    """
    kc, kp = rc.smile_strike_offsets(94.0, 93.0, 97.0, 0.36)
    assert kc < 0 < kp


def test_strike_offsets_use_own_vol():
    """Each quote is placed at ITS OWN vol's standard deviation, not at the ATM's.

    With a 4-point vol difference between the wings the two conventions differ by
    a measurable amount, so this is a real distinction and not a formality.
    """
    kc, kp = rc.smile_strike_offsets(94.0, 90.0, 98.0, 0.25)
    assert kc == pytest.approx(-rc.DELTA25_SIGMAS * 90.0 * 0.5, rel=1e-12)
    assert kp == pytest.approx(+rc.DELTA25_SIGMAS * 98.0 * 0.5, rel=1e-12)
    assert abs(kp) > abs(kc)                    # the higher-vol wing sits further out


def test_delta25_constant_is_the_normal_quantile():
    """0.674490 is ``Phi^-1(0.75)``, i.e. the 25-delta point of a normal model."""
    from scipy.stats import norm
    assert rc.DELTA25_SIGMAS == pytest.approx(float(norm.ppf(0.75)), rel=1e-12)


# ==================================================================== the smile


def test_three_point_smile_passes_through_its_quotes():
    """The fitted quadratic reproduces the three quoted vols exactly."""
    atm, c, p, t = 94.0, 92.0, 97.0, 0.36
    sm = rc.three_point_smile(atm, c, p, t, n_points=201)
    assert sm is not None
    kc, kp = rc.smile_strike_offsets(atm, c, p, t)
    assert float(np.interp(0.0, sm["offset_bp"], sm["vol_bp"])) == pytest.approx(atm, rel=1e-6)
    assert float(sm["vol_bp"].iloc[0]) == pytest.approx(c, rel=1e-9)
    assert float(sm["vol_bp"].iloc[-1]) == pytest.approx(p, rel=1e-9)
    assert float(sm["offset_bp"].iloc[0]) == pytest.approx(kc, rel=1e-12)
    assert float(sm["offset_bp"].iloc[-1]) == pytest.approx(kp, rel=1e-12)


def test_three_point_smile_refuses_bad_input():
    """``None``, not a repaired curve -- the caller must fall back deliberately."""
    assert rc.three_point_smile(np.nan, 92.0, 97.0, 0.36) is None
    assert rc.three_point_smile(94.0, 92.0, 97.0, 0.0) is None
    assert rc.three_point_smile(94.0, -1.0, 97.0, 0.36) is None


def test_density_is_normalised_and_centred():
    """A SYMMETRIC smile must give a density that sums to 1 and has ~zero mean.

    Symmetric input is the known answer: with call vol == put vol the risk-neutral
    distribution of the shift is symmetric about zero, so its first moment is a
    hand-computable 0 rather than something read off the output.
    """
    grid = np.arange(-250.0, 251.0, 25.0)
    sm = rc.three_point_smile(90.0, 92.0, 92.0, 0.5)
    w = rc.real_shift_density(sm, grid, tte_years=0.5)
    assert w is not None
    assert float(w.sum()) == pytest.approx(1.0, abs=1e-12)
    assert float(np.dot(w, grid)) == pytest.approx(0.0, abs=1.0)


def test_density_skews_the_way_the_smile_does():
    """A put-bid smile (put vol > call vol, i.e. RR < 0) must put more mass on
    HIGHER yields. This is the sign check that connects the strike geometry to
    the density -- both could be individually consistent and jointly mirrored."""
    grid = np.arange(-250.0, 251.0, 10.0)
    w = rc.real_shift_density(rc.three_point_smile(90.0, 86.0, 96.0, 0.5), grid,
                              tte_years=0.5)
    assert w is not None
    assert float(np.dot(w, grid)) > 0.0


def test_density_rejects_degenerate():
    """A density concentrated in one grid cell is a failed second derivative, not
    a distribution, and must come back ``None`` rather than turn ``E[payoff]``
    into the payoff at a single shift."""
    spike = np.zeros(11)
    spike[5] = 1.0
    assert rc.real_shift_density(None, np.arange(11.0), tte_years=1.0) is None
    # a near-zero tte collapses the whole distribution onto the forward
    w = rc.real_shift_density(rc.three_point_smile(90.0, 90.0, 90.0, 1e-8),
                              np.arange(-250.0, 251.0, 25.0), tte_years=1e-8)
    assert w is None or float(w.max()) <= 0.99


# ============================================================== funded straddle


def test_straddle_premium_closed_form():
    """``sqrt(2/pi) * sigma * sqrt(T)`` -- the Bachelier ATM straddle, exactly.

    Dropping the ``sqrt(2/pi)`` (a 25% error) or the ``sqrt(T)`` (a factor of 1.7
    at a 133-day expiry) both survive a plot and neither survives this.
    """
    from RVUtils.ConvexityRV.strat1_curve_gamma import atmf_straddle_premium_bp
    assert atmf_straddle_premium_bp(100.0, 0.25) == pytest.approx(
        math.sqrt(2.0 / math.pi) * 100.0 * 0.5, rel=1e-12)


def test_straddle_scales_with_tte(synth_panel):
    """Premium == carry PRO-RATED to the option's own life, not the full year.

    The option expires long before the horizon, so funding a full year's carry
    with it would oversize the straddle by ``1 / tte`` -- a factor of ~2.7 at the
    measured median 133-day expiry. Both are emitted and their ratio is exactly
    ``tte_years``, which is the arithmetic this pins.
    """
    h = synth_panel.reset_index()
    h = h[h["listed_symbol"] == "US@H365"]
    st = rc.funded_straddle_frame(h, None, rc.RealContractConfig())
    r = (st["straddle_dv01"].to_numpy(dtype=float)
         / st["straddle_dv01_full_carry"].to_numpy(dtype=float))
    assert np.allclose(r, st["listed_tte"].to_numpy(dtype=float), rtol=1e-12)


def test_straddle_flags_positive_carry(synth_panel):
    """Where the flattener CARRIES POSITIVELY there is nothing to fund, and the
    row says so instead of quietly sizing a straddle off ``|carry|``."""
    h = synth_panel.reset_index()
    h = h[h["listed_symbol"] == "US@H365"].sort_values("date")
    st = rc.funded_straddle_frame(h, None, rc.RealContractConfig())
    assert list(st["carry_negative"]) == [True, True, False]


def test_contract_count_needs_a_futures_dv01(synth_panel):
    """Without ``fv01`` the contract count is NaN, and the schema is unchanged.

    A count silently defaulted to a nominal DV01 would be the one number in this
    study a reader would take straight to a ticket.
    """
    h = synth_panel.reset_index()
    h = h[h["listed_symbol"] == "US@H365"]
    st = rc.funded_straddle_frame(h, None, rc.RealContractConfig())
    assert "n_contracts" in st.columns
    assert st["n_contracts"].isna().all()

    fv = pd.DataFrame({"root": ["US"] * 3,
                       "date": pd.to_datetime(["2026-01-02", "2026-02-02", "2026-03-02"]),
                       "fv01_points_per_bp": [0.14, 0.14, 0.14],
                       "futures_price": [119.0] * 3, "ctd_mod_duration": [11.7] * 3})
    st2 = rc.funded_straddle_frame(h, fv, rc.RealContractConfig())
    assert np.isfinite(st2["n_contracts"].to_numpy(dtype=float)).any()
    # n_contracts * DV01/contract must reconstruct the straddle DV01
    n = st2["n_contracts"].to_numpy(dtype=float)
    dv = st2["dv01_usd_per_contract"].to_numpy(dtype=float)
    assert np.allclose(n * dv, st2["straddle_dv01"].to_numpy(dtype=float), rtol=1e-10)


# ======================================================================== roll


def test_roll_report_counts_changes(synth_panel):
    """Exactly ONE roll is planted (``USZ26`` -> ``USH27``) over three dates."""
    r = rc.contract_roll_report(synth_panel)
    h = r[r["listed_symbol"] == "US@H365"]
    assert len(h) == 1
    assert int(h["n_rolls"].iloc[0]) == 1
    assert int(h["n_days"].iloc[0]) == 3


def test_cm_gap_names_a_series_that_exists(synth_panel):
    """``cm_gap_days`` is the CONTROL's gap, not ``target - 365``.

    The naive version returns 0.0 on the ``H365`` row, which reads as "constant
    maturity matched the horizon perfectly" -- when in fact **there is no
    365-day constant-maturity series**: the vendor quotes 30, 60 and 90 days
    only. That single 0.0 would invert the entire finding of §4.
    """
    s = rc.contract_selection_report(synth_panel, _ladder(), cm_control_days=30)
    h = s.set_index("listed_symbol")
    assert (h["cm_gap_days"] == -335.0).all()
    assert h.loc["US@H365", "gap_improvement_days"] > 0, (
        "the horizon rule must get CLOSER to the horizon than the 30-day control")
    assert h.loc["US@D30", "gap_improvement_days"] == pytest.approx(0.0, abs=15.0), (
        "a 30-day-target contract is about as far from the horizon as the 30-day "
        "constant maturity -- if it looked like a big improvement the column is wrong")


def test_selection_report_measures_longest_against_the_ladder(synth_panel):
    """``frac_selected_is_longest`` is measured against the FULL ladder.

    At the 365-day target it must come back exactly 1.0 -- the target is beyond
    every expiry -- and at the 30-day target it must not, or the two rules are
    not distinguishable and the comparison is vacuous.
    """
    s = rc.contract_selection_report(synth_panel, _ladder())
    h = s.set_index("listed_symbol")
    assert h.loc["US@H365", "frac_selected_is_longest"] == pytest.approx(1.0)
    assert h.loc["US@D30", "frac_selected_is_longest"] < 1.0


# ============================================================ the CM comparison


def test_pooled_join_is_by_date_and_structure():
    """The CM-vs-real table must join on ``(date, structure)``, never on date.

    With four structures a date-only join cross-multiplies the pooled row 4x4 and
    reports a disagreement rate that is entirely the cross product -- 17% where
    the truth is 0.6%. Pinned by planting a panel where the two benchmarks agree
    on EVERY row, so any pooled disagreement at all is the join.
    """
    cur = _curve_panel()
    cur2 = cur.copy()
    cur2["structure"] = "30Y/50Y"
    cur = pd.concat([cur, cur2], ignore_index=True)
    panel = rc.build_longend_contract_panel(
        cur, _ladder(), rc.RealContractConfig(),
        structures=["5Y/30Y", "30Y/50Y"], roots=["US"], targets=["H365", "D30"])
    t = rc.cm_vs_real_table(panel, panel, real_symbol="US@H365", cm_symbol="US@H365")
    pooled = t[t["structure"] == "POOLED"].iloc[0]
    assert float(pooled["frac_signal_differs"]) == 0.0
    assert int(pooled["n_days"]) == int(t[t["structure"] != "POOLED"]["n_days"].sum())


def test_unavailable_roots_are_recorded():
    """UL and TN are named, with the measured failure, so the sector limitation
    is data rather than a footnote."""
    assert set(rc.UNAVAILABLE_REAL_ROOTS) == {"UL", "TN"}
    assert "30Y/50Y" in rc.UNAVAILABLE_REAL_ROOTS["UL"]["sector_primary_for"]
    note = rc.real_sector_note("30Y/50Y")
    assert note["sector_primary"] == "UL"
    assert note["sector_matched"] is False
    assert note["limitation"]
    assert rc.real_sector_note("5Y/30Y")["sector_matched"] is True


def test_lazy_reexports_resolve_without_a_cycle():
    """``strat1_listed`` and ``strat1_threeway`` expose the real-contract API.

    The re-export is lazy because the three modules form a cycle if it is not
    (``strat1_listed -> strat1_real_contracts -> strat1_threeway ->
    strat1_listed``). Importing each of the three FIRST, in a clean module table,
    is what proves the cycle is actually broken rather than merely ordered
    around -- an eager import survives whichever module happens to be imported
    first in the test process and fails for the next caller.
    """
    import subprocess
    import sys

    #: Run in a SUBPROCESS, one per starting module. Deleting entries from
    #: ``sys.modules`` in-process would leave the rest of the suite holding stale
    #: class objects, and the identity assertions below would then fail for a
    #: reason that has nothing to do with the import graph.
    repo = str(pathlib.Path(__file__).resolve().parents[1])
    for first in ("strat1_listed", "strat1_threeway", "strat1_real_contracts"):
        p = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {repo!r});"
             f"import RVUtils.ConvexityRV.{first} as m; print(m.__name__)"],
            capture_output=True, text=True)
        assert p.returncode == 0, (
            f"importing {first} FIRST failed -- the import cycle is not broken:\n"
            f"{p.stderr[-1500:]}")

    from RVUtils.ConvexityRV import strat1_listed as sl
    from RVUtils.ConvexityRV import strat1_threeway as tw2

    assert sl.RealContractConfig is rc.RealContractConfig
    assert sl.build_longend_contract_panel is rc.build_longend_contract_panel
    assert sl.HEADLINE_ROOT == rc.HEADLINE_ROOT
    assert tw2.real_threeway_frames is rc.real_threeway_frames
    #: Prefixed on the three-way module: a bare ``HEADLINE_ROOT`` next to that
    #: module's own ``HEADLINE_ROLE`` / ``HEADLINE_CM_DAYS`` would read as part of
    #: the constant-maturity set while meaning something else.
    assert tw2.REAL_HEADLINE_ROOT == rc.HEADLINE_ROOT
    assert tw2.HEADLINE_ROLE == "primary" and tw2.HEADLINE_CM_DAYS == 30
    # the constant-maturity API must be untouched
    for n in ("build_longend_listed_panel", "longend_signal_distribution",
              "Strat1ListedConfig", "listed_signal_row", "signal_distribution"):
        assert hasattr(sl, n), n
    for n in ("threeway_frame", "longend_verdict", "flip_threshold_table",
              "all_gate_books", "apply_gate", "select_longend_benchmark"):
        assert hasattr(tw2, n), n
    with pytest.raises(AttributeError):
        sl.definitely_not_a_real_name


def test_mutation_log_is_complete():
    """Every mutation in the log names a test that still exists in this module."""
    here = set(globals())
    missing = sorted(t for t in MUTATION_LOG.values() if t not in here)
    assert not missing, f"mutation log references deleted tests: {missing}"


# =============================================================== data-backed


@pytest.mark.slow
@pytest.mark.skipif(not (PANEL.exists() and S1.exists()),
                    reason="real-contract artifacts not built")
def test_curve_side_is_reused_verbatim():
    """The real-contract panel's curve columns must EQUAL strategy 1's stored ones.

    The whole study is a controlled substitution of one benchmark, so if the
    curve side moved at all the comparison is measuring two things at once.
    """
    panel = pd.read_parquet(PANEL)
    s1 = pd.read_parquet(S1)
    s1["date"] = pd.to_datetime(s1["date"])
    j = panel.merge(s1, on=["date", "structure"], suffixes=("", "_s1"))
    assert len(j) > 50_000
    for c in ("breakeven_vol_bp_day", "carry_roll_bp", "atmf_vol_bp_day"):
        a = j[c].to_numpy(dtype=float)
        b = j[f"{c}_s1"].to_numpy(dtype=float)
        ok = np.isfinite(a) & np.isfinite(b)
        assert np.array_equal(a[ok], b[ok]), c
        assert np.array_equal(np.isfinite(a), np.isfinite(b)), f"{c} finiteness"


@pytest.mark.slow
@pytest.mark.skipif(not (PANEL.exists() and CM_CONTROL.exists()),
                    reason="real-contract artifacts not built")
def test_swaption_gate_is_identical_across_the_two_runs():
    """``swaption_only`` does not touch the listed benchmark, so it MUST agree.

    This is the alignment check that licenses every other row of the CM-vs-real
    gate table: a non-zero difference here means the two three-way frames are not
    on the same rows and nothing else in that table can be read.
    """
    cfg = tw.longend_config()
    real = pd.read_parquet(PANEL)
    cm = pd.read_parquet(CM_CONTROL)
    three_real = rc.real_threeway_frames(real, cfg)[f"{rc.HEADLINE_ROOT}@{rc.HEADLINE_TARGET}"]
    three_cm = tw.threeway_frame(
        tw.select_longend_benchmark(cm, role=None, root=rc.HEADLINE_ROOT, cm_days=30), cfg)
    t = rc.cm_vs_real_gate_table(three_cm, three_real)
    assert (t["frac_differs_swaption_only"].to_numpy(dtype=float) == 0.0).all()
    assert (t["n_differs_listed_only"].to_numpy(dtype=float) > 0).any()


@pytest.mark.slow
@pytest.mark.skipif(not (PANEL.exists() and CONTRACTS.exists()),
                    reason="real-contract artifacts not built")
def test_selected_expiry_never_reaches_the_horizon():
    """The measured ceiling: no listed UST option in this sample gets within 124
    days of the one-year horizon. If a future harvest changes that, this test
    fails and the module docstring's headline claim has to be rewritten."""
    panel = pd.read_parquet(PANEL)
    h = panel[panel["listed_symbol"] == f"{rc.HEADLINE_ROOT}@{rc.HEADLINE_TARGET}"]
    gap = h["listed_gap_days"].to_numpy(dtype=float)
    assert (gap < 0).all()
    assert gap.max() == pytest.approx(-124.0, abs=1.0)


@pytest.mark.slow
@pytest.mark.skipif(not PANEL.exists(), reason="real-contract artifacts not built")
def test_real_benchmark_prices_more_vol_than_thirty_day_cm():
    """The selected contract sits at a median 133 days, where the ABPV term
    structure is ABOVE the 30-day point -- so the real benchmark must be higher.

    A negative sign here would mean the ageing effect had inverted, which would
    contradict the harvest's own measured term structure, so it is worth a test
    rather than a plot.
    """
    real = pd.read_parquet(PANEL)
    cm = pd.read_parquet(CM_CONTROL)
    t = rc.cm_vs_real_table(real, cm, real_symbol=f"{rc.HEADLINE_ROOT}@{rc.HEADLINE_TARGET}",
                            cm_symbol=f"{rc.HEADLINE_ROOT}_30")
    d = float(t[t["structure"] == "POOLED"]["median_listed_diff_bp_day"].iloc[0])
    assert d > 0.0
