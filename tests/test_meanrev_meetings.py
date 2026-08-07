"""Synthetic, no-network tests for the FOMC-calendar machinery.

Every number here is hand-computable. The one test that reaches outside this
file reads an in-repo *constant* (``Query.IRSwaps._CENTRAL_BANK_DATES``) and is
the cross-check that the hardcoded calendar is not a typo -- it is a second,
independently-maintained copy of the same dates.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.MeanRev.meetings import (
    FOMC_DECISIONS,
    LAST_ACTUAL_YEAR,
    LAST_PUBLISHED_YEAR,
    PROJECTION_GAPS_WEEKS,
    calendar_fly_loading,
    calendar_fly_panel,
    contract_weight_table,
    effective_meeting_count,
    fomc_decisions,
    fomc_schedule,
    meeting_count_gaps,
    meeting_residual_panel,
    meeting_weight_matrix,
    project_year,
    solve_smooth_path,
)

D = datetime.date


# ---------------------------------------------------------------------------
# the calendar itself
# ---------------------------------------------------------------------------

def test_eight_scheduled_meetings_every_year():
    for year, dates in FOMC_DECISIONS.items():
        assert len(dates) == 8, f"{year} has {len(dates)} meetings"
        assert list(dates) == sorted(dates), f"{year} is not sorted"
        assert all(d.year == year for d in dates)


def test_decisions_are_midweek_and_strictly_increasing():
    ds = fomc_decisions(D(2018, 1, 1), D(2035, 12, 31))
    assert ds == sorted(set(ds))
    # Scheduled FOMC meetings end on a Wednesday, except when the November
    # meeting is shifted a day for a general election.
    assert all(d.weekday() in (2, 3) for d in ds)
    thursdays = [d for d in ds if d.weekday() == 3]
    assert thursdays == [D(2018, 11, 8), D(2020, 11, 5), D(2024, 11, 7)]


def test_gaps_between_meetings_are_five_to_nine_weeks():
    ds = fomc_decisions(D(2018, 1, 1), D(2035, 12, 31))
    gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
    assert min(gaps) >= 35 and max(gaps) <= 63, (min(gaps), max(gaps))


def test_calendar_matches_the_independent_in_repo_copy():
    """``_CENTRAL_BANK_DATES`` stores meeting windows as (decision, next).

    It is maintained separately from this module and covers 2023-02 onward,
    so agreement over that span is a genuine second source. Its 2027 entries
    are explicitly guesses in the source file and are excluded.
    """
    from Query.IRSwaps._CENTRAL_BANK_DATES import _FALLBACK_DATES

    windows = _FALLBACK_DATES["USD-SOFR-1D"]
    theirs = sorted({v[0] for v in windows.values()}
                    | {v[1] for v in windows.values()})
    theirs = [d for d in theirs if D(2023, 1, 1) <= d <= D(2026, 12, 31)]
    mine = fomc_decisions(D(2023, 1, 1), D(2026, 12, 31))
    assert theirs == mine
    assert len(mine) == 32


def test_regime_boundaries_are_the_day_after_a_decision():
    """The lab's policy regimes are cut on FOMC dates -- a third cross-check."""
    from RVUtils.MeanRev.panel import DEFAULT_REGIMES

    ds = set(fomc_decisions(D(2018, 1, 1), D(2027, 12, 31)))
    for name, lo, _hi in DEFAULT_REGIMES:
        if lo is None:
            continue
        d = pd.Timestamp(lo).date()
        # DEFAULT_REGIMES is itself inconsistent by a day -- HIKING and PLATEAU
        # start the day after their decision, CUTTING starts on it. That is a
        # pre-existing quirk of the prior lab's boundaries and is left alone
        # rather than silently shifting every published regime number; either
        # convention still has to land on a meeting.
        assert d in ds or (d - datetime.timedelta(days=1)) in ds, (
            f"{name} starts {lo}, which is not a meeting date")


def test_source_column_flags_projection():
    sch = fomc_schedule(D(2018, 1, 1), D(2032, 12, 31))
    by = sch.groupby("source")["year"]
    assert by.max()["actual"] == LAST_ACTUAL_YEAR
    assert by.min()["published"] == LAST_ACTUAL_YEAR + 1
    assert by.max()["published"] == LAST_PUBLISHED_YEAR
    assert by.min()["projected"] == LAST_PUBLISHED_YEAR + 1
    assert (sch["effective_date"] - sch["decision_date"]
            == pd.Timedelta(days=1)).all()


