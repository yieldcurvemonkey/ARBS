r"""The risk-adjusted-carry screen, graded on Citi's 2019-12-04 table.

``strat3_strikeless_vol.screen_frame`` was tied out to Citi's Figure 7, close
2019-05-08, **eight pairs**. The 05-Dec-2019 note *Taking profits on delta-hedged
15y5y/20y10y flatteners* prints the same eight columns for all **fifteen** pairs
on a different date. That is 120 published cells the code was never fitted to,
and it is the signal workflow 4 is built on, so it is worth a second tie-out.

What this file pins is a **split verdict**, because that is what was measured:

* **Rank reproduces.** Spearman against Citi across the fifteen pairs is 0.986
  (level), 0.944 (carry), 0.992 (daily breakeven) and **0.988 on ``be_over_rv``,
  the decision statistic**. Two of Citi's three "most attractive" pairs are ours,
  and the third is an adjacent transposition between two pairs whose ratios
  differ by 0.002 on our curve.

* **Level does not.** Every column carries an offset — level −0.807 bp, carry
  +1.101 bp, breakeven −0.752 bp, ratio −0.190. The level offset reproduces the
  one ``test_citi_figure_7_levels_and_carry`` already documents ("uniformly
  ~0.8bp more negative … on a SOFR curve this repo rebuilds from banked par
  rates while Citi quoted its own") **to two decimals, seven months later and on
  fifteen pairs instead of eight** — which is what makes it a stable curve
  difference rather than an error.

The consequence is a design constraint, not a footnote. Citi publishes
**absolute** thresholds for the ratio — exit around 0.8, steepener above 1.0 —
and on our curve exactly one of the fifteen pairs exceeds 0.75 and **none
exceeds 1.0**. Applying Citi's printed steepener threshold to our series would
fire zero times, ever: precisely the degeneracy that made strat 1 "a
permanently-on flattener, not a timing rule". So workflow 4 keys on the
cross-sectional rank, and these tests pin that the rank is what survives.

One row shows the mechanism by which the carry offset does real damage.
``20Yx5Y/25Yx10Y`` has Citi carry **+0.34 bp**, so its breakeven truncates to
zero and its ratio is 0.00. Ours is **−0.136 bp**, so it does not truncate and
the ratio is 0.20. The carry residual after removing the mean offset has a
standard deviation of **0.89 bp** — large against a decision boundary that sits
at exactly zero. A rule reading ``carry >= 0`` is therefore reading a coin flip
on the pairs nearest the boundary, which are the pairs the rule is about.
"""

from __future__ import annotations

import datetime as dt
import os

import numpy as np
import pytest

pytestmark = [pytest.mark.integration]

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

ASOF = dt.date(2019, 12, 4)
CURVE = "USD-SOFR-1D"

#: Citi Figure 1, close 12/4/2019, USD. Order matches ``S3.PAIRS_15`` exactly --
#: asserted below rather than assumed.
PUB_LEVEL = [-6.77, -7.97, -11.33, -14.90, -14.99, -18.83, -9.18, -12.54,
             -16.11, -16.20, -20.04, -11.82, -15.65, -7.02, -10.85]
PUB_CARRY = [-3.19, -4.16, -3.95, -3.95, -3.73, -3.82, -2.30, -2.09, -2.09,
             -1.87, -1.96, -0.77, -0.86, 0.43, 0.34]
PUB_BE = [4.14, 4.62, 3.93, 3.54, 3.40, 3.16, 4.23, 3.33, 2.90, 2.70, 2.49,
          1.98, 1.84, 0.00, 0.00]
PUB_RV = [4.22, 4.23, 4.16, 4.17, 4.08, 4.13, 4.23, 4.16, 4.17, 4.08, 4.13,
          4.08, 4.13, 4.08, 4.13]
PUB_RATIO = [0.98, 1.09, 0.95, 0.85, 0.83, 0.77, 1.00, 0.80, 0.70, 0.66, 0.60,
             0.49, 0.45, 0.00, 0.00]


@pytest.fixture(scope="module")
def screen():
    import RVUtils.ConvexityRV.strat3_strikeless_vol as S3
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    try:
        mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
        pricer = mdp._get_curve(curve_name=CURVE, timestamp=ASOF)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Citi curve for {ASOF} unavailable offline: {exc}")
    return S3.screen_frame(pricer, S3.PAIRS_15, asof=ASOF)


