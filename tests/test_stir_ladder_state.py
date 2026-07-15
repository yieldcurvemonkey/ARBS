# tests/test_stir_ladder_state.py
import numpy as np
import pandas as pd
import pytest
from SDRUtils.stir_flow.ladder_state import ladder_at, ladder_grid, print_weights

TS0 = pd.Timestamp("2026-07-10 14:00:00+00:00")
HL = {"default": 90.0, "block": 240.0}


def _print(unit="T1", bucket="2026-07-29", dv=100.0, vis=TS0, p_flip=0.0,
           suspect=False, block=False, space="MEETING"):
    return dict(unit_key=unit, bucket_space=space, bucket_key=bucket, delta_dv01=dv,
                visibility_timestamp=vis, p_flip=p_flip,
                curve_suspect_trade=suspect, is_block=block)


def test_no_lookahead_print_invisible_before_visibility():
    df = pd.DataFrame([_print(vis=TS0)])
    before = ladder_at(df, TS0 - pd.Timedelta(seconds=1), half_lives=HL)
    at = ladder_at(df, TS0, half_lives=HL)
    assert before.empty or before.get("2026-07-29", 0.0) == 0.0
    assert at["2026-07-29"] == pytest.approx(100.0)


def test_ewma_halves_at_half_life_and_block_hl():
    df = pd.DataFrame([_print(), _print(unit="B1", bucket="2026-09-16", block=True)])
    at_90 = ladder_at(df, TS0 + pd.Timedelta(minutes=90), half_lives=HL)
    assert at_90["2026-07-29"] == pytest.approx(50.0, rel=1e-6)
    assert at_90["2026-09-16"] == pytest.approx(100.0 * 0.5 ** (90.0 / 240.0), rel=1e-6)


def test_expected_weighting_and_suspect_exclusion():
    df = pd.DataFrame([
        _print(unit="A", dv=100.0, p_flip=0.25),           # weight 0.5
        _print(unit="S", dv=999.0, suspect=True),           # excluded by default
    ])
    lad = ladder_at(df, TS0, half_lives=HL)
    assert lad["2026-07-29"] == pytest.approx(50.0)
    lad_inc = ladder_at(df, TS0, half_lives=HL, include_suspect=True)
    assert lad_inc["2026-07-29"] == pytest.approx(50.0 + 999.0)
    lad_unw = ladder_at(df, TS0, half_lives=HL, weighting="unweighted")
    assert lad_unw["2026-07-29"] == pytest.approx(100.0)


def test_unwind_netting_zeroes_from_unwind_visibility():
    df = pd.DataFrame([_print(unit="T1", dv=100.0)])
    unw = pd.DataFrame([dict(unit_key="T1",
                             unwind_visibility_ts=TS0 + pd.Timedelta(minutes=30))])
    before = ladder_at(df, TS0 + pd.Timedelta(minutes=29), half_lives=HL, unwinds=unw)
    after = ladder_at(df, TS0 + pd.Timedelta(minutes=31), half_lives=HL, unwinds=unw)
    assert before["2026-07-29"] > 0
    assert after.get("2026-07-29", 0.0) == 0.0


def test_space_filter_and_grid():
    df = pd.DataFrame([
        _print(),
        _print(unit="F1", bucket="SR3U26", space="FUTURES"),
    ])
    fut = ladder_at(df, TS0, space="FUTURES", half_lives=HL)
    assert list(fut.index) == ["SR3U26"]
    grid = ladder_grid(df, [TS0, TS0 + pd.Timedelta(minutes=90)], half_lives=HL)
    assert grid.loc[TS0, "2026-07-29"] == pytest.approx(100.0)
    assert grid.iloc[1]["2026-07-29"] == pytest.approx(50.0)


def test_print_weights_for_book():
    df = pd.DataFrame([_print()])
    w = print_weights(df, TS0 + pd.Timedelta(minutes=90), HL)
    assert w["T1"] == pytest.approx(0.5)
