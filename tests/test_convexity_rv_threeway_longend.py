"""Known-answer tests for the THREE-WAY study on the **LONG END**.

The short-end suite (``test_convexity_rv_threeway.py``) pins the shared kernel --
the ranking, the gates, the ``both == cheapest`` identity, the linearity that
licenses deriving gate books from one engine run. None of that is re-tested here.
This file pins only what the long-end mode ADDS, in three tiers so the fast gate
stays fast:

* **Hand-computed / synthetic** (no I/O). Small planted panels where the selected
  benchmark, the basis sign, the flip ratio, the saturation measure and the
  correlation haircut are all known on paper before the code runs.
* **Algebraic properties** (no I/O). The two that would silently invert a
  headline: the correlation haircut must be monotone DECREASING in ``rbar``, and
  the ``both``/``cheapest`` identity must survive the long-end config.
* **Data-backed** (``@pytest.mark.slow``, skipped when the parquet is absent).
  The tie-outs that make the study trustworthy: the recomputed
  ``gate_swaption_only`` must equal strategy 1's own stored signal row-for-row on
  the intersection, replaying each stored direction through :func:`apply_gate`
  must reproduce the stored cohort P&L, and the headline statistics must still
  read what the notebook reports.


Verifying the checker itself
----------------------------
A test that passes against mutated code is a test that does not test, so eleven
plausible wrong implementations were planted in the long-end section of
``strat1_threeway.py`` and this file re-run against each. **Measured log:**

======================================================  =======  ==========================================
mutation                                                result   first test to fail
======================================================  =======  ==========================================
selector picks ``control`` where ``primary`` was asked   CAUGHT  test_role_selects_the_mapped_root
selector ignores ``cm_days``                             CAUGHT  test_role_selects_the_mapped_root
basis computed as listed - swaption (sign flip)          CAUGHT  test_basis_sign_is_swaption_minus_listed
correlation haircut inverted (``1 - (k-1)*rbar``)        CAUGHT  test_haircut_is_monotone_decreasing_in_...
``k_eff`` ignores ``rbar`` entirely (returns ``k``)      CAUGHT  test_haircut_is_monotone_decreasing_in_...
``n_eff_pooled`` multiplies by ``k`` not ``k_eff``       CAUGHT  test_pooled_n_eff_is_below_nominal
flip percentile drops the ``+inf`` days                  CAUGHT  test_flip_threshold_includes_infinities
saturation measured as mean, not max, of the shares      CAUGHT  test_saturation_is_one_when_unanimous
binding structure picked on ``frac_curve_at_sentinel``   CAUGHT  test_binding_structure_is_the_unsaturated_one
``basis_frame`` guard removed                            CAUGHT  test_basis_frame_rejects_longend_panel
sign runs counted as ``sum`` not ``1 + sum`` of changes  CAUGHT  test_sign_runs_are_counted_on_paper
======================================================  =======  ==========================================

**Eleven of eleven were caught**, and the suite was re-run clean after restoring
the module. The runner used ``-x``, so the column is the FIRST test to fail
rather than the only one -- notably the ``cm_days`` mutation is caught by the
role test (which checks the selected level, not just the root) before the
duplicate-key test it was aimed at ever runs.

Reproduce by hand: apply one of the replacements above to
``RVUtils/ConvexityRV/strat1_threeway.py``, run
``pytest tests/test_convexity_rv_threeway_longend.py``, and revert.
"""

from __future__ import annotations

import datetime
import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import strat1_threeway as tw

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "data" / "convexity_rv"
LONGEND_PANEL = DATA / "strat1_listed_longend_panel.parquet"
S1_PANEL = DATA / "strat1_signal_panel.parquet"


def _safe(label: str) -> str:
    return label.replace("/", "-")


# --------------------------------------------------------------------- fixtures


