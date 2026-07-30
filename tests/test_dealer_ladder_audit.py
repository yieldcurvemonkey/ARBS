"""G1 audit tests. Half of these prove the audits FIRE on a known-leaky builder --
an audit that cannot fail is not an audit.
"""
import numpy as np
import pandas as pd
import pytest

from BT.dealer_ladder import audit
from SDRUtils.stir_flow import ladder_state

TS0 = pd.Timestamp("2026-07-10 14:00:00+00:00")
HL = {"default": 90.0, "block": 240.0}
GRID = [TS0 + pd.Timedelta(minutes=m) for m in (0, 30, 60, 90, 120)]


def _prints():
    """Three prints becoming visible at 0, +45 and +105 minutes."""
    rows = []
    for i, (unit, vis_min, dv) in enumerate(
            [("A", 0, 100.0), ("B", 45, -60.0), ("C", 105, 250.0)]):
        rows.append(dict(
            unit_key=unit, bucket_space="FUTURES", bucket_key="SFRU26",
            delta_dv01=dv, p_flip=0.0, curve_suspect_trade=False, is_block=False,
            execution_timestamp=TS0 + pd.Timedelta(minutes=vis_min - 1),
            visibility_timestamp=TS0 + pd.Timedelta(minutes=vis_min),
        ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- honest builder
def honest(prints, ts):
    return ladder_state.ladder_at(prints, ts, space="FUTURES", half_lives=HL)


# ------------------------------------------------------------------ leaky builders
def leaky_ignores_visibility(prints, ts):
    """Sums every print regardless of visibility -- the textbook look-ahead."""
    df = prints[prints["bucket_space"] == "FUTURES"]
    return df.groupby("bucket_key")["delta_dv01"].sum()


def leaky_off_by_one(prints, ts):
    """Admits prints visible up to one minute AFTER the decision instant."""
    df = prints[(prints["bucket_space"] == "FUTURES")
                & (pd.to_datetime(prints["visibility_timestamp"])
                   <= pd.Timestamp(ts) + pd.Timedelta(minutes=1))]
    return df.groupby("bucket_key")["delta_dv01"].sum()


def test_future_poison_passes_the_honest_builder():
    res = audit.audit_future_poison(_prints(), honest, GRID)
    assert res["pass"], res
    assert res["n_timestamps"] == len(GRID)
    # the audit must not have passed vacuously: something WAS poisoned
    assert res["max_future_prints"] >= 2, res


def test_future_poison_catches_a_builder_that_ignores_visibility():
    res = audit.audit_future_poison(_prints(), leaky_ignores_visibility, GRID)
    assert not res["pass"]
    assert res["n_leaking"] >= 1
    assert res["leaks"][0]["max_abs_dev"] > 1.0


def test_future_poison_catches_an_off_by_one_minute():
    """The leak a code review misses: `<=` against a shifted timestamp."""
    grid = [TS0 + pd.Timedelta(minutes=44)]        # B becomes visible at +45
    res = audit.audit_future_poison(_prints(), leaky_off_by_one, grid)
    assert not res["pass"], res
    assert res["leaks"][0]["n_future_prints"] >= 1


def test_future_poison_reports_vacuous_coverage():
    """A grid entirely after the last print poisons nothing and proves nothing."""
    late = [TS0 + pd.Timedelta(minutes=500)]
    res = audit.audit_future_poison(_prints(), leaky_ignores_visibility, late)
    assert res["pass"]                    # nothing to poison -> no deviation
    assert res["max_future_prints"] == 0  # ...which is exactly what this flags


def test_poison_leaves_visible_rows_untouched():
    p = _prints()
    ts = TS0 + pd.Timedelta(minutes=50)
    out = audit.poison_not_yet_visible(p, ts)
    visible = pd.to_datetime(p["visibility_timestamp"]) <= ts
    pd.testing.assert_series_equal(p.loc[visible, "delta_dv01"],
                                   out.loc[visible, "delta_dv01"])
    assert (out.loc[~visible, "delta_dv01"] != p.loc[~visible, "delta_dv01"]).all()


# ------------------------------------------------------------- visibility delays
def test_visibility_delays_accepts_legal_delay_set():
    res = audit.audit_visibility_delays(_prints())
    assert res["pass"], res
    assert res["mode"] == "delay-set-only"


def test_visibility_delays_rejects_a_sub_legal_delay():
    p = _prints()
    # 30 seconds: shorter than ANY Appendix C class
    p.loc[0, "visibility_timestamp"] = p.loc[0, "execution_timestamp"] + pd.Timedelta(seconds=30)
    res = audit.audit_visibility_delays(p)
    assert not res["pass"]
    assert res["n_shorter_than_minimum"] == 1


def test_visibility_delays_rejects_an_unenumerated_delay():
    p = _prints()
    p.loc[0, "visibility_timestamp"] = p.loc[0, "execution_timestamp"] + pd.Timedelta(minutes=7)
    res = audit.audit_visibility_delays(p)
    assert not res["pass"]
    assert 7.0 in res["illegal_delays"]


def test_visibility_delays_exact_class_mode():
    p = _prints()
    p["cleared"] = False
    p["on_facility"] = False
    p["is_capped"] = False
    # off-facility + uncleared -> UNCLEARED_OFF_FACILITY -> +30min
    p["visibility_timestamp"] = (pd.to_datetime(p["execution_timestamp"])
                                 + pd.Timedelta(minutes=30))
    res = audit.audit_visibility_delays(p)
    assert res["pass"] and res["mode"] == "exact-class", res
    # now mis-stamp one row with the pre-audit two-bucket delay
    p.loc[1, "visibility_timestamp"] = p.loc[1, "execution_timestamp"] + pd.Timedelta(minutes=1)
    bad = audit.audit_visibility_delays(p)
    assert not bad["pass"] and bad["n_mismatched"] == 1


def test_visibility_delays_empty_frame():
    res = audit.audit_visibility_delays(_prints().head(0))
    assert res["pass"] and res["n"] == 0


# ------------------------------------------------------------ trailing moments
def _panel():
    idx = pd.date_range("2026-01-12", periods=40, freq="B")
    rng = np.random.default_rng(7)
    return pd.DataFrame({"SFRU26": rng.normal(size=40)}, index=idx)


def full_sample_z(panel):
    """The invisible leak: standardise against the WHOLE sample's moments."""
    return (panel - panel.mean()) / panel.std()


def trailing_z(panel, window=10):
    mu = panel.rolling(window, min_periods=window).mean().shift(1)
    sd = panel.rolling(window, min_periods=window).std().shift(1)
    return (panel - mu) / sd


def test_trailing_moments_catches_full_sample_zscore():
    res = audit.audit_trailing_moments(_panel(), full_sample_z)
    assert not res["pass"], res
    assert res["max_abs_dev_in_head"] > 1e-6


def test_trailing_moments_passes_a_trailing_zscore():
    res = audit.audit_trailing_moments(_panel(), trailing_z)
    assert res["pass"], res


def test_trailing_moments_short_panel_is_not_a_failure():
    res = audit.audit_trailing_moments(_panel().head(3), full_sample_z)
    assert res["pass"] and "too short" in res["note"]


# --------------------------------------------------------------------- battery
def test_run_g1_battery_shape():
    out = audit.run_g1_battery(_prints(), honest, GRID,
                               panel=_panel(), standardise_fn=trailing_z)
    assert [v["audit"] for v in out] == ["visibility_delays", "future_poison",
                                         "trailing_moments"]
    assert all(v["pass"] for v in out)


def test_run_g1_battery_without_panel_skips_moments():
    out = audit.run_g1_battery(_prints(), honest, GRID)
    assert [v["audit"] for v in out] == ["visibility_delays", "future_poison"]


@pytest.mark.parametrize("builder", [leaky_ignores_visibility, leaky_off_by_one])
def test_battery_fails_loudly_for_each_leak(builder):
    out = audit.run_g1_battery(_prints(), builder,
                               [TS0 + pd.Timedelta(minutes=44)])
    assert not all(v["pass"] for v in out)
