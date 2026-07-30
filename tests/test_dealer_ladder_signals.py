"""Signal-panel tests. The load-bearing one pins the fast panel against
``ladder_state.ladder_at``, which is the authority on the ladder's semantics.
"""
import numpy as np
import pandas as pd
import pytest

from BT.dealer_ladder import config as cfg
from BT.dealer_ladder import signals as S
from SDRUtils.stir_flow import ladder_state

NY = "America/New_York"
HL = {"default": 90.0, "block": 240.0}


def _prints(seed=0, n=60, days=("2026-07-10", "2026-07-13")):
    rng = np.random.default_rng(seed)
    rows = []
    for d in days:
        base = pd.Timestamp(f"{d} 08:00", tz=NY)
        for i in range(n):
            vis = base + pd.Timedelta(minutes=int(rng.integers(0, 470)))
            rows.append(dict(
                unit_key=f"{d}-{i}", bucket_space="FUTURES",
                bucket_key=rng.choice(["SFRU26", "SFRZ26", "SFRH27"]),
                delta_dv01=float(rng.normal(scale=20_000)),
                visibility_timestamp=vis,
                execution_timestamp=vis - pd.Timedelta(minutes=1),
                p_flip=rng.choice([0.0, 0.1, 0.25, np.nan]),
                curve_suspect_trade=bool(rng.random() < 0.15),
                is_block=bool(rng.random() < 0.2),
            ))
    return pd.DataFrame(rows)


def _grid(days=("2026-07-10", "2026-07-13"), minutes=30):
    out = []
    for d in days:
        out.append(pd.date_range(f"{d} 08:00", f"{d} 16:00", freq=f"{minutes}min",
                                 tz=NY, inclusive="left"))
    idx = out[0].append(out[1:]) if len(out) > 1 else out[0]
    return idx


# --------------------------------------------------------- the pinning test
@pytest.mark.parametrize("weighting", ["expected", "unweighted"])
@pytest.mark.parametrize("include_suspect", [False, True])
def test_panel_matches_ladder_at_exactly(weighting, include_suspect):
    """The fast per-session panel must equal the authority, timestamp by timestamp."""
    prints, grid = _prints(), _grid()
    panel = S.ladder_panel(prints, grid, space="FUTURES", half_lives=HL,
                           weighting=weighting, include_suspect=include_suspect)
    for ts in grid:
        want = ladder_state.ladder_at(prints, ts, space="FUTURES", half_lives=HL,
                                      weighting=weighting,
                                      include_suspect=include_suspect)
        got = panel.loc[ts]
        for bucket, value in want.items():
            assert got[bucket] == pytest.approx(value, rel=1e-9, abs=1e-6), (ts, bucket)
        # A bucket absent from `want` was dropped there for summing to exactly zero.
        # Here it is either NaN (no contributing print at all -- the distinction
        # ladder_at cannot express) or a value that rounds to zero.
        for bucket in got.index:
            if bucket not in want.index:
                v = got[bucket]
                assert (v != v) or abs(v) < 1e-6, (ts, bucket, v)


def test_panel_matches_ladder_at_with_unwind_netting():
    prints, grid = _prints(seed=3), _grid()
    unw = pd.DataFrame([
        dict(unit_key="2026-07-10-5",
             unwind_visibility_ts=pd.Timestamp("2026-07-10 11:00", tz=NY)),
        dict(unit_key="2026-07-13-9",
             unwind_visibility_ts=pd.Timestamp("2026-07-13 09:30", tz=NY)),
    ])
    panel = S.ladder_panel(prints, grid, space="FUTURES", half_lives=HL, unwinds=unw)
    for ts in grid:
        want = ladder_state.ladder_at(prints, ts, space="FUTURES", half_lives=HL,
                                      unwinds=unw)
        for bucket, value in want.items():
            assert panel.loc[ts, bucket] == pytest.approx(value, rel=1e-9, abs=1e-6)


# ----------------------------------------------------------- no-lookahead
def test_panel_is_nan_before_any_print_is_visible():
    """NOT zero. "No print has become public yet" is an absence of information, and
    encoding it as 0.0 would give trailing_zscore a tradable constant."""
    prints = _prints(days=("2026-07-10",))
    early = pd.DatetimeIndex([pd.Timestamp("2026-07-10 07:00", tz=NY)])
    panel = S.ladder_panel(prints, early, space="FUTURES", half_lives=HL)
    assert panel.isna().all().all()