def _synthetic_longend_panel() -> pd.DataFrame:
    """Four dates x two structures x three benchmarks, every answer planted.

    The two structures deliberately have DIFFERENT primary roots, mirroring the
    real map (UL is primary for 30Y/50Y, US for 5Y/30Y). That is the property a
    role-based selector has to get right and a root-based one cannot express, so
    it is planted rather than assumed.

    A root's vol is a property of the CONTRACT, not of the structure referencing
    it, so each root carries ONE level per date and the roles only decide which
    root each structure points at. (An earlier draft of this fixture gave US a
    different vol under each structure, which is unphysical and which
    ``longend_basis_frame``'s uniqueness guard now rejects outright.)

    ==============  ======  =========  ============================
    structure       curve   swaption   roles: primary / alt / control
    ==============  ======  =========  ============================
    30Y/50Y           2.0        5.0   UL / US / TY
    5Y/30Y            6.5        5.0   US / UL / TY
    ==============  ======  =========  ============================

    with listed levels UL 6.0, US 7.0, TY 9.0 at cm=30 (and +0.1 at cm=60, as the
    real term structure slopes up). So:

    * 30Y/50Y: curve 2.0 is cheap against everything -- unanimous and saturated,
      the case where the benchmark cannot matter;
    * 5Y/30Y: curve 6.5 is RICH against the swaption (6.5 > 5.0) and CHEAP
      against its primary listed (6.5 < 7.0) -- the disagreement case the whole
      study turns on, planted on every date.
    """
    dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])
    #: root -> listed ATM bp/day at cm=30. One level per contract per date.
    level = {"UL": 6.0, "US": 7.0, "TY": 9.0}
    spec = {
        "30Y/50Y": {"curve": 2.0, "swpn": 5.0,
                    "primary": "UL", "alt": "US", "control": "TY"},
        "5Y/30Y": {"curve": 6.5, "swpn": 5.0,
                   "primary": "US", "alt": "UL", "control": "TY"},
    }
    rows = []
    for d in dates:
        for label, s in spec.items():
            for role in ("primary", "alt", "control"):
                root = s[role]
                for cm in (30, 60):
                    rows.append({
                        "date": d, "structure": label,
                        "listed_symbol": f"{root}_{cm}", "listed_root": root,
                        "listed_cm_days": cm, "listed_role": role,
                        "breakeven_vol_bp_day": s["curve"],
                        "breakeven_status": "root",
                        "atmf_vol_bp_day": s["swpn"], "otc_atmf_bp_day": s["swpn"],
                        # the 60-day point is a touch higher, as the real term
                        # structure is, so a selector that ignores cm_days shows up
                        "listed_atm_bp_day": level[root] + (0.1 if cm == 60 else 0.0),
                        "listed_swap_point": "30Y",
                    })
    return pd.DataFrame(rows)


def _cfg(**kw):
    base = dict(structures=(("30Y/50Y", "30Y", "50Y"), ("5Y/30Y", "5Y", "30Y")),
                start=datetime.date(2019, 1, 1), end=datetime.date(2027, 1, 1))
    base.update(kw)
    return tw.Strat1ThreeWayConfig(**base)


@pytest.fixture
def panel() -> pd.DataFrame:
    return _synthetic_longend_panel()


@pytest.fixture
def three(panel) -> pd.DataFrame:
    return tw.threeway_frame(
        tw.select_longend_benchmark(panel, role="primary", cm_days=30), _cfg())


# ------------------------------------------------------------ benchmark selection


def test_role_selects_the_mapped_root(panel):
    """``role="primary"`` must give a DIFFERENT root per structure, in one call.

    This is the whole reason the selector keys on the panel's ``listed_role``
    stamp rather than on a root string: no single contract is the sector-matched
    benchmark for every long-end structure.
    """
    sel = tw.select_longend_benchmark(panel, role="primary", cm_days=30)
    got = sel.set_index("structure")["listed_root"].to_dict()
    assert got == {"30Y/50Y": "UL", "5Y/30Y": "US"}

    ctrl = tw.select_longend_benchmark(panel, role="control", cm_days=30)
    assert set(ctrl["listed_root"]) == {"TY"}
    # ... and the control must actually change the numbers, or it is not a control
    assert not np.allclose(sorted(sel["listed_atm_bp_day"]),
                           sorted(ctrl["listed_atm_bp_day"]))


def test_root_selection_pins_one_contract(panel):
    sel = tw.select_longend_benchmark(panel, role=None, root="US", cm_days=30)
    assert set(sel["listed_root"]) == {"US"}
    # US is primary for 5Y/30Y and alt for 30Y/50Y, so both structures survive
    assert set(sel["structure"]) == {"30Y/50Y", "5Y/30Y"}
    assert set(sel["listed_role"]) == {"primary", "alt"}


def test_root_alias_is_folded(panel):
    """``"ZB"`` and ``"WN"`` are the same contracts as ``"US"`` and ``"UL"``."""
    a = tw.select_longend_benchmark(panel, role=None, root="ZB", cm_days=30)
    b = tw.select_longend_benchmark(panel, role=None, root="US", cm_days=30)
    pd.testing.assert_frame_equal(a, b)


def test_cm_days_selects_the_right_tenor(panel):
    a = tw.select_longend_benchmark(panel, role="primary", cm_days=30)
    b = tw.select_longend_benchmark(panel, role="primary", cm_days=60)
    assert np.allclose(b["listed_atm_bp_day"].to_numpy(float)
                       - a["listed_atm_bp_day"].to_numpy(float), 0.1)


def test_duplicate_key_is_rejected(panel):
    """A selection that leaves two rows per (date, structure) must RAISE.

    Not defensive decoration: ``threeway_frame`` would happily rank that date
    twice and double-weight it in every pooled statistic, and nothing downstream
    checks. Simulated by stamping two constant maturities with the same role and
    asking for a selection that cannot discriminate them.
    """
    bad = panel.copy()
    bad.loc[bad["listed_cm_days"] == 60, "listed_cm_days"] = 30
    with pytest.raises(ValueError, match="unique"):
        tw.select_longend_benchmark(bad, role="primary", cm_days=30)


