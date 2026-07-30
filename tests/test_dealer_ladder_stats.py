"""Statistics tests. Several are calibration tests: they check the machinery has
the right FALSE-POSITIVE rate on synthetic nulls, not merely that it runs.
"""
import numpy as np
import pandas as pd
import pytest

from BT.dealer_ladder import stats


# ------------------------------------------------------------------- blocks
def test_day_codes_groups_by_et_calendar_date():
    ts = pd.to_datetime([
        "2026-07-10 13:00:00+00:00",   # 09:00 ET, 07/10
        "2026-07-10 20:59:00+00:00",   # 16:59 ET, 07/10
        "2026-07-11 01:00:00+00:00",   # 21:00 ET on 07/10 -- SAME ET session date
        "2026-07-13 13:00:00+00:00",
    ])
    codes = stats.day_codes(ts)
    assert codes[0] == codes[1] == codes[2]
    assert codes[3] != codes[0]


def test_day_codes_handles_naive_input():
    codes = stats.day_codes(pd.to_datetime(["2026-07-10 09:00", "2026-07-11 09:00"]))
    assert list(codes) == [0, 1]


def test_cluster_se_exceeds_iid_se_when_days_are_correlated():
    """The whole point: intraday rows inside a session are not independent."""
    rng = np.random.default_rng(0)
    day_effect = rng.normal(scale=1.0, size=40)
    vals, blocks = [], []
    for d, eff in enumerate(day_effect):
        vals.extend(eff + rng.normal(scale=0.05, size=25))   # 25 near-identical rows
        blocks.extend([d] * 25)
    res = stats.cluster_mean_t(vals, blocks)
    iid_se = np.std(vals, ddof=1) / np.sqrt(len(vals))
    assert res["se"] > 3 * iid_se, (res["se"], iid_se)
    assert res["n_blocks"] == 40 and res["n"] == 1000


def test_cluster_mean_t_needs_two_blocks():
    res = stats.cluster_mean_t([1.0, 2.0, 3.0], [0, 0, 0])
    assert res["mean"] == pytest.approx(2.0)
    assert np.isnan(res["se"]) and np.isnan(res["t"])
    assert res["n_blocks"] == 1


def test_cluster_mean_t_drops_non_finite():
    res = stats.cluster_mean_t([1.0, np.nan, 3.0, np.inf], [0, 0, 1, 1])
    assert res["n"] == 2 and res["mean"] == pytest.approx(2.0)


def test_cluster_mean_t_empty():
    res = stats.cluster_mean_t([], [])
    assert res["n"] == 0 and np.isnan(res["mean"])


def test_cluster_mean_t_rejects_length_mismatch():
    with pytest.raises(ValueError, match="differ in length"):
        stats.cluster_mean_t([1.0, 2.0], [0])


def test_resample_blocks_draws_whole_days():
    b = np.array([0, 0, 0, 1, 1, 2])
    rng = np.random.default_rng(3)
    idx = stats.resample_blocks(b, rng)
    assert len(idx) >= 3
    # every drawn day contributes ALL of its rows
    picked = pd.Series(b[idx]).value_counts()
    sizes = pd.Series(b).value_counts()
    for day, cnt in picked.items():
        assert cnt % sizes[day] == 0


def test_day_blocked_ci_brackets_a_known_mean():
    rng = np.random.default_rng(1)
    vals, blocks = [], []
    for d in range(60):
        vals.extend(rng.normal(loc=2.0, scale=1.0, size=10))
        blocks.extend([d] * 10)
    res = stats.day_blocked_ci(vals, blocks, n_boot=400, seed=5)
    assert res["lo"] < 2.0 < res["hi"]
    assert res["n_boot"] == 400


def test_day_blocked_ci_degenerate_single_block():
    res = stats.day_blocked_ci([1.0, 2.0], [0, 0], n_boot=10)
    assert np.isnan(res["lo"]) and res["n_boot"] == 0


# ------------------------------------------------------- Romano-Wolf stepdown
def _null_panel(n_days=40, n_rows=8, n_cols=12, rho=0.9, seed=0):
    """A pure-null panel of HIGHLY correlated variants -- the realistic case:
    a grid of near-identical configurations sharing most of their signal."""
    rng = np.random.default_rng(seed)
    rows, blocks = [], []
    for d in range(n_days):
        common = rng.normal(size=n_rows)
        for _ in range(1):
            block = np.column_stack([
                rho * common + np.sqrt(1 - rho ** 2) * rng.normal(size=n_rows)
                for _ in range(n_cols)
            ])
            rows.append(block)
            blocks.extend([d] * n_rows)
    return pd.DataFrame(np.vstack(rows),
                        columns=[f"v{i}" for i in range(n_cols)]), np.array(blocks)


def test_romano_wolf_controls_family_wise_error_under_the_null():
    """On a correlated null grid, the minimum ADJUSTED p should rarely be small."""
    rejections = 0
    trials = 12
    for s in range(trials):
        panel, blocks = _null_panel(seed=s)
        res = stats.romano_wolf(panel, blocks, n_boot=200, seed=100 + s)
        if res["p_fwer"].min() < 0.05:
            rejections += 1
    assert rejections <= 2, f"{rejections}/{trials} false rejections -- FWER not controlled"


def test_romano_wolf_is_less_conservative_than_bonferroni_on_correlated_grids():
    """Why the stepdown exists: Bonferroni over 12 near-duplicate variants
    throws away power that the correlation structure says is not there."""
    panel, blocks = _null_panel(seed=7)
    panel = panel + 0.55                      # a real, common effect
    res = stats.romano_wolf(panel, blocks, n_boot=300, seed=11)
    top = res.iloc[0]
    bonferroni = min(1.0, top["p_raw"] * panel.shape[1])
    assert top["p_fwer"] <= bonferroni + 1e-12
    assert top["p_fwer"] < 0.05               # the real effect is still found


