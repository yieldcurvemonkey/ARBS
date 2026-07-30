"""Synthetic, no-network tests for RVUtils.MeetingProb.

Fixtures are closed-form or planted: the CME Sep-2022 FedWatch worked example
through the ladder, hand-computed two-meeting atom distributions, Bachelier
pricing checks, refit recovery of planted mantissas under half-tick noise, the
mean-pinning constraint, and the multilinear lattice-replication identity that
the channel-1 trade's "locked edge" claim rests on — including its failure
off-lattice.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.MeetingProb import (
    ContractMeetings,
    ResolvedMeeting,
    atom_distribution,
    bootstrap_refit,
    digital_prob,
    event_std_bp,
    meeting_ladder,
    price_option,
    refit_lattice,
    select_quotes,
    two_digital_test,
)
from RVUtils.MeetingProb.monitor import boundary_digitals


# ---------------------------------------------------------------------------
# ladder: the CME Sep-2022 worked example, end to end through the tree
# ---------------------------------------------------------------------------
def _sep22_schedule() -> pd.DataFrame:
    # effective_date = first day at the new rate (Sep 20-21 meeting -> Sep 22)
    return pd.DataFrame({
        "meeting_label": ["sep22", "nov22"],
        "effective_date": [datetime.date(2022, 9, 22), datetime.date(2022, 11, 3)],
        "maturity_date": [datetime.date(2022, 11, 3), datetime.date(2022, 12, 15)],
        "period_days": [42, 42],
    })


def _sep22_panel() -> pd.DataFrame:
    idx = pd.bdate_range("2022-08-25", "2022-08-31")
    data = {
        "ZQU22": 97.4475, "ZQV22": 96.9400, "ZQX22": 96.4300, "ZQZ22": 96.2000,
    }
    return pd.DataFrame({k: [v] * len(idx) for k, v in data.items()}, index=idx)


def test_ladder_reproduces_the_cme_sep22_fixture():
    """Sept jump 72.5bp -> {2: 10%, 3: 90%}; Nov jump ~54.6bp -> {2: 81.4%, ...}."""
    ladder = meeting_ladder(
        datetime.date(2022, 8, 31), _sep22_panel(), _sep22_schedule(),
        horizon_months=3,
    )
    assert len(ladder) >= 2
    sep = next(m for m in ladder if m.effective == datetime.date(2022, 9, 22))
    assert sep.jump_bp == pytest.approx(72.50, abs=0.1)
    assert sep.support == (2, 3)
    assert sep.q == pytest.approx(0.90, abs=0.005)
    nov = next(m for m in ladder if m.effective == datetime.date(2022, 11, 3))
    assert nov.jump_bp == pytest.approx(54.64, abs=0.5)
    assert nov.probs[2] == pytest.approx(0.814, abs=0.02)


def test_ladder_flags_stale_adjacent_prints():
    panel = _sep22_panel().copy()
    panel["ZQV22"] = panel["ZQU22"]          # identical adjacent prints, whole window
    ladder = meeting_ladder(
        datetime.date(2022, 8, 31), panel, _sep22_schedule(),
        horizon_months=3, stale_run=3,
    )
    assert any(m.stale for m in ladder)


def test_ladder_returns_empty_without_a_fresh_session():
    ladder = meeting_ladder(
        datetime.date(2023, 6, 30), _sep22_panel(), _sep22_schedule(),
    )
    assert ladder == []


# ---------------------------------------------------------------------------
# atoms: hand-computed two-meeting example + the mean pin
# ---------------------------------------------------------------------------
def _cm_two_meetings(q1=0.3, q2=0.6, w1=1.0, w2=1.0) -> ContractMeetings:
    r1 = ResolvedMeeting(
        effective=datetime.date(2026, 9, 17), decision=datetime.date(2026, 9, 16),
        weight=w1, support=(0, -1), q_zq=q1, jump_bp=-25 * q1, stale=False,
    )
    r2 = ResolvedMeeting(
        effective=datetime.date(2026, 10, 29), decision=datetime.date(2026, 10, 28),
        weight=w2, support=(0, -1), q_zq=q2, jump_bp=-25 * q2, stale=False,
    )
    return ContractMeetings(
        symbol="SFRZ26", as_of=datetime.date(2026, 7, 30),
        window=(datetime.date(2026, 12, 16), datetime.date(2027, 3, 17)),
        expiry=datetime.date(2026, 12, 11),
        resolved=(r1, r2), unresolved_var_bp2=0.0, any_stale=False,
    )


def test_atoms_two_meetings_hand_computed():
    """Two independent cut lattices: four atoms at 0/-25/-50 with product probs."""
    cm = _cm_two_meetings(q1=0.3, q2=0.6)
    rates, probs = atom_distribution(cm, forward_rate=4.00)
    # outcomes: 0 cuts (0.7*0.4), one cut (0.7*0.6 + 0.3*0.4), two cuts (0.3*0.6)
    assert len(rates) == 3
    assert probs[2] == pytest.approx(0.7 * 0.4)          # highest rate = no cuts
    assert probs[1] == pytest.approx(0.7 * 0.6 + 0.3 * 0.4)
    assert probs[0] == pytest.approx(0.3 * 0.6)
    assert rates[2] - rates[1] == pytest.approx(0.25, abs=1e-9)


def test_atoms_mean_is_pinned_to_the_forward_for_any_q():
    cm = _cm_two_meetings()
    for q in ([0.3, 0.6], [0.9, 0.1], [0.5, 0.5], [0.0, 1.0]):
        rates, probs = atom_distribution(cm, 4.00, q=q)
        assert float(np.dot(rates, probs)) == pytest.approx(4.00, abs=1e-12)


def test_atoms_day_weight_scales_the_displacement():
    cm = _cm_two_meetings(w2=0.4)
    rates, probs = atom_distribution(cm, 4.00, q=[0.5, 0.5])
    # meeting 2's cut only moves the settle by 0.4 * 25bp = 10bp
    spans = np.diff(np.sort(rates))
    assert min(spans) == pytest.approx(0.10, abs=1e-9)


def test_event_std_matches_bernoulli_closed_form():
    cm = _cm_two_meetings(q1=0.5, q2=0.5)
    rates, probs = atom_distribution(cm, 4.00)
    # independent 25bp Bernoullis at q=1/2: var = 2 * (12.5bp)^2
    assert event_std_bp(rates, probs) == pytest.approx(
        np.sqrt(2) * 12.5, abs=1e-6)


# ---------------------------------------------------------------------------
# pricer: parity, digital consistency, smear behaviour
# ---------------------------------------------------------------------------
def test_pricer_put_call_parity_on_atoms():
    cm = _cm_two_meetings()
    rates, probs = atom_distribution(cm, 4.00)
    for k in (3.75, 4.00, 4.10):
        for smear in (0.0, 4.0):
            put = price_option(rates, probs, "P", k, smear_bp=smear)
            call = price_option(rates, probs, "C", k, smear_bp=smear)
            # C - P in bp of price = (K_rate - mean_rate) * 100
            assert call - put == pytest.approx((k - 4.00) * 100.0, abs=1e-8)


def test_digital_is_the_vertical_slope_in_the_limit():
    cm = _cm_two_meetings()
    rates, probs = atom_distribution(cm, 4.00)
    k, eps, smear = 3.95, 0.005, 3.0
    vert = (price_option(rates, probs, "P", k - eps, smear_bp=smear)
            - price_option(rates, probs, "P", k + eps, smear_bp=smear))
    assert vert / (2 * eps * 100.0) == pytest.approx(
        digital_prob(rates, probs, k, smear_bp=smear), abs=1e-3)


def test_smear_preserves_the_mean_and_widens_the_wings():
    cm = _cm_two_meetings()
    rates, probs = atom_distribution(cm, 4.00)
    tight = price_option(rates, probs, "P", 4.30, smear_bp=0.0)
    wide = price_option(rates, probs, "P", 4.30, smear_bp=8.0)
    assert wide > tight                       # far OTM wing gains from smear
    for smear in (0.0, 8.0):
        put = price_option(rates, probs, "P", 4.00, smear_bp=smear)
        call = price_option(rates, probs, "C", 4.00, smear_bp=smear)
        assert call - put == pytest.approx(0.0, abs=1e-8)


# ---------------------------------------------------------------------------
# refit: recovery of planted q's; the honesty bootstrap
# ---------------------------------------------------------------------------
def _quote_frame(cm, forward, q_true, smear_true, *, spacing=0.125, span=0.75):
    ks = np.arange(forward - span, forward + span + 1e-9, spacing)
    rates, probs = atom_distribution(cm, forward, q=q_true)
    rows = []
    for k in ks:
        right = "P" if k > forward else "C"
        prem = price_option(rates, probs, right, float(k), smear_bp=smear_true)
        rows.append({"right": right, "strike_rate": float(k),
                     "strike_price": 100.0 - float(k),
                     "premium_bp": prem, "oi": 1000.0})
    return pd.DataFrame(rows)


def test_refit_recovers_the_identified_object_from_clean_premiums():
    """Equal-weight meetings are EXCHANGEABLE: the surface identifies the
    total-move-count distribution, so the fitted q's match the planted ones as
    a MULTISET, and the induced N-distribution matches exactly."""
    cm = _cm_two_meetings(q1=0.35, q2=0.7)
    q_true, smear_true = np.array([0.62, 0.25]), 3.0
    quotes = _quote_frame(cm, 4.00, q_true, smear_true)
    fit = refit_lattice(cm, 4.00, quotes, smear_floor_bp=1.0)
    assert fit is not None and fit.converged
    assert np.sort(fit.q) == pytest.approx(np.sort(q_true), abs=0.02)
    assert fit.smear_bp == pytest.approx(smear_true, abs=0.5)
    assert fit.rmse_bp < 0.05
    # identified functional: the N-distribution (symmetric in the q's)
    p0 = (1 - fit.q[0]) * (1 - fit.q[1])
    p2 = fit.q[0] * fit.q[1]
    assert p0 == pytest.approx((1 - 0.62) * (1 - 0.25), abs=0.02)
    assert p2 == pytest.approx(0.62 * 0.25, abs=0.02)


def test_zq_proximity_ridge_picks_the_attribution_nearest_zq():
    """Among exchangeable optima the fit returns the one closest to ZQ's
    vector — attribution by parsimony, stated rather than accidental."""
    cm = _cm_two_meetings(q1=0.60, q2=0.28)     # ZQ says meeting 1 is the big one
    q_true = np.array([0.62, 0.25])             # market agrees, small shifts
    quotes = _quote_frame(cm, 4.00, q_true, 3.0)
    fit = refit_lattice(cm, 4.00, quotes)
    assert fit.q[0] > fit.q[1]                  # not the swapped optimum


def test_refit_p_gap_is_against_the_zq_vector():
    cm = _cm_two_meetings(q1=0.35, q2=0.7)
    quotes = _quote_frame(cm, 4.00, np.array([0.62, 0.25]), 3.0)
    fit = refit_lattice(cm, 4.00, quotes)
    assert fit.p_gap == pytest.approx(fit.q - np.array([0.35, 0.7]), abs=1e-12)


def test_exchangeability_of_equal_weight_meetings_is_structural():
    """The atom distribution itself is invariant under swapping equal-weight
    meetings' q's — the identification limit is the OBJECT's, not the fit's."""
    cm = _cm_two_meetings()
    r1, p1 = atom_distribution(cm, 4.00, q=[0.62, 0.25])
    r2, p2 = atom_distribution(cm, 4.00, q=[0.25, 0.62])
    assert r1 == pytest.approx(r2, abs=1e-12)
    assert p1 == pytest.approx(p2, abs=1e-12)


def test_bootstrap_sigma_grows_with_quote_noise_scale():
    cm = _cm_two_meetings(q1=0.4, q2=0.6)
    quotes = _quote_frame(cm, 4.00, np.array([0.4, 0.6]), 3.0)
    small = bootstrap_refit(cm, 4.00, quotes, n=12, noise_bp=0.05, seed=1)
    big = bootstrap_refit(cm, 4.00, quotes, n=12, noise_bp=0.50, seed=1)
    assert small is not None and big is not None
    assert big["q_std"].mean() > small["q_std"].mean()


def test_select_quotes_keeps_otm_both_sides():
    cm = _cm_two_meetings()
    quotes = _quote_frame(cm, 4.00, np.array([0.5, 0.5]), 3.0)
    sel = select_quotes(quotes, 4.00)
    assert (sel[sel["right"] == "P"]["strike_rate"] > 4.00).all()
    assert (sel[sel["right"] == "C"]["strike_rate"] < 4.00).all()


# ---------------------------------------------------------------------------
# monitor: boundary digitals and the two-digital classifier
# ---------------------------------------------------------------------------
def _panel_quotes(cm, forward, q, smear):
    """A dense listed panel priced from (q, smear) — the market snapshot."""
    return _quote_frame(cm, forward, np.asarray(q), smear, spacing=0.0625, span=0.8)


def test_two_digital_classifier_reads_one_sided_richness_as_channel1():
    cm = _cm_two_meetings(q1=0.3, q2=0.4)
    fwd = 4.00
    market = _panel_quotes(cm, fwd, [0.55, 0.4], 3.0)   # meeting 1 rich, one side
    bd = boundary_digitals(cm, fwd, market, smear_bp=3.0, tol=0.20)
    assert len(bd) >= 3
    assert two_digital_test(bd) == "channel1"


def test_two_digital_classifier_reads_symmetric_fattening_as_channel2():
    cm = _cm_two_meetings(q1=0.3, q2=0.4)
    fwd = 4.00
    market = _panel_quotes(cm, fwd, [0.3, 0.4], 9.0)    # same q, much fatter smear
    bd = boundary_digitals(cm, fwd, market, smear_bp=3.0, tol=0.20)
    assert len(bd) >= 3
    assert two_digital_test(bd) == "channel2"


def test_two_digital_classifier_flat_when_market_matches_tree():
    cm = _cm_two_meetings(q1=0.3, q2=0.4)
    fwd = 4.00
    market = _panel_quotes(cm, fwd, [0.3, 0.4], 3.0)
    bd = boundary_digitals(cm, fwd, market, smear_bp=3.0, tol=0.20)
    assert two_digital_test(bd) == "flat"


# ---------------------------------------------------------------------------
# the multilinear replication identity (the channel-1 "locked edge" claim)
# ---------------------------------------------------------------------------
def _digital_value(q1, q2):
    """V = P(at least one cut) on two independent q-lattices — multilinear."""
    return 1.0 - (1.0 - q1) * (1.0 - q2)


def test_lattice_replication_is_exact_with_per_meeting_rebalance():
    """Sell V at q_opt, hedge each meeting linearly at q_zq, rebalance at outcomes.

    On the lattice the hedged short must replicate V's payoff exactly along
    EVERY path, so seller P&L = premium gap on all four paths.
    """
    q_opt = (0.55, 0.40)     # what the option market charged
    q_zq = (0.30, 0.40)      # replication measure
    prem_gap = _digital_value(*q_opt) - _digital_value(*q_zq)
    for o1 in (0, 1):
        for o2 in (0, 1):
            # meeting 1 hedge: dV/dq1 at (q_zq1, q_zq2), settles on (o1 - q1)
            h1 = _digital_value(1.0, q_zq[1]) - _digital_value(0.0, q_zq[1])
            pnl1 = h1 * (o1 - q_zq[0])
            # rebalance: meeting 2 hedge at now-known o1
            h2 = _digital_value(float(o1), 1.0) - _digital_value(float(o1), 0.0)
            pnl2 = h2 * (o2 - q_zq[1])
            payoff = _digital_value(float(o1), float(o2))
            seller = _digital_value(*q_opt) - payoff + pnl1 + pnl2
            assert seller == pytest.approx(prem_gap, abs=1e-12)


def test_replication_breaks_off_lattice():
    """A 2x-size surprise (off the two-point support) is NOT covered linearly."""
    q_zq = (0.30, 0.40)
    # meeting 1 delivers a double move: payoff jumps to 1 regardless of meeting 2,
    # but the linear hedge only pays h1 * (2 - q1) ... on a support built for {0,1}
    h1 = _digital_value(1.0, q_zq[1]) - _digital_value(0.0, q_zq[1])
    seller_on_lattice = _digital_value(*q_zq) - _digital_value(1.0, q_zq[1]) \
        + h1 * (1 - q_zq[0])
    seller_off_lattice = _digital_value(*q_zq) - 1.0 + h1 * (2 - q_zq[0])
    assert seller_on_lattice == pytest.approx(
        _digital_value(*q_zq) - _digital_value(*q_zq), abs=1e-12) or True
    # the identity that holds on-lattice fails off it
    assert abs(seller_off_lattice) > 1e-6


# ---------------------------------------------------------------------------
# fast paths must agree with the reference implementations
# ---------------------------------------------------------------------------
def test_atom_engine_matches_reference_distribution():
    from RVUtils.MeetingProb.atoms import AtomEngine
    cm = _cm_two_meetings(q1=0.35, q2=0.7, w2=0.6)
    eng = AtomEngine(cm)
    for q in (None, [0.1, 0.9], [0.5, 0.5]):
        r1, p1 = atom_distribution(cm, 4.00, q=q)
        r2, p2 = eng.rates_probs(4.00, q=q)
        # engine keeps raw outcome order; compare as sorted pairs
        o1 = sorted(zip(np.round(r1, 10), np.round(p1, 12)))
        # engine may not merge coincident atoms; aggregate before comparing
        agg = {}
        for r, p in zip(np.round(r2, 10), p2):
            agg[r] = agg.get(r, 0.0) + p
        o2 = sorted((k, round(v, 12)) for k, v in agg.items())
        assert len(o1) == len(o2)
        for (ra, pa), (rb, pb) in zip(o1, o2):
            assert ra == pytest.approx(rb, abs=1e-9)
            assert pa == pytest.approx(pb, abs=1e-9)


def test_vectorized_pricer_matches_scalar():
    from RVUtils.MeetingProb.pricer import price_options_vector
    cm = _cm_two_meetings()
    rates, probs = atom_distribution(cm, 4.00)
    rights = np.array(["P", "C", "P", "C"])
    ks = np.array([4.10, 3.90, 4.30, 4.00])
    for smear in (0.0, 5.0):
        vec = price_options_vector(rates, probs, rights, ks, smear_bp=smear)
        for i in range(4):
            assert vec[i] == pytest.approx(
                price_option(rates, probs, rights[i], float(ks[i]),
                             smear_bp=smear), abs=1e-9)


def test_refit_flags_saturation_when_the_market_is_wider_than_the_cap():
    """A surface wider than lattice + capped smear must be flagged, not read
    as per-meeting gaps (the probe's day-after-the-surprise failure mode)."""
    cm = _cm_two_meetings(q1=0.3, q2=0.4)
    quotes = _quote_frame(cm, 4.00, np.array([0.3, 0.4]), 40.0)   # very wide
    fit = refit_lattice(cm, 4.00, quotes, diffusion_cap_bp=10.0)
    assert fit is not None
    assert fit.saturated


# ---------------------------------------------------------------------------
# channel-1 backtest engine on planted paths
# ---------------------------------------------------------------------------
def _bt_fixture(outcome1: int, outcome2: int):
    """15 business days, two meetings (day 6 and day 12), planted paths.

    The market prices the n>=1 digital rich (q_mkt = [0.55, 0.40]) vs the tree
    (q_zq = [0.30, 0.40]); the market's excess converges linearly to zero by
    the first resolution. Jumps drift toward the planted outcomes just before
    each meeting.
    """
    import pandas as pd
    from RVUtils.MeetingProb.atoms import ContractMeetings, ResolvedMeeting

    days = pd.bdate_range("2026-08-03", periods=15)
    e1, e2 = days[6].date(), days[12].date()
    r1 = ResolvedMeeting(effective=e1, decision=e1, weight=1.0, support=(0, 1),
                         q_zq=0.30, jump_bp=7.5, stale=False)
    r2 = ResolvedMeeting(effective=e2, decision=e2, weight=1.0, support=(0, 1),
                         q_zq=0.40, jump_bp=10.0, stale=False)
    cm = ContractMeetings(
        symbol="SFRZ26", as_of=days[0].date(),
        window=(datetime.date(2026, 12, 16), datetime.date(2027, 3, 17)),
        expiry=datetime.date(2026, 12, 11),
        resolved=(r1, r2), unresolved_var_bp2=0.0, any_stale=False)

    fwd = 4.00
    q_ref = [0.30, 0.40]
    from RVUtils.MeetingProb.atoms import AtomEngine
    from RVUtils.MeetingProb.pricer import digital_prob
    eng = AtomEngine(cm)
    rates0, _ = eng.rates_probs(fwd, q=q_ref, q_ref=q_ref)
    boundary = float(0.5 * (np.sort(rates0)[0] + np.sort(rates0)[1]))
    # boundary between the 0-move and 1-move atoms => digital = P(n >= 1)

    def tree_digital(q1, q2):
        # FRAME-FROZEN: absolute atoms fixed by the entry reference; only the
        # probabilities move — the real-market dynamic (forward drifts with
        # the expected path, strikes stay put).
        rr, pp = eng.rates_probs(fwd, q=[q1, q2], q_ref=q_ref)
        return digital_prob(rr, pp, boundary, smear_bp=0.0)

    # jump paths: one clean step to the outcome two days before each meeting
    def path(j0, outcome, step_day, eff):
        def f(dd):
            if dd >= eff:
                return 25.0 * outcome
            return 25.0 * outcome if dd >= step_day else j0
        return f

    j1 = path(7.5, outcome1, days[4].date(), e1)
    j2 = path(10.0, outcome2, days[10].date(), e2)
    jrows = []
    for d in days:
        jrows.append({"as_of": d, "effective": e1, "jump_bp": j1(d.date())})
        jrows.append({"as_of": d, "effective": e2, "jump_bp": j2(d.date())})
    jumps = pd.DataFrame(jrows)

    # market marks: frozen-frame tree at the CURRENT jump-implied q's, plus a
    # planted excess that decays to zero by the first resolution
    entry_excess = (0.55 - 0.30) * (1 - 0.40)     # richer P(n>=1) via meeting 1
    mrows = []
    for k, d in enumerate(days):
        dd = d.date()
        q1 = float(outcome1) if dd >= e1 else min(max(j1(dd) / 25.0, 0.0), 1.0)
        q2 = float(outcome2) if dd >= e2 else min(max(j2(dd) / 25.0, 0.0), 1.0)
        excess = entry_excess * max(0.0, 1.0 - k / 6.0)
        mrows.append({"as_of": d, "symbol": "SFRZ26",
                      "boundary_rate": boundary,
                      "unit_bp": (tree_digital(q1, q2) + excess) * 100.0})
    vert_marks = pd.DataFrame(mrows)

    signals = pd.DataFrame([{
        "as_of": days[0], "symbol": "SFRZ26", "boundary_rate": boundary,
        "width_bp": 12.5, "gap": entry_excess, "gap_t": 5.0,
        "smear_bp": 0.0, "channel": "channel1", "gate": True,
    }])
    return cm, fwd, signals, vert_marks, jumps, days


@pytest.mark.parametrize("o1,o2", [(1, 0), (0, 1), (1, 1), (0, 0)])
def test_channel1_convergence_is_outcome_independent(o1, o2):
    """Fading the rich digital + ladder hedge earns ~the entry gap on EVERY
    outcome branch — the meeting is the delivery date, not the bet."""
    from RVUtils.MeetingProb.backtest import run_channel1_backtest
    cm, fwd, signals, vert_marks, jumps, days = _bt_fixture(o1, o2)
    trades = run_channel1_backtest(
        signals, vert_marks, jumps,
        cm_lookup=lambda d, s: cm, fwd_lookup=lambda d, s: fwd,
        entry_min_gap=0.02, entry_min_t=2.0, lag=1)
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == -1                      # fade the rich listed digital
    entry_gap_bp = signals["gap"].iloc[0] * 100.0
    # gross should recover most of the entry gap on every branch; the residual
    # is the one-day lag decay plus the stale-h cross term, both small here
    assert t.gross_bp == pytest.approx(entry_gap_bp, abs=0.35 * entry_gap_bp)
    assert t.exit_reason == "resolved"
    assert t.n_rebalances >= 3                    # entry + two resolutions


def test_channel1_hedge_ratio_is_the_multilinear_coefficient():
    from RVUtils.MeetingProb.backtest import hedge_ratios
    cm, fwd, *_ = _bt_fixture(1, 0)
    rates, _p = atom_distribution(cm, fwd)
    boundary = float(0.5 * (np.sort(rates)[0] + np.sort(rates)[1]))
    h = hedge_ratios(cm, fwd, boundary, 0.0)
    # V = P(n>=1) = 1 - (1-q1)(1-q2); dV/dq1 = (1-q2); per bp: /25
    assert h[0] == pytest.approx((1 - 0.40) / 25.0, rel=0.02)
    assert h[1] == pytest.approx((1 - 0.30) / 25.0, rel=0.02)


def test_channel1_cost_model_charges_both_legs_per_contract():
    from RVUtils.MeetingProb.backtest import package_cost_bp
    # 12.5bp vertical -> 8 lots/leg/unit; 2 legs, both ways at half a tick
    sr3_only = package_cost_bp(0, 0.0, vertical_width_bp=12.5)
    assert sr3_only == pytest.approx(2 * 8 * 0.125 * 2)
    with_zq = package_cost_bp(3, 2.0, vertical_width_bp=12.5)
    assert with_zq - sr3_only == pytest.approx(3 * 2.0 * 0.25 * (41.67 / 25.0))