def test_role_and_root_are_mutually_exclusive(panel):
    with pytest.raises(ValueError, match="exactly one"):
        tw.select_longend_benchmark(panel, role="primary", root="US")
    with pytest.raises(ValueError, match="exactly one"):
        tw.select_longend_benchmark(panel, role=None, root=None)


def test_unknown_role_raises(panel):
    with pytest.raises(ValueError, match="role must be one of"):
        tw.select_longend_benchmark(panel, role="secondary")


def test_missing_column_raises():
    with pytest.raises(KeyError, match="listed_role"):
        tw.select_longend_benchmark(
            pd.DataFrame({"date": [], "structure": [], "listed_symbol": [],
                          "listed_root": [], "listed_cm_days": []}),
            role="primary")


# ------------------------------------------------------------------- the basis


def test_basis_sign_is_swaption_minus_listed(panel):
    """POSITIVE basis = OTC prices MORE vol than the exchange. Planted.

    The planted swaption is 5.0 everywhere and the planted listed levels are
    UL 6.0, US 7.0, TY 9.0, so the basis must be -1.0 / -2.0 / -4.0 and NOT
    +1.0 / +2.0 / +4.0. The sign is load-bearing for the whole verdict -- it is
    what decides whether swaptions were the expensive comparison or the cheap
    one -- so it is pinned on hand-set numbers, with three distinct magnitudes so
    a mutation cannot pass by accident of symmetry.
    """
    b = tw.longend_basis_frame(panel, _cfg())
    for sym, want in (("UL_30", -1.0), ("US_30", -2.0), ("TY_30", -4.0)):
        got = b.loc[b["listed_symbol"] == sym, "basis_bp_day"].to_numpy(float)
        assert len(got) == 4
        assert np.allclose(got, want), f"{sym}: {got[:2]} != {want}"


def test_basis_frame_keys_on_symbol_not_date(panel):
    b = tw.longend_basis_frame(panel, _cfg())
    # 4 dates x 6 symbols, one row each -- never collapsed to 4 rows
    assert len(b) == 24
    assert b.duplicated(subset=["date", "listed_symbol"]).sum() == 0


def test_basis_frame_rejects_longend_panel(panel):
    """The SFR ``basis_frame`` must REFUSE a panel whose benchmark varies by structure.

    Without the guard it silently keeps whichever structure sorted first and
    labels one root's basis "the basis" -- a wrong number that looks right.
    """
    sel = tw.select_longend_benchmark(panel, role="primary", cm_days=30)
    with pytest.raises(ValueError, match="more than one"):
        tw.basis_frame(sel, _cfg())


def test_basis_frame_still_accepts_an_sfr_shaped_panel():
    """The guard must not break the path it was added next to.

    An SFR panel has ONE listed vol per date shared by every structure, and its
    ``listed_symbol`` legitimately varies ACROSS dates as the contract rolls -- a
    guard written on symbol cardinality would reject it.
    """
    dates = pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-08"])
    rows = []
    for i, d in enumerate(dates):
        for label in ("A", "B"):
            rows.append({"date": d, "structure": label,
                         "breakeven_vol_bp_day": 4.0,
                         "otc_atmf_bp_day": 6.0,
                         "listed_atm_bp_day": 7.0 + i,          # same for A and B
                         "listed_symbol": f"SFRH2{5 + i}",      # rolls across dates
                         "breakeven_status": "root"})
    p = pd.DataFrame(rows)
    cfg = tw.Strat1ThreeWayConfig(structures=(("A", "1Y", "2Y"), ("B", "2Y", "3Y")),
                                  start=datetime.date(2024, 1, 1),
                                  end=datetime.date(2026, 1, 1))
    b = tw.basis_frame(p, cfg)
    assert len(b) == 3
    assert np.allclose(b["basis_bp_day"].to_numpy(float), [-1.0, -2.0, -3.0])


def _basis_frame_of(dates, basis) -> pd.DataFrame:
    """A one-symbol basis frame with a planted ``basis_bp_day`` series.

    Shaped exactly like :func:`longend_basis_frame`'s output -- the two vol
    columns are carried and reconciled against the basis so a helper that
    recomputed the basis from them would still see the planted values.
    """
    b = np.asarray(list(basis), dtype=float)
    return pd.DataFrame({
        "date": pd.DatetimeIndex(dates), "listed_symbol": "X",
        "listed_root": "X", "listed_cm_days": 30,
        "otc_atmf_bp_day": 10.0 + b, "listed_atm_bp_day": 10.0,
        "basis_bp_day": b,
    })