def test_romano_wolf_finds_a_single_planted_winner():
    panel, blocks = _null_panel(seed=3, rho=0.2)
    panel["v0"] = panel["v0"] + 1.2
    res = stats.romano_wolf(panel, blocks, n_boot=300, seed=4)
    assert res.index[0] == "v0"
    assert res.loc["v0", "p_fwer"] < 0.05
    assert res.loc["v1", "p_fwer"] > 0.05


def test_romano_wolf_p_values_are_monotone_down_the_order():
    panel, blocks = _null_panel(seed=9)
    panel["v0"] += 0.9
    panel["v1"] += 0.5
    res = stats.romano_wolf(panel, blocks, n_boot=200, seed=2)
    p = res["p_fwer"].to_numpy()
    assert np.all(np.diff(p) >= -1e-12), p


def test_romano_wolf_empty_panel():
    res = stats.romano_wolf(pd.DataFrame(), np.array([]))
    assert res.empty and "p_fwer" in res.columns


def test_romano_wolf_rejects_block_length_mismatch():
    panel, blocks = _null_panel(n_days=3, n_rows=2, n_cols=2)
    with pytest.raises(ValueError, match="blocks length"):
        stats.romano_wolf(panel, blocks[:-1], n_boot=10)


# ---------------------------------------------------------------------- IC
def test_rank_ic_perfect_and_inverted():
    assert stats.rank_ic([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert stats.rank_ic([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_rank_ic_is_monotone_invariant():
    """Rank IC, not Pearson: a monotone but wildly nonlinear target scores 1.0."""
    s = [1, 2, 3, 4, 5]
    assert stats.rank_ic(s, [1, 10, 1e3, 1e6, 1e9]) == pytest.approx(1.0)


def test_rank_ic_degenerate_cases():
    assert np.isnan(stats.rank_ic([1, 2], [1, 2]))            # < 3 pairs
    assert np.isnan(stats.rank_ic([1, 1, 1, 1], [1, 2, 3, 4]))  # no signal variation
    assert np.isnan(stats.rank_ic([1, 2, 3, np.nan], [np.nan, np.nan, 3, 4]))


def test_ic_by_block_is_computed_within_days():
    """A pure between-day level difference must NOT register as skill."""
    sig = [1, 2, 3, 1, 2, 3]
    tgt = [0, 0, 0, 9, 9, 9]        # target constant within each day
    blocks = [0, 0, 0, 1, 1, 1]
    per = stats.ic_by_block(sig, tgt, blocks)
    assert per.isna().all(), per


def test_ic_by_block_recovers_within_day_skill():
    sig = [1, 2, 3, 1, 2, 3]
    tgt = [1, 2, 3, 2, 4, 6]
    per = stats.ic_by_block(sig, tgt, [0, 0, 0, 1, 1, 1])
    assert per.tolist() == pytest.approx([1.0, 1.0])


# --------------------------------------------------------------- reporting
@pytest.mark.parametrize("t,want", [
    (3.2, "***"), (3.0, "***"), (2.7, "**"), (2.0, "*"), (1.7, "."),
    (1.0, ""), (-3.5, "***"), (np.nan, ""), (None, ""),
])
def test_stars(t, want):
    assert stats.stars(t) == want


def test_sign_consistency_flags_a_one_day_wonder():
    """One enormous session must not read as a consistent effect."""
    vals = [0.0] * 20 + [100.0]
    blocks = list(range(20)) + [20]
    res = stats.sign_consistency(vals, blocks)
    assert res["pooled_mean"] > 0
    assert res["share_agreeing"] == pytest.approx(1.0)   # only 1 non-zero block
    assert res["n_blocks"] == 21
    assert res["p_sign"] == pytest.approx(1.0)           # n=1 -> no evidence


def test_sign_consistency_rewards_a_broad_effect():
    vals, blocks = [], []
    for d in range(30):
        vals.append(1.0 + 0.01 * d)
        blocks.append(d)
    res = stats.sign_consistency(vals, blocks)
    assert res["share_agreeing"] == pytest.approx(1.0)
    assert res["p_sign"] < 1e-6


def test_sign_consistency_on_a_coin_flip():
    rng = np.random.default_rng(4)
    vals = list(rng.normal(size=60))
    blocks = list(range(60))
    res = stats.sign_consistency(vals, blocks)
    assert 0.35 < res["share_agreeing"] < 0.65, res
    assert res["p_sign"] > 0.2, res


def test_sign_consistency_is_undefined_at_an_exactly_zero_pooled_mean():
    """No pooled sign to agree WITH -- must be NaN, not a spurious 0.0 share."""
    res = stats.sign_consistency([1.0, -1.0] * 15, list(range(30)))
    assert res["pooled_mean"] == 0.0
    assert np.isnan(res["share_agreeing"]) and np.isnan(res["p_sign"])
    assert res["n_blocks"] == 30


def test_sign_consistency_empty():
    res = stats.sign_consistency([], [])
    assert np.isnan(res["pooled_mean"]) and res["n_blocks"] == 0


@pytest.mark.parametrize("a,factor", [(0.5, 0.0), (0.6, 0.2), (0.7, 0.4), (0.8, 0.6), (1.0, 1.0)])
def test_attenuate_matches_the_2a_minus_1_rule(a, factor):
    assert stats.attenuate(10.0, a) == pytest.approx(10.0 * factor)


def test_attenuate_at_chance_accuracy_erases_the_edge():
    assert stats.attenuate(5.0, 0.5) == pytest.approx(0.0)