def test_projection_rule_reproduces_2026_exactly():
    assert project_year(2026) == list(FOMC_DECISIONS[2026])


def test_projection_shape():
    p = project_year(2030)
    assert len(p) == 8
    assert all(d.weekday() == 2 for d in p)
    gaps = [(b - a).days // 7 for a, b in zip(p, p[1:])]
    assert tuple(gaps) == PROJECTION_GAPS_WEEKS


def test_projection_shift_translates_the_whole_year_uniformly():
    """A one-week probe must move every meeting by one week, not by k weeks.

    Adding the shift to each GAP compounds it: meeting k lands k*shift weeks
    away, so a nominal one-week sensitivity check would displace the December
    meeting by seven weeks and report the projection as far more fragile than
    it is.
    """
    for w in (-2, -1, 1, 3):
        base, shifted = project_year(2030), project_year(2030, shift_weeks=w)
        assert [(b - a).days for a, b in zip(base, shifted)] == [7 * w] * 8


def test_projection_fidelity_against_every_known_year():
    """Pins the fidelity table in PROJECTION_GAPS_WEEKS's docstring.

    The rule gets the rhythm right and the phase sometimes wrong: exact in two
    of ten years, out by at most one week in the rest. Anyone who edits the gap
    pattern has to update both this and the docstring.
    """
    expected = {2018: (4, 8), 2019: (0, 0), 2020: (3, 8), 2021: (3, 7),
                2022: (4, 7), 2023: (6, 7), 2024: (3, 8), 2025: (1, 7),
                2026: (0, 0), 2027: (3, 7)}
    assert set(expected) == set(FOMC_DECISIONS)
    for year, (n_wrong, max_err) in expected.items():
        errs = [(p - a).days for a, p in
                zip(FOMC_DECISIONS[year], project_year(year))]
        assert len([e for e in errs if e]) == n_wrong, (year, errs)
        assert max(abs(e) for e in errs) == max_err, (year, errs)


def test_2020_emergency_cuts_are_not_in_the_schedule():
    from RVUtils.MeanRev.meetings import UNSCHEDULED_2020

    ds = set(fomc_decisions(D(2020, 1, 1), D(2020, 12, 31)))
    assert not (ds & set(UNSCHEDULED_2020))
    assert D(2020, 3, 18) in ds          # the scheduled meeting is kept


# ---------------------------------------------------------------------------
# day weights
# ---------------------------------------------------------------------------

def test_weight_is_the_share_of_the_window_after_the_meeting():
    window = (D(2026, 1, 1), D(2026, 4, 11))            # exactly 100 days
    # decision 2026-02-08 -> effective 2026-02-09 -> 61 of the 100 days sit at
    # the new rate, so the contract inherits 0.61 of the jump.
    W = meeting_weight_matrix([window], [D(2026, 2, 8)])
    assert W.shape == (1, 1)
    assert (window[1] - window[0]).days == 100
    assert (window[1] - D(2026, 2, 9)).days == 61
    assert W[0, 0] == pytest.approx(0.61)


def test_weight_is_one_before_and_zero_after_the_window():
    window = (D(2026, 1, 1), D(2026, 4, 11))
    W = meeting_weight_matrix([window], [D(2025, 6, 1), D(2026, 9, 1)])
    assert W[0, 0] == pytest.approx(1.0)
    assert W[0, 1] == pytest.approx(0.0)


def test_effective_meeting_count_sums_the_row():
    windows = [(D(2026, 1, 1), D(2026, 4, 11)), (D(2026, 4, 11), D(2026, 7, 20))]
    W = meeting_weight_matrix(windows, [D(2026, 2, 8), D(2026, 5, 20)])
    assert effective_meeting_count(W) == pytest.approx(W.sum(axis=1))


def test_calendar_fly_loading_is_the_second_difference_of_the_weights():
    windows = [(D(2026, 1, 1), D(2026, 4, 11)), (D(2026, 4, 11), D(2026, 7, 20)),
               (D(2026, 7, 20), D(2026, 10, 28))]
    W = meeting_weight_matrix(windows, [D(2026, 5, 20)])
    phi = calendar_fly_loading(W, (0, 1, 2))
    assert phi[0] == pytest.approx(2 * W[1, 0] - W[0, 0] - W[2, 0])


def test_a_perfectly_regular_calendar_has_zero_curvature():
    """Uniform windows with meetings at identical relative offsets -> phi = 0.

    This is the null the whole thesis is stated against: the calendar only
    creates a butterfly because it is *irregular* against the IMM grid.
    """
    start = D(2026, 1, 1)
    windows = [(start + datetime.timedelta(days=90 * i),
                start + datetime.timedelta(days=90 * (i + 1))) for i in range(3)]
    meetings = [start + datetime.timedelta(days=9 + 45 * k) for k in range(8)]
    W = meeting_weight_matrix(windows, meetings)
    phi = calendar_fly_loading(W, (0, 1, 2))
    assert float(np.sum(phi)) == pytest.approx(0.0, abs=1e-12)


def test_an_irregular_calendar_has_non_zero_curvature():
    start = D(2026, 1, 1)
    windows = [(start + datetime.timedelta(days=90 * i),
                start + datetime.timedelta(days=90 * (i + 1))) for i in range(3)]
    # one meeting in the first window, two in the third: pure asymmetry
    meetings = [start + datetime.timedelta(days=d) for d in (30, 200, 250)]
    W = meeting_weight_matrix(windows, meetings)
    assert abs(float(np.sum(calendar_fly_loading(W, (0, 1, 2))))) > 0.5


def test_meeting_count_gaps_counts_between_leg_starts():
    starts = [D(2026, 1, 1), D(2026, 4, 1), D(2026, 7, 1)]
    meetings = [D(2026, 2, 10), D(2026, 3, 10), D(2026, 5, 10)]
    near, far, asym = meeting_count_gaps(starts, meetings)
    assert (near, far, asym) == (2, 1, 1)


def test_gap_counts_and_day_weights_use_the_same_boundary():
    """A meeting effective exactly ON a leg start must land the same way in both.

    ``meeting_weight_matrix`` gives such a meeting weight 1 in that window (it
    is already in force for the whole quarter) and 0 in the preceding one, i.e.
    it belongs to the EARLIER gap under a ``(a, b]`` convention. If
    ``meeting_count_gaps`` used ``[a, b)`` it would assign it to the later gap
    and the two halves of this module would disagree on every boundary case.
    """
    starts = [D(2026, 1, 1), D(2026, 4, 1), D(2026, 7, 1)]
    windows = [(starts[0], starts[1]), (starts[1], starts[2]),
               (starts[2], D(2026, 10, 1))]
    # decision on 2026-03-31 -> effective 2026-04-01, exactly the belly's start
    boundary = D(2026, 3, 31)
    W = meeting_weight_matrix(windows, [boundary])
    assert W[0, 0] == pytest.approx(0.0)     # not inside the front leg's quarter
    assert W[1, 0] == pytest.approx(1.0)     # in force for all of the belly's
    near, far, _ = meeting_count_gaps(starts, [boundary])
    assert (near, far) == (1, 0), "the boundary meeting belongs to the NEAR gap"


def test_contract_weight_table_is_one_row_per_code():
    codes = ["A", "B", "A"]
    df = pd.DataFrame({
        "code": codes,
        "imm_start": [D(2026, 1, 1), D(2026, 4, 1), D(2026, 1, 1)],
        "imm_end": [D(2026, 4, 1), D(2026, 7, 1), D(2026, 4, 1)],
    })
    wt = contract_weight_table(df, [D(2026, 2, 1), D(2026, 5, 1)])
    assert list(wt.index) == ["A", "B"]
    assert wt.shape == (2, 2)
    assert wt.loc["A"].iloc[1] == pytest.approx(0.0)
    assert wt.loc["B"].iloc[0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# the smooth-path fit
# ---------------------------------------------------------------------------

def _toy_strip(n_contracts=8, n_meetings=12, seed=0):
    start = D(2026, 1, 1)
    windows = [(start + datetime.timedelta(days=91 * i),
                start + datetime.timedelta(days=91 * (i + 1)))
               for i in range(n_contracts)]
    meetings = [start + datetime.timedelta(days=20 + 47 * k)
                for k in range(n_meetings)]
    W = meeting_weight_matrix(windows, meetings)
    return windows, meetings, W


def test_small_lambda_fits_the_strip_almost_exactly():
    _, _, W = _toy_strip()
    rng = np.random.default_rng(3)
    y = 400.0 + W @ rng.normal(0, 12, W.shape[1])
    fit = solve_smooth_path(y, W, lam=1e-6)
    assert np.abs(fit["resid"]).max() < 1e-3


def test_large_lambda_forces_the_jump_path_onto_a_straight_line():
    _, _, W = _toy_strip()
    rng = np.random.default_rng(4)
    y = 400.0 + W @ rng.normal(0, 12, W.shape[1])
    fit = solve_smooth_path(y, W, lam=1e8)
    d = np.asarray(fit["delta"])
    second = d[:-2] - 2 * d[1:-1] + d[2:]
    assert np.abs(second).max() < 1e-6


def test_a_linear_jump_path_is_in_the_null_space_of_the_penalty():
    """A path whose per-meeting jump grows linearly is fitted for free.

    That is the whole point of penalising the *second* difference: a Fed that
    accelerates smoothly is not a dislocation, however kinked the strip it
    produces. The residual must therefore be ~zero at any penalty strength --
    up to the small conditioning ridge, which does pull the jumps toward zero
    and so leaves a residual of order 1e-3 bp, a fiftieth of a settlement tick.
    """
    _, _, W = _toy_strip()
    delta = np.linspace(-8.0, 8.0, W.shape[1])
    y = 425.0 + W @ delta
    for lam in (0.1, 10.0, 1e4, 1e8):
        fit = solve_smooth_path(y, W, lam=lam)
        assert np.abs(fit["resid"]).max() < 1e-2, lam


def test_a_lone_kinked_contract_shows_up_in_the_residual():
    _, _, W = _toy_strip()
    delta = np.linspace(-8.0, 8.0, W.shape[1])
    y = 425.0 + W @ delta
    y[3] += 5.0
    fit = solve_smooth_path(y, W, lam=1e4)
    r = np.asarray(fit["resid"])
    assert r[3] > 3.0
    assert int(np.argmax(np.abs(r))) == 3
    # the smoothing spreads some of the bump onto the neighbours; the hit
    # contract must still dominate
    assert abs(r[3]) > 2.0 * np.abs(np.delete(r, 3)).max()


def test_solve_smooth_path_survives_a_strip_with_no_meetings():
    fit = solve_smooth_path([1.0, 2.0, 3.0], np.zeros((3, 0)), lam=1.0)
    assert np.isnan(fit["resid"]).all()


def test_solve_smooth_path_survives_too_few_observations():
    _, _, W = _toy_strip(n_contracts=8)
    y = np.full(8, np.nan)
    y[0] = 400.0
    fit = solve_smooth_path(y, W, lam=10.0)
    assert np.isnan(fit["resid"]).all()


def test_solve_smooth_path_fits_around_a_partially_nan_strip():
    """A hole in the strip must be skipped, not poison the whole fit."""
    _, _, W = _toy_strip()
    delta = np.linspace(-8.0, 8.0, W.shape[1])
    y = 425.0 + W @ delta
    holed = y.copy()
    holed[2] = np.nan
    fit = solve_smooth_path(holed, W, lam=1e4)
    ok = ~np.isnan(holed)
    assert np.isfinite(fit["resid"][ok]).all()
    assert np.abs(fit["resid"][ok]).max() < 1e-2
    # the missing contract still gets a FITTED value from the path
    assert np.isfinite(fit["fitted"][2])


def test_the_base_rate_is_not_shrunk_toward_zero():
    """The ridge conditions the jumps, not the level of the policy rate.

    Penalising the intercept would drag a 4% base toward 0%, and the residual --
    which is the whole output -- would have to absorb 400bp of it. With the
    intercept excluded from the ridge, even an absurd penalty leaves the base at
    the strip's own level; it only kills the jumps.
    """
    _, _, W = _toy_strip()
    delta = np.linspace(-8.0, 8.0, W.shape[1])
    y = 425.0 + W @ delta
    loose = solve_smooth_path(y, W, lam=100.0, ridge=1e-6)
    assert abs(loose["base"] - 425.0) < 1.0

    crushed = solve_smooth_path(y, W, lam=100.0, ridge=1e10)
    assert np.abs(crushed["delta"]).max() < 1e-3        # jumps are gone
    # ...and the base is still a policy rate, not ~0, which is what a ridged
    # intercept would have produced.
    assert 300.0 < crushed["base"] < 550.0
    assert crushed["base"] == pytest.approx(float(np.mean(y)), abs=1e-6)


def test_fixed_base_branch_requires_a_base():
    _, _, W = _toy_strip()
    y = 425.0 + W @ np.linspace(-8.0, 8.0, W.shape[1])
    with pytest.raises(ValueError, match="base_bp"):
        solve_smooth_path(y, W, lam=10.0, fit_base=False)


def test_fixed_base_branch_uses_the_base_it_is_given():
    _, _, W = _toy_strip()
    delta = np.linspace(-8.0, 8.0, W.shape[1])
    y = 425.0 + W @ delta
    fit = solve_smooth_path(y, W, lam=1e4, fit_base=False, base_bp=425.0)
    assert fit["base"] == pytest.approx(425.0)
    assert np.abs(fit["resid"]).max() < 1e-2
    # a wrong base must show up in the residual, not be absorbed silently
    off = solve_smooth_path(y, W, lam=1e8, fit_base=False, base_bp=405.0)
    assert np.abs(off["resid"]).max() > 1.0


# ---------------------------------------------------------------------------
# the panels
# ---------------------------------------------------------------------------

def _toy_contracts(n_dates=6, n_contracts=6):
    """A tiny contract panel with a strictly linear-in-meetings policy path."""
    start = D(2026, 1, 1)
    meetings = fomc_decisions(D(2025, 6, 1), D(2029, 12, 31))
    rows = []
    windows = [(start + datetime.timedelta(days=91 * i),
                start + datetime.timedelta(days=91 * (i + 1)))
               for i in range(n_contracts)]
    W = meeting_weight_matrix(windows, meetings)
    delta = np.linspace(-6.0, 6.0, len(meetings))
    rates_bp = 400.0 + W @ delta
    for t in range(n_dates):
        d = D(2025, 11, 3) + datetime.timedelta(days=t)
        for i, (a, b) in enumerate(windows):
            rows.append({"as_of": pd.Timestamp(d), "code": f"C{i}",
                         "imm_start": a, "imm_end": b,
                         "rate_pct": rates_bp[i] / 100.0})
    return pd.DataFrame(rows), meetings


def test_meeting_residual_panel_is_flat_on_a_linear_path():
    c, meetings = _toy_contracts()
    resid = meeting_residual_panel(c, meetings=meetings, lam=1e4, max_slot=16)
    assert resid.shape[0] == 6
    assert np.nanmax(np.abs(resid.to_numpy())) < 1e-2


def test_meeting_residual_panel_finds_an_injected_dislocation():
    c, meetings = _toy_contracts()
    hit = (c["code"] == "C2")
    c.loc[hit, "rate_pct"] = c.loc[hit, "rate_pct"] + 0.04     # +4bp
    resid = meeting_residual_panel(c, meetings=meetings, lam=1e4, max_slot=16)
    slot_of_c2 = 3          # C0..C5 are already ordered by imm_start
    assert resid[slot_of_c2].abs().min() > 2.0
    others = resid.drop(columns=[slot_of_c2])
    assert others.abs().to_numpy().max() < 1.5


def test_meeting_residual_panel_reports_projection_share():
    """The projection guard must actually fire when projected meetings are used.

    ``between(0, 1)`` alone is unfalsifiable, and on a short-dated fixture the
    branch never runs at all -- so the share is checked to be ZERO on a strip
    ending inside the published calendar and STRICTLY POSITIVE on one reaching
    past it.
    """
    near, mt = _toy_contracts(n_contracts=4)          # ends well before 2028
    _, ex_near = meeting_residual_panel(near, meetings=mt, lam=10.0,
                                        max_slot=16, return_extras=True)
    assert set(ex_near) == {"fitted", "n_meetings", "proj_share", "path_bp"}
    assert (ex_near["proj_share"] == 0.0).all()

    far, mt2 = _toy_contracts(n_contracts=16)         # reaches into 2029/2030
    _, ex_far = meeting_residual_panel(far, meetings=mt2, lam=10.0,
                                       max_slot=16, return_extras=True)
    assert ex_far["proj_share"].max() > 0.0
    assert (ex_far["proj_share"].between(0.0, 1.0)).all()


def test_calendar_fly_panel_agrees_with_itself():
    c, meetings = _toy_contracts()
    from RVUtils.MeanRev.panel import add_strip_slots, enumerate_structures

    sl = add_strip_slots(c, order_col="imm_start", start_col="imm_start")
    st = enumerate_structures(sl, spacing=1, max_slot=16)
    cal = calendar_fly_panel(st, c, meetings=meetings)
    assert not cal.empty
    # phi_sum and mtg_fly are the same number reached two ways
    assert np.abs(cal["phi_sum"] - cal["mtg_fly"]).max() < 1e-9
    # ...and it is not trivially zero, or the agreement would prove nothing
    assert cal["phi_sum"].abs().max() > 1e-3
    assert cal["asym"].ge(0).all()


def test_calendar_fly_panel_is_constant_per_key():
    """asym / phi are functions of the leg TRIPLE, so they never vary with date.

    Anything calling itself a calendar "gate" is therefore a static partition of
    keys, and a notebook has to say so. Pinned here rather than left to be
    rediscovered.
    """
    c, meetings = _toy_contracts(n_dates=6)
    from RVUtils.MeanRev.panel import add_strip_slots, enumerate_structures

    sl = add_strip_slots(c, order_col="imm_start", start_col="imm_start")
    st = enumerate_structures(sl, spacing=1, max_slot=16)
    cal = calendar_fly_panel(st, c, meetings=meetings)
    for col in ("phi_sum", "asym", "near_gap", "far_gap", "mtg_belly"):
        assert (cal.groupby("key")[col].nunique() == 1).all(), col
    assert cal["as_of"].nunique() == 6


def test_calendar_tilted_fly_is_still_a_butterfly():
    """The tilt reweights the wings but must keep the package level-neutral."""
    from RVUtils.MeanRev.meetings import calendar_tilted_fly
    from RVUtils.MeanRev.panel import add_strip_slots, enumerate_structures

    c, meetings = _toy_contracts()
    sl = add_strip_slots(c, order_col="imm_start", start_col="imm_start")
    st = enumerate_structures(sl, spacing=1, max_slot=16)
    cal = calendar_fly_panel(st, c, meetings=meetings)
    out = calendar_tilted_fly(st, cal)
    assert set(out) == {"level", "tilt", "front_share", "phi"}

    # Reconstruct the package from the reported tilt and check it reproduces the
    # level panel. Asserting the tilt against the clip that produced it would
    # only be restating the code.
    legs = st.set_index(["as_of", "key"])[["leg0_value", "leg1_value", "leg2_value"]]
    n_checked = 0
    for (d, key), r in legs.iterrows():
        t = out["tilt"].at[pd.Timestamp(d), key]
        if not np.isfinite(t):
            continue
        w = np.array([-(1.0 - t), 2.0, -(1.0 + t)])
        assert w.sum() == pytest.approx(0.0, abs=1e-12), "not level-neutral"
        lvl = float(w @ r.to_numpy(dtype=float)) * 100.0
        assert lvl == pytest.approx(out["level"].at[pd.Timestamp(d), key], abs=1e-9)
        n_checked += 1
    assert n_checked > 20
    fs = out["front_share"].to_numpy(dtype=float)
    fs = fs[np.isfinite(fs)]
    assert np.all((fs > 0.3) & (fs < 0.7))


def test_calendar_tilted_fly_equals_the_plain_fly_when_phi_is_zero():
    from RVUtils.MeanRev.meetings import calendar_tilted_fly
    from RVUtils.MeanRev.panel import add_strip_slots, enumerate_structures, pivot_levels

    c, meetings = _toy_contracts()
    sl = add_strip_slots(c, order_col="imm_start", start_col="imm_start")
    st = enumerate_structures(sl, spacing=1, max_slot=16)
    cal = calendar_fly_panel(st, c, meetings=meetings)
    cal["phi_sum"] = 0.0
    out = calendar_tilted_fly(st, cal)
    plain = pivot_levels(st)
    a = out["level"].reindex(index=plain.index, columns=plain.columns)
    assert np.nanmax(np.abs((a - plain).to_numpy())) < 1e-9


def test_calendar_fly_panel_carries_no_market_data():
    """The calendar table must not move when the rates move."""
    c, meetings = _toy_contracts()
    from RVUtils.MeanRev.panel import add_strip_slots, enumerate_structures

    sl = add_strip_slots(c, order_col="imm_start", start_col="imm_start")
    st = enumerate_structures(sl, spacing=1, max_slot=16)
    a = calendar_fly_panel(st, c, meetings=meetings)
    c2 = c.copy()
    c2["rate_pct"] = c2["rate_pct"] * 3.0 + 1.0
    sl2 = add_strip_slots(c2, order_col="imm_start", start_col="imm_start")
    st2 = enumerate_structures(sl2, spacing=1, max_slot=16)
    b = calendar_fly_panel(st2, c2, meetings=meetings)
    pd.testing.assert_frame_equal(a, b)