def test_sign_runs_are_counted_on_paper():
    """``mean_sign_run_days`` on a sequence whose runs are countable by eye."""
    d = pd.bdate_range("2020-01-01", periods=8)
    #                  +   +   +   -   -   +   -   -      -> 4 runs of 8 days
    v = [1.0, 2.0, 3.0, -1.0, -2.0, 4.0, -3.0, -4.0]
    b = _basis_frame_of(d, v)
    p = tw.basis_persistence(b, lags=(1,))
    assert int(p["n_sign_runs"].iloc[0]) == 4
    assert p["mean_sign_run_days"].iloc[0] == pytest.approx(8 / 4)
    assert p["frac_positive"].iloc[0] == pytest.approx(4 / 8)


def test_ar1_half_life_recovers_a_planted_decay():
    """A simulated AR(1) must report half-life ``ln(0.5) / ln(phi)``.

    Simulated rather than a deterministic geometric decay: the sample
    autocorrelation of ``phi**t`` is not ``phi`` (subtracting the series mean
    from a monotone path leaves a large slow component), so a deterministic path
    would pin the wrong number. A real AR(1) has ``rho_1 -> phi``, which is the
    property the half-life formula assumes.
    """
    phi, n = 0.9, 20_000
    rng = np.random.default_rng(4)
    v = np.empty(n)
    v[0] = 0.0
    for i in range(1, n):
        v[i] = phi * v[i - 1] + rng.standard_normal()
    p = tw.basis_persistence(_basis_frame_of(pd.bdate_range("2000-01-03", periods=n), v),
                             lags=(1,))
    assert p["rho_1"].iloc[0] == pytest.approx(phi, abs=0.02)
    assert p["ar1_half_life_days"].iloc[0] == pytest.approx(
        math.log(0.5) / math.log(phi), rel=0.10)


def test_regime_table_splits_by_year():
    d = pd.to_datetime(["2020-06-01", "2020-06-02", "2021-06-01", "2021-06-02"])
    b = _basis_frame_of(d, [1.0, 1.0, -2.0, -2.0])
    t = tw.basis_regime_table(b, by="year").set_index("period")
    assert t.loc["2020", "median_bp_day"] == pytest.approx(1.0)
    assert t.loc["2021", "median_bp_day"] == pytest.approx(-2.0)
    assert t.loc["2020", "frac_positive"] == 1.0
    assert t.loc["2021", "frac_positive"] == 0.0


# --------------------------------------------------------- the flip-ratio retest


def test_flip_threshold_ratio_is_hand_computable(three):
    """On the planted panel every input to the ratio is known.

    ``30Y/50Y``: curve 2.0, swaption 5.0, listed 6.0 on all four dates. So
    ``|basis| = 1.0`` and ``|curve - swaption| = 3.0`` on every date, hence
    ``flip_p25 = 3.0`` and ``shortfall_multiple_p25 = 3.0``.
    """
    t = tw.flip_threshold_table(three, include_reference=False).set_index("structure")
    r = t.loc["30Y/50Y"]
    assert r["median_abs_basis_bp_day"] == pytest.approx(1.0)
    assert r["flip_p25_bp_day"] == pytest.approx(3.0)
    assert r["shortfall_multiple_p25"] == pytest.approx(3.0)
    assert r["median_basis_bp_day"] == pytest.approx(-1.0)


def test_flip_threshold_includes_infinities():
    """``never_cheap`` days must be INCLUDED in the percentile.

    The short-end study's published 2.721 came from ``np.nanpercentile`` over the
    raw absolute gap, which carries ``+inf`` for ``never_cheap`` days. Dropping
    them is a different statistic, and on the real 5Y/30Y (21.8% never_cheap) it
    moves the headline ratio from 3.45 to 2.40. A retest run on a different
    formula is not a retest, so the inclusive form is pinned and the finite form
    is required to differ.

    Planted: 8 dates, 6 with gap 1.0 and 2 with the curve at ``+inf``. Including
    the infinities the p75 sits in the infinite tail; excluding them it is 1.0.
    """
    d = pd.to_datetime([f"2020-01-{i:02d}" for i in (2, 3, 6, 7, 8, 9, 10, 13)])
    curve = [4.0] * 6 + [np.inf] * 2
    p = pd.DataFrame({"date": d, "structure": ["S"] * 8,
                      "breakeven_vol_bp_day": curve,
                      "breakeven_status": ["root"] * 6 + ["never_cheap"] * 2,
                      "otc_atmf_bp_day": [5.0] * 8,
                      "listed_atm_bp_day": [5.5] * 8})
    cfg = tw.Strat1ThreeWayConfig(structures=(("S", "5Y", "30Y"),),
                                  start=datetime.date(2019, 1, 1),
                                  end=datetime.date(2021, 1, 1))
    t = tw.flip_threshold_table(tw.threeway_frame(p, cfg), quantiles=(75,),
                                include_reference=False).set_index("structure")
    assert t.loc["S", "frac_gap_infinite"] == pytest.approx(0.25)
    assert not np.isfinite(t.loc["S", "flip_p75_bp_day"])       # inclusive
    assert t.loc["S", "flip_p75_finite_bp_day"] == pytest.approx(1.0)   # exclusive


