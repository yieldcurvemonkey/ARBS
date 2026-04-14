"""Verify TradeTape emits one enriched row per classified input row.

Pins the contract between the lifecycle fixture and ``TradeTape.compute``.
If TradeTape's behaviour ever drifts these tests should fail loud so we
can react by either adjusting the fixture or filing a follow-up — we
never silently mutate TradeTape to satisfy the fixture.
"""
from __future__ import annotations

import pytest

from SDRUtils.analytics.trade_tape import TradeTape
from tests.fixtures.tape_lifecycle_fixtures import sample_classified_df


def _compute():
    df = sample_classified_df()
    # use_cache=False to avoid picking up stale pickles during dev.
    return df, TradeTape(df=df, raw_df=None).compute(use_cache=False)


def test_compute_preserves_row_count():
    df, tape = _compute()
    assert len(tape) == len(df)


def test_compute_has_all_expected_columns():
    _, tape = _compute()
    expected = [
        "trade_id",
        "package_id",
        "execution_timestamp",
        "tape_label",
        "trade_type",
        "venue",
        "ccp",
        "rate_index_clean",
        "is_new_risk",
        "is_unwind",
        "is_compression",
        "is_reset_optimization",
        "is_ufro",
        "is_block",
        "is_off_date",
        "lifecycle_type",
        "quality_flags",
    ]
    missing = [c for c in expected if c not in tape.columns]
    assert not missing, f"missing columns: {missing}"


def test_unwind_flag_fires_for_backdated_effective():
    _, tape = _compute()
    by_id = tape.set_index("trade_id")
    assert bool(by_id.loc["T_UNW_1", "is_unwind"]) is True


def test_newt_row_is_new_risk():
    _, tape = _compute()
    by_id = tape.set_index("trade_id")
    # Baseline NEWT should always register as new-risk.
    assert bool(by_id.loc["T_NEWT_1", "is_new_risk"]) is True


def test_novation_flags_populate():
    _, tape = _compute()
    by_id = tape.set_index("trade_id")
    assert bool(by_id.loc["T_NOVA_BORN_1", "is_novation_born"]) is True
    assert bool(by_id.loc["T_NOVA_TERM_1", "is_novation_terminated"]) is True


def test_exercise_and_clearing_flags():
    _, tape = _compute()
    by_id = tape.set_index("trade_id")
    assert bool(by_id.loc["T_XERC_1", "is_exercise_born"]) is True
    assert bool(by_id.loc["T_CLR_1", "is_clearing_termination"]) is True