def test_a_bucket_with_no_prints_never_becomes_a_tradable_constant():
    """The defect this NaN semantics exists to prevent.

    With a 0.0 fill, a session in which a bucket has NO visible prints gets
    z = (0 - mu)/sd, a CONSTANT above the trigger for every decision -- and because the
    ladder mean is systematically negative (most prints are PAID, PAID means negative
    delta_dv01) that constant is systematically POSITIVE. The result was a full session
    of same-signed trades on a bucket carrying no information at all.
    """
    printed = tuple(f"2026-03-{d:02d}" for d in range(2, 14))
    # The quiet session must be FURTHER than the lookback (20 half-lives = 30h at
    # hl=90), otherwise the previous session's prints legitimately still contribute a
    # small decayed amount -- which is data, not absence of it.
    days = printed + ("2026-03-27",)
    grid = _grid(days=days, minutes=60)
    prints = _prints(n=20, days=printed, seed=4)        # NOTHING on 2026-03-27
    prints = prints[prints["bucket_key"] == "SFRU26"]
    panel = S.ladder_panel(prints, grid, space="FUTURES", half_lives=HL,
                           buckets=["SFRU26"])
    z = S.trailing_zscore(panel, window_days=5, min_days=3)
    last = [i for i, tt in enumerate(grid) if tt.date() == grid[-1].date()]
    assert panel["SFRU26"].iloc[last].isna().all(), "quiet session must be NaN"
    assert z["SFRU26"].iloc[last].isna().all(), "and must not yield a tradable z"


def test_panel_passes_the_future_poison_audit():
    from BT.dealer_ladder import audit

    prints, grid = _prints(days=("2026-07-10",)), _grid(days=("2026-07-10",), minutes=60)

    def build(p, ts):
        return S.ladder_panel(p, pd.DatetimeIndex([ts]), space="FUTURES",
                              half_lives=HL).iloc[0]

    res = audit.audit_future_poison(prints, build, grid)
    assert res["pass"], res
    assert res["max_future_prints"] > 0


def test_trailing_zscore_passes_the_moments_audit():
    from BT.dealer_ladder import audit

    days = [f"2026-0{m}-{d:02d}" for m in (3,) for d in range(2, 26)]
    grid = _grid(days=tuple(days), minutes=120)
    prints = _prints(n=15, days=tuple(days), seed=11)
    panel = S.ladder_panel(prints, grid, space="FUTURES", half_lives=HL)
    res = audit.audit_trailing_moments(panel, lambda p: S.trailing_zscore(p, 5, 3))
    assert res["pass"], res


# ---------------------------------------------------------------- mechanics
def test_increments_never_cross_a_session():
    prints, grid = _prints(), _grid()
    panel = S.ladder_panel(prints, grid, space="FUTURES", half_lives=HL)
    inc = S.ladder_increments(panel)
    days = pd.Index([t.date() for t in grid])
    first_rows = [i for i, d in enumerate(days) if i == 0 or days[i - 1] != d]
    assert inc.iloc[first_rows].isna().all().all()
    # and somewhere in each session the increments are genuinely populated
    assert inc.notna().any().any()


def test_increments_equal_level_differences_within_a_session():
    prints, grid = _prints(days=("2026-07-10",)), _grid(days=("2026-07-10",))
    panel = S.ladder_panel(prints, grid, space="FUTURES", half_lives=HL)
    inc = S.ladder_increments(panel)
    manual = panel["SFRU26"].iloc[3] - panel["SFRU26"].iloc[2]
    assert inc["SFRU26"].iloc[3] == pytest.approx(manual)


def test_trailing_zscore_excludes_the_current_session():
    """Session d's own values must not enter session d's moments."""
    days = tuple(f"2026-03-{d:02d}" for d in range(2, 14))
    grid = _grid(days=days, minutes=240)
    idx = grid
    panel = pd.DataFrame({"X": np.r_[np.zeros(len(idx) - 2), [100.0, 100.0]]}, index=idx)
    z = S.trailing_zscore(panel, window_days=5, min_days=2)
    last_day = idx[-1].date()
    rows = [i for i, t in enumerate(idx) if t.date() == last_day]
    # history is all zeros -> zero std -> NaN, NOT a finite z built on itself
    assert z["X"].iloc[rows].isna().all()