def test_saturation_is_one_when_unanimous(three):
    """``frac_verdict_saturated`` is the MAX of the verdict shares, not the mean.

    ``30Y/50Y`` is planted cheap on every date -> 1.0. ``5Y/30Y`` is planted rich
    against the swaption on every date -> also 1.0 here, because saturation is
    about unanimity of the verdict, not about which way it points. The mean of
    three shares would give 1/3 for both and rank nothing.
    """
    t = tw.flip_threshold_table(three, include_reference=False).set_index("structure")
    assert t.loc["30Y/50Y", "frac_verdict_saturated"] == pytest.approx(1.0)
    assert t.loc["5Y/30Y", "frac_verdict_saturated"] == pytest.approx(1.0)


def test_binding_structure_is_the_unsaturated_one():
    """The verdict must nominate the structure whose verdict is NOT unanimous.

    Planted so the two candidate selectors DISAGREE, which is what happens on the
    real panel: ``SAT`` is cheap on 100% of days but has no sentinel days at all,
    while ``MIX`` is cheap on half its days and has sentinels on half. Selecting
    on ``frac_curve_at_sentinel`` picks ``SAT``; the correct selector picks
    ``MIX``.
    """
    d = pd.to_datetime([f"2020-01-{i:02d}" for i in (2, 3, 6, 7)])
    rows = []
    for i, dd in enumerate(d):
        rows.append({"date": dd, "structure": "SAT", "breakeven_vol_bp_day": 1.0,
                     "breakeven_status": "root", "otc_atmf_bp_day": 5.0,
                     "listed_atm_bp_day": 5.5, "listed_symbol": "US_30"})
        rows.append({"date": dd, "structure": "MIX",
                     "breakeven_vol_bp_day": 0.0 if i < 2 else 9.0,
                     "breakeven_status": "always_cheap" if i < 2 else "root",
                     "otc_atmf_bp_day": 5.0, "listed_atm_bp_day": 5.5,
                     "listed_symbol": "US_30"})
    p = pd.DataFrame(rows)
    cfg = tw.Strat1ThreeWayConfig(
        structures=(("SAT", "30Y", "50Y"), ("MIX", "5Y", "30Y")),
        start=datetime.date(2019, 1, 1), end=datetime.date(2021, 1, 1))
    three = tw.threeway_frame(p, cfg)
    t = tw.flip_threshold_table(three, include_reference=False).set_index("structure")
    assert t.loc["SAT", "frac_verdict_saturated"] == pytest.approx(1.0)
    assert t.loc["MIX", "frac_verdict_saturated"] == pytest.approx(0.5)
    # the two selectors genuinely disagree on this panel -- that is the point
    assert t.loc["SAT", "frac_curve_at_sentinel"] < t.loc["MIX", "frac_curve_at_sentinel"]

    v = tw.longend_verdict(three, tw.longend_basis_frame(p, cfg), cfg=cfg)
    assert v["flip_retest"]["binding_structure"] == "MIX"


# ---------------------------------------------------- gates under the long-end cfg


def test_both_equals_cheapest_under_longend_config(three):
    """The identity is configuration-independent; re-measured, not inherited."""
    r = tw.assert_both_equals_cheapest(three)
    assert r["identical"] and r["n_differ"] == 0
    assert len(tw.DISTINCT_GATE_MODES) == 4


def test_gate_distinctness_classifies_identity_and_coincidence(three):
    t = tw.gate_distinctness_table(three).set_index(["mode_a", "mode_b"])
    assert t.loc[("both", "cheapest"), "n_differ_daily"] == 0
    assert t.loc[("both", "cheapest"), "relation"] == "identity"


def test_longend_config_leaves_the_sfr_defaults_alone():
    """Adding the long-end mode must not move a single SFR knob."""
    sfr = tw.Strat1ThreeWayConfig()
    assert sfr.structures == tw.SFR_STRUCTURES
    assert sfr.start == datetime.date(2024, 7, 1)
    assert sfr.end == datetime.date(2026, 7, 28)
    assert sfr.gate_mode == "both"
    le = tw.longend_config()
    assert le.structures == tw.LONGEND_STRUCTURES
    assert le.start == datetime.date(2019, 1, 1)
    assert le.end == datetime.date(2026, 8, 14)
    # the parts that MUST match, or the gate books are not comparable to
    # strategy 1's own stored cohorts
    for f in ("horizon_years", "cost_bp_one_way", "package_dv01", "signal_lag_days",
              "curve_col", "swaption_col", "listed_col", "business_days_per_year"):
        assert getattr(le, f) == getattr(sfr, f), f