# ---------------------------------------------------------------------------
# 0. Grade the answer key before using it
# ---------------------------------------------------------------------------
def test_the_published_table_is_internally_consistent():
    """Three properties of Citi's own table, checked before it is used as truth.

    A transcription error in the answer key is indistinguishable from a defect
    in the code it is grading, and it is the cheaper of the two to rule out.
    """
    import RVUtils.ConvexityRV.strat3_strikeless_vol as S3

    assert len(S3.PAIRS_15) == 15

    # (a) realized vol is keyed on the LONG leg, so pairs sharing a long leg
    #     must show the same vol. This is how the convention was pinned.
    by_long: dict[str, set] = {}
    for (_s, l), v in zip(S3.PAIRS_15, PUB_RV):
        by_long.setdefault(l, set()).add(v)
    assert all(len(v) == 1 for v in by_long.values()), by_long
    assert len(by_long) == 6

    # (b) the ratio is BE / vol
    ratio = np.array(PUB_BE) / np.array(PUB_RV)
    assert np.max(np.abs(ratio - np.array(PUB_RATIO))) < 0.01

    # (c) the breakeven truncates to zero exactly where carry is positive
    for be, carry in zip(PUB_BE, PUB_CARRY):
        assert (be == 0.0) == (carry >= 0.0), (be, carry)


# ---------------------------------------------------------------------------
# 1. What reproduces: the rank
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "col,pub,floor",
    [("level_bp", PUB_LEVEL, 0.95),
     ("carry_1y_bp", PUB_CARRY, 0.90),
     ("be_daily_analytic", PUB_BE, 0.95)],
)
def test_rank_order_survives(screen, col, pub, floor):
    """The screen's actual output is which pair is cheapest, and that survives."""
    from scipy.stats import spearmanr

    rho = spearmanr(screen[col].to_numpy(), np.array(pub)).statistic
    assert rho > floor, f"{col}: spearman {rho:.4f} against Citi 2019-12-04"


def test_the_decision_statistic_ranks_with_citi(screen):
    """``be_over_rv`` is what the rule reads. Its ranking is what transfers."""
    from scipy.stats import spearmanr

    rv = screen["rlzd_vol_bp"].to_numpy(dtype=float)
    if not np.isfinite(rv).all():
        # screen_frame needs a rate history for the trailing vol; without one
        # use Citi's own vols, which isolates the breakeven leg.
        rv = np.array(PUB_RV)
    ratio = screen["be_daily_analytic"].to_numpy() / rv
    rho = spearmanr(ratio, np.array(PUB_RATIO)).statistic
    assert rho > 0.95, f"be_over_rv spearman {rho:.4f}"


# ---------------------------------------------------------------------------
# 2. What does NOT reproduce: the level, and why it matters
# ---------------------------------------------------------------------------
def test_the_level_offset_is_the_one_already_documented(screen):
    """~0.8bp more negative, the same figure Figure 7 records seven months earlier.

    Pinned as a RANGE, not a point: if this offset ever collapses to zero the
    curve construction changed, and if it widens materially something else did.
    Either way the absolute-threshold question below has to be revisited.
    """
    off = float(np.mean(screen["level_bp"].to_numpy() - np.array(PUB_LEVEL)))
    assert -1.3 < off < -0.4, (
        f"level offset {off:+.3f} bp; Figure 7 documents ~-0.8 and this table "
        f"measured -0.807"
    )


def test_citis_absolute_thresholds_do_not_transfer(screen):
    """The reason workflow 4 keys on rank and not on 0.8 / 1.0.

    Citi exits the flattener around a ratio of 0.8 and enters the steepener
    above 1.0. On our curve the whole cross-section sits lower. Applying the
    printed steepener threshold would fire zero times -- the same degeneracy
    that made strat 1 a permanently-on flattener rather than a timing rule.
    """
    rv = screen["rlzd_vol_bp"].to_numpy(dtype=float)
    if not np.isfinite(rv).all():
        rv = np.array(PUB_RV)
    ours = screen["be_daily_analytic"].to_numpy() / rv

    assert (np.array(PUB_RATIO) >= 1.0).sum() >= 2, "the published table has both sides"
    assert (ours >= 1.0).sum() == 0, (
        f"our ratios reach {ours.max():.3f}; if any now clears 1.0 the level "
        "offset has changed and the rank-based rule should be re-examined"
    )


def test_the_carry_sign_is_not_reliable_near_zero(screen):
    """Why ``carry >= 0`` cannot be used as a hard gate on this curve.

    The carry residual, after removing its mean offset, is large against a
    decision boundary that sits at exactly zero -- and the two pairs Citi shows
    with positive carry are precisely the ones a ``carry >= 0`` rule would act
    on.
    """
    ours = screen["carry_1y_bp"].to_numpy()
    pub = np.array(PUB_CARRY)
    resid = (ours - pub) - np.mean(ours - pub)
    assert resid.std(ddof=1) > 0.3, (
        f"carry residual sd {resid.std(ddof=1):.3f} bp -- if this has become "
        "small, the carry sign may now be trustworthy and the gate could be "
        "tightened"
    )

    pub_pos = pub >= 0.0
    our_pos = ours >= 0.0
    assert pub_pos.sum() == 2
    assert (pub_pos != our_pos).any(), (
        "the carry sign now agrees with Citi on every pair; re-examine whether "
        "the rank-only rule is still necessary"
    )