def test_trailing_zscore_needs_min_days():
    days = tuple(f"2026-03-{d:02d}" for d in range(2, 8))
    grid = _grid(days=days, minutes=240)
    rng = np.random.default_rng(0)
    panel = pd.DataFrame({"X": rng.normal(size=len(grid))}, index=grid)
    z = S.trailing_zscore(panel, window_days=10, min_days=4)
    first_days = sorted({t.date() for t in grid})[:4]
    early = [i for i, t in enumerate(grid) if t.date() in first_days]
    assert z["X"].iloc[early].isna().all()
    assert z["X"].iloc[-1] == z["X"].iloc[-1]      # later days are finite


def test_trailing_zscore_standardises_to_roughly_unit_scale():
    days = tuple(f"2026-03-{d:02d}" for d in range(2, 27))
    grid = _grid(days=days, minutes=60)
    rng = np.random.default_rng(5)
    panel = pd.DataFrame({"X": rng.normal(loc=7.0, scale=3.0, size=len(grid))},
                         index=grid)
    z = S.trailing_zscore(panel, window_days=10, min_days=5).dropna()
    assert abs(float(z["X"].mean())) < 0.5
    assert 0.6 < float(z["X"].std()) < 1.6


def test_build_signal_returns_all_three_panels():
    prints, grid = _prints(), _grid()
    out = S.build_signal(prints, grid, cfg.SignalConfig(z_window_days=1))
    assert set(out) == {"level", "increment", "z"}
    for v in out.values():
        assert list(v.index) == list(grid)


def test_print_intensity_is_unsigned_and_direction_blind():
    prints, grid = _prints(days=("2026-07-10",)), _grid(days=("2026-07-10",))
    intensity = S.print_intensity_panel(prints, grid, space="FUTURES", half_lives=HL)
    vals = intensity.to_numpy()
    assert (vals[~np.isnan(vals)] >= -1e-12).all()
    flipped = prints.copy()
    flipped["delta_dv01"] = -flipped["delta_dv01"]
    other = S.print_intensity_panel(flipped, grid, space="FUTURES", half_lives=HL)
    pd.testing.assert_frame_equal(intensity, other)


def test_panel_empty_inputs():
    empty = _prints().head(0)
    grid = _grid(days=("2026-07-10",))
    out = S.ladder_panel(empty, grid, space="FUTURES", half_lives=HL)
    assert list(out.index) == list(grid) and out.shape[1] == 0
    assert S.ladder_panel(_prints(), pd.DatetimeIndex([]), half_lives=HL).empty


def test_panel_respects_an_explicit_bucket_list():
    prints, grid = _prints(), _grid()
    out = S.ladder_panel(prints, grid, space="FUTURES", half_lives=HL,
                         buckets=["SFRU26", "SFRZ99"])
    assert list(out.columns) == ["SFRU26", "SFRZ99"]
    assert out["SFRZ99"].isna().all()            # a bucket with no prints is NaN


def test_print_weights_matches_the_state_module():
    prints = _prints()
    mine = S.print_weights(prints, "expected")
    theirs = ladder_state._weight(prints, "expected").to_numpy()
    np.testing.assert_allclose(mine, theirs)
    np.testing.assert_allclose(S.print_weights(prints, "unweighted"),
                               ladder_state._weight(prints, "unweighted").to_numpy())


def test_print_weights_rejects_unknown_scheme():
    with pytest.raises(ValueError, match="unknown weighting"):
        S.print_weights(_prints(), "magic")


def test_trailing_zscore_is_time_keyed_not_arrival_keyed():
    """A concatenated or reordered panel must not let a LATER session into an
    earlier session's moments. pd.unique preserves arrival order, so this would
    otherwise pass silently -- and audit_trailing_moments cannot see it, because it
    poisons by POSITION and so assumes the very property at issue."""
    days = tuple(f"2026-03-{d:02d}" for d in range(2, 14))
    grid = _grid(days=days, minutes=240)
    rng = np.random.default_rng(3)
    panel = pd.DataFrame({"X": rng.normal(size=len(grid))}, index=grid)

    sorted_z = S.trailing_zscore(panel, window_days=5, min_days=3)

    # swap the last two sessions' ARRIVAL order, keeping the timestamps intact
    last_two = sorted(set(t.date() for t in grid))[-2:]
    a = panel[[t.date() == last_two[0] for t in panel.index]]
    b = panel[[t.date() == last_two[1] for t in panel.index]]
    rest = panel[[t.date() not in last_two for t in panel.index]]
    shuffled = pd.concat([rest, b, a])
    shuffled_z = S.trailing_zscore(shuffled, window_days=5, min_days=3)

    for ts in a.index:
        want, got = sorted_z.loc[ts, "X"], shuffled_z.loc[ts, "X"]
        assert (want != want and got != got) or want == pytest.approx(got), ts