def test_longend_config_column_names_match_the_panel(panel):
    cfg = tw.longend_config()
    for c in (cfg.curve_col, cfg.swaption_col, cfg.listed_col):
        assert c in panel.columns, c


# ------------------------------------------------------- the correlation haircut


def _fake_cohorts(labels, n=40, seed=0, rho=0.0):
    """Overlapping monthly cohorts whose P&L has a planted pairwise correlation."""
    rng = np.random.default_rng(seed)
    entry = pd.bdate_range("2019-02-01", periods=n, freq="MS")
    exit_ = entry + pd.DateOffset(years=1)
    common = rng.standard_normal(n)
    out = {}
    for i, lab in enumerate(labels):
        idio = rng.standard_normal(n)
        pnl = math.sqrt(rho) * common + math.sqrt(max(0.0, 1 - rho)) * idio
        out[lab] = pd.DataFrame({
            "tag": [f"{lab}_{k}" for k in range(n)], "structure": lab,
            "entry": entry, "exit": exit_, "direction": 1.0,
            "live_at_end": False, "closed": True, "n_legs_closed": 2,
            "gross_pnl_bp": pnl, "net_pnl_bp": pnl - 1.0,
        })
    return out


def test_haircut_is_monotone_decreasing_in_correlation():
    """MORE correlated structures must be worth FEWER independent observations.

    The single most dangerous way to get this wrong is a sign slip that credits
    correlated structures with more independence -- it inflates ``n_eff``, which
    LOWERS the expected-maximum-Sharpe bar, which turns a failing gate into a
    passing one. So the direction is pinned rather than the formula.
    """
    labels = ["A", "B", "C", "D"]
    prev_k = None
    for rho in (0.0, 0.3, 0.6, 0.9):
        c = _fake_cohorts(labels, rho=rho, seed=7)
        r = tw.effective_independent_n_pooled(
            c, tw.longend_config(structures=tuple((l, "5Y", "30Y") for l in labels)))
        if prev_k is not None:
            assert r["k_eff_structures"] < prev_k, f"rho={rho}"
        prev_k = r["k_eff_structures"]
    # at rho ~ 0 the four structures are worth nearly four; at 0.9 nearly one
    lo = tw.effective_independent_n_pooled(
        _fake_cohorts(labels, rho=0.0, seed=7),
        tw.longend_config(structures=tuple((l, "5Y", "30Y") for l in labels)))
    hi = tw.effective_independent_n_pooled(
        _fake_cohorts(labels, rho=0.95, seed=7),
        tw.longend_config(structures=tuple((l, "5Y", "30Y") for l in labels)))
    assert lo["k_eff_structures"] > 3.0
    assert hi["k_eff_structures"] < 1.3


def test_pooled_n_eff_is_below_nominal():
    """Both haircuts must bite: 4 structures x 40 cohorts is not 160 observations."""
    labels = ["A", "B", "C", "D"]
    c = _fake_cohorts(labels, rho=0.7, seed=3)
    r = tw.effective_independent_n_pooled(
        c, tw.longend_config(structures=tuple((l, "5Y", "30Y") for l in labels)))
    assert r["n_nominal_pooled"] == 160
    assert r["n_eff_pooled"] < r["n_nominal_pooled"] / 10
    assert r["n_eff_pooled"] == pytest.approx(
        r["n_eff_per_structure_mean"] * r["k_eff_structures"])


def test_correlation_uses_unit_pnl_not_signed_pnl():
    """Correlation must be a property of the STRUCTURES, not of the directions.

    Two structures with identical exposure but opposite stored directions are
    perfectly correlated in unit terms. Correlating the stored signed P&L would
    report -1 and credit the pair with spurious diversification.
    """
    n = 30
    entry = pd.bdate_range("2019-02-01", periods=n, freq="MS")
    rng = np.random.default_rng(11)
    unit = rng.standard_normal(n)
    frames = {}
    for lab, d in (("A", 1.0), ("B", -1.0)):
        frames[lab] = pd.DataFrame({
            "tag": [f"{lab}_{k}" for k in range(n)], "structure": lab,
            "entry": entry, "exit": entry + pd.DateOffset(years=1),
            "direction": d, "live_at_end": False, "closed": True,
            "n_legs_closed": 2,
            "gross_pnl_bp": d * unit, "net_pnl_bp": d * unit - 1.0,
        })
    corr, summ = tw.cohort_pnl_correlation(
        frames, tw.longend_config(structures=(("A", "5Y", "30Y"), ("B", "5Y", "30Y"))))
    assert summ["mean_pairwise_r"] == pytest.approx(1.0)


def test_expected_max_sharpe_rises_with_trials_and_falls_with_n():
    """Sanity on the correction itself, at the long-end sample size."""
    a = tw.expected_max_sharpe_under_null(4, 10)
    b = tw.expected_max_sharpe_under_null(12, 10)
    assert b > a > 0
    assert tw.expected_max_sharpe_under_null(4, 100) < a


# =============================================================================
#  Data-backed tie-outs -- the ones that make the study trustworthy
# =============================================================================

pytestmark_slow = pytest.mark.slow


@pytest.fixture(scope="module")
def real_panel():
    if not LONGEND_PANEL.exists():
        pytest.skip(f"missing {LONGEND_PANEL}")
    p = pd.read_parquet(LONGEND_PANEL)
    p["date"] = pd.to_datetime(p["date"])
    return p


@pytest.fixture(scope="module")
def real_three(real_panel):
    return tw.threeway_frame(
        tw.select_longend_benchmark(real_panel, role=tw.HEADLINE_ROLE,
                                    cm_days=tw.HEADLINE_CM_DAYS),
        tw.longend_config())


@pytest.fixture(scope="module")
def real_cohorts():
    cfg = tw.longend_config()
    out = {}
    for label, _f, _b in cfg.structures:
        p = DATA / f"strat1_cohorts_{_safe(label)}.parquet"
        if p.exists():
            out[label] = pd.read_parquet(p)
    if len(out) != len(cfg.structures):
        pytest.skip("missing stored strat1 long-end cohort tables")
    return out


@pytest.mark.slow
def test_gate_swaption_only_reproduces_stored_strat1_signal(real_three):
    """**The tie-out.** Recomputing strategy 1's own signal must change nothing.

    ``gate_swaption_only`` is the curve breakeven read against the 1Yx30Y ATMF --
    which is exactly what ``strat1_curve_gamma`` already stored in
    ``strat1_signal_panel.parquet``. Any difference means the long-end mode is
    measuring something other than strategy 1's signal, and every gate comparison
    built on it would be comparing the wrong baseline.

    Restricted to ``usable`` rows because ``require_all_three`` deliberately
    zeroes the gate where the listed benchmark is absent -- that is the gate
    working, not a discrepancy.
    """
    if not S1_PANEL.exists():
        pytest.skip(f"missing {S1_PANEL}")
    s1 = pd.read_parquet(S1_PANEL)
    s1["date"] = pd.to_datetime(s1["date"])
    stored = s1.set_index(["date", "structure"])["signal"]
    j = real_three.reset_index().set_index(["date", "structure"]).join(
        stored.rename("stored"), how="inner")
    u = j["usable"].to_numpy(bool)
    assert u.sum() > 6000
    n_diff = int((j.loc[u, "gate_swaption_only"].to_numpy(float)
                  != j.loc[u, "stored"].to_numpy(float)).sum())
    assert n_diff == 0, f"{n_diff} of {int(u.sum())} rows differ"


@pytest.mark.slow
def test_apply_gate_replays_the_stored_direction(real_cohorts):
    """Known answer: the stored direction back through the gate = the stored P&L.

    The single check that makes every gate-mode number trustworthy -- it pins the
    cost convention (charged twice, only when traded) and the linearity
    derivation simultaneously. ``lag_days=0`` because the direction is indexed by
    the cohort's own entry date here, not by the signal grid.
    """
    cfg = tw.longend_config()
    for label, c in real_cohorts.items():
        sig = pd.Series(c["direction"].to_numpy(float), index=pd.to_datetime(c["entry"]))
        b = tw.apply_gate(c, sig, cfg=cfg, lag_days=0)
        m = b["gate_closed"].to_numpy(bool)
        assert m.sum() >= 70, label
        err = np.abs(b.loc[m, "gate_net_bp"].to_numpy(float)
                     - c.loc[m, "net_pnl_bp"].to_numpy(float))
        assert err.max() < 1e-9, f"{label}: max err {err.max():.3e}"


@pytest.mark.slow
def test_real_intersection_is_the_full_window(real_three):
    """The headline coverage claim: ~7.5 years, not the short end's 2."""
    rep = tw.longend_intersection_report(real_three)
    assert rep["pooled"]["dates_all_three"] == 1854
    assert rep["pooled"]["intersection_window"] == ("2019-01-02", "2026-08-11")
    per = {r["structure"]: r["n_usable"] for r in rep["per_structure"]}
    # US-benchmarked structures see more days than UL-benchmarked ones
    assert per["5Y/30Y"] == 1854 and per["10Yx10Y/20Yx10Y"] == 1854
    assert per["30Y/50Y"] == 1614 and per["20Yx5Y/25Yx5Y"] == 1614
    assert rep["n_common_dates"] == 1614


@pytest.mark.slow
def test_real_both_equals_cheapest(real_three):
    r = tw.assert_both_equals_cheapest(real_three)
    assert r["identical"] and r["n_differ"] == 0 and r["n_rows"] == 7098


@pytest.mark.slow
def test_real_flip_ratio_compresses_versus_the_short_end(real_three):
    """**The headline.** The retest that motivated the study, pinned to its numbers.

    Nothing here is a range check for its own sake: each assertion is a number the
    notebook and the verdict quote, and if the pipeline changes underneath them
    they must fail rather than drift.
    """
    t = tw.flip_threshold_table(real_three, include_reference=False).set_index("structure")
    b = t.loc["5Y/30Y"]
    assert b["frac_verdict_saturated"] == pytest.approx(0.5140, abs=5e-4)
    assert b["median_abs_basis_bp_day"] == pytest.approx(0.5557, abs=5e-4)
    assert b["flip_p25_bp_day"] == pytest.approx(1.9165, abs=5e-4)
    assert b["shortfall_multiple_p25"] == pytest.approx(3.4488, abs=5e-3)
    assert b["frac_disagree"] == pytest.approx(0.0334, abs=5e-4)
    # ... and it is genuinely below the short end's 10.02
    assert b["shortfall_multiple_p25"] < tw.SHORT_END_REFERENCE["basis_shortfall_multiple"]
    # the other three are saturated, so their ratios say nothing
    for s in ("30Y/50Y", "20Yx5Y/25Yx5Y", "10Yx10Y/20Yx10Y"):
        assert t.loc[s, "frac_verdict_saturated"] == pytest.approx(1.0)
        assert t.loc[s, "frac_disagree"] == pytest.approx(0.0)


@pytest.mark.slow
def test_real_basis_is_negative_everywhere(real_panel):
    """Every one of the twelve benchmarks prices MORE vol than the 1Yx30Y swaption.

    The sign is the finding: substituting the exchange benchmark makes the curve
    look cheaper still, so swaptions were the CHEAP comparison, not the expensive
    one the hypothesis assumed.
    """
    p = tw.basis_persistence(tw.longend_basis_frame(real_panel, tw.longend_config()))
    assert len(p) == 12
    assert (p["median_bp_day"] < 0).all(), p[["listed_symbol", "median_bp_day"]]
    assert p.set_index("listed_symbol").loc["US_30", "median_bp_day"] == pytest.approx(
        -0.545, abs=5e-3)
    assert p.set_index("listed_symbol").loc["UL_30", "median_bp_day"] == pytest.approx(
        -0.195, abs=5e-3)


@pytest.mark.slow
def test_real_sample_size(real_cohorts):
    """n_eff, measured. 7.50 per structure and ~9.7 pooled -- not 352."""
    r = tw.effective_independent_n_pooled(real_cohorts, tw.longend_config())
    assert r["n_eff_per_structure_mean"] == pytest.approx(7.5017, abs=1e-3)
    assert r["mean_pairwise_r"] == pytest.approx(0.6983, abs=1e-3)
    assert r["k_eff_structures"] == pytest.approx(1.2925, abs=1e-3)
    assert r["n_eff_pooled"] == pytest.approx(9.696, abs=1e-2)
    assert r["n_nominal_pooled"] == 352
    # 3.7x the short end's per-structure count, and still ten observations
    assert r["n_eff_per_structure_mean"] / r["shortend_n_eff_per_structure"] > 3.5


@pytest.mark.slow
def test_real_best_gate_does_not_beat_the_null(real_three, real_cohorts):
    """The honest bottom line, pinned so it cannot quietly become a claim.

    The long-end books are profitable, but the best of four gates must clear the
    expected maximum of four zero-edge strategies at the EFFECTIVE sample size,
    and it does not.
    """
    cfg = tw.longend_config()
    books = tw.all_gate_books(real_three, real_cohorts, cfg)
    gs = tw.gate_summary(books, cfg).set_index("gate_mode")
    n_eff = tw.effective_independent_n_pooled(real_cohorts, cfg)["n_eff_pooled"]
    bar = tw.expected_max_sharpe_under_null(len(tw.DISTINCT_GATE_MODES),
                                            max(2, int(round(n_eff))))
    best = float(gs["sharpe_per_trade"].max())
    assert bar == pytest.approx(0.3327, abs=5e-3)
    assert best == pytest.approx(0.2423, abs=5e-3)
    assert best < bar, "best gate unexpectedly clears the multiple-testing bar"
    # the listed veto barely moves the book
    d = float(gs.loc["both", "net_bp_mean"]) - float(gs.loc["swaption_only", "net_bp_mean"])
    assert abs(d) < 0.1


@pytest.mark.slow
def test_real_gate_distinctness(real_three, real_cohorts):
    """both == cheapest is an identity; listed_only/either merely coincide here."""
    cfg = tw.longend_config()
    books = tw.all_gate_books(real_three, real_cohorts, cfg)
    t = tw.gate_distinctness_table(real_three, books).set_index(["mode_a", "mode_b"])
    assert t.loc[("both", "cheapest"), "relation"] == "identity"
    assert t.loc[("listed_only", "either"), "relation"] == "coincides_on_cohort_grid"
    assert t.loc[("listed_only", "either"), "n_differ_daily"] == 12
    assert t.loc[("listed_only", "either"), "n_differ_at_entries"] == 0
