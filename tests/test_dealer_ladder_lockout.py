"""The one-shot holdout rule, enforced rather than promised.

A promise not to look at the holdout twice is the weakest form of no-lookahead
control, and the second look is exactly the one that turns a fitted result into a
reported out-of-sample one. These tests pin the enforcement, including the two cases
that would quietly hand back a second shot: an unreadable ledger, and a change to a
part of the config other than the primary block.
"""
import dataclasses
import json
import os

import pandas as pd
import pytest

from BT.dealer_ladder import config as cfg, gates, lockout
from tests.test_dealer_ladder_integration import _context, _no_write


def _conf(**over):
    base = cfg.LadderStudyConfig()
    return dataclasses.replace(base, **over) if over else base


def test_the_same_specification_may_be_re_run(tmp_path):
    """Idempotent by design: the same spec over the same data yields the same number,
    so a re-run is a re-render, not a second shot."""
    c = _conf()
    first = lockout.claim(c, str(tmp_path), timestamp="2026-07-30T09:00:00")
    second = lockout.claim(c, str(tmp_path), timestamp="2026-07-30T11:00:00")
    assert second["claimed_at"] == first["claimed_at"], "must not restamp"
    assert second["spec_fingerprint"] == first["spec_fingerprint"]


def test_a_different_specification_is_refused(tmp_path):
    lockout.claim(_conf(), str(tmp_path), timestamp="t0")
    moved = _conf(primary=dataclasses.replace(cfg.PrimarySpec(), horizon_min=240))
    with pytest.raises(lockout.LockoutAlreadyBurned) as exc:
        lockout.claim(moved, str(tmp_path), timestamp="t1")
    assert "one shot" in str(exc.value)


@pytest.mark.parametrize("field, value", [
    ("universe", cfg.UniverseConfig()),
    ("cost", cfg.CostConfig()),
    ("stats", cfg.StatsConfig()),
    ("signal", cfg.SignalConfig()),
])
def test_the_fingerprint_covers_more_than_the_primary_block(tmp_path, field, value):
    """Widening the universe or softening the cost model changes the test exactly as
    much as moving the horizon does. A fingerprint over the primary block alone would
    let either through."""
    lockout.claim(_conf(), str(tmp_path), timestamp="t0")
    changed = dataclasses.replace(value, **{
        dataclasses.fields(value)[0].name: _perturb(
            getattr(value, dataclasses.fields(value)[0].name))})
    with pytest.raises(lockout.LockoutAlreadyBurned):
        lockout.claim(_conf(**{field: changed}), str(tmp_path), timestamp="t1")


def _perturb(v):
    if isinstance(v, bool):
        return not v
    if isinstance(v, (int, float)):
        return type(v)(v + 1)
    if isinstance(v, tuple):
        return v[:-1] if len(v) > 1 else v + v
    if isinstance(v, dict):
        return {**v, "__perturbed__": 1.0}
    if isinstance(v, str):
        return v + "x"
    if hasattr(v, "toordinal"):
        return v.replace(day=1 if v.day != 1 else 2)
    raise AssertionError(f"no perturbation for {type(v)}")


def test_an_unreadable_ledger_is_not_treated_as_unused(tmp_path):
    """The one failure mode that would silently restore a second shot."""
    with open(lockout.ledger_path(str(tmp_path)), "w", encoding="utf-8") as fh:
        fh.write("{not json at all")
    assert lockout.is_claimed(str(tmp_path))
    with pytest.raises(lockout.LockoutAlreadyBurned):
        lockout.claim(_conf(), str(tmp_path), timestamp="t1")


def test_force_is_possible_but_never_invisible(tmp_path):
    lockout.claim(_conf(), str(tmp_path), timestamp="t0")
    moved = _conf(primary=dataclasses.replace(cfg.PrimarySpec(), horizon_min=240))
    rec = lockout.claim(moved, str(tmp_path), timestamp="t1", force=True,
                        note="re-registered after the 07-30 data fix")
    assert rec["overrode_prior"] is not None
    on_disk = json.load(open(lockout.ledger_path(str(tmp_path)), encoding="utf-8"))
    assert on_disk["overrode_prior"] == lockout.config_fingerprint(_conf())
    assert "re-registered" in on_disk["note"]


def test_the_fingerprint_is_stable_across_equal_configs():
    assert lockout.config_fingerprint(_conf()) == lockout.config_fingerprint(_conf())
    assert len(lockout.config_fingerprint(_conf())) == 12


def test_the_ledger_records_provenance(tmp_path):
    rec = lockout.claim(_conf(), str(tmp_path), timestamp="2026-07-30T09:00:00",
                        code_vintage="468474ca6f84", note="one shot")
    assert rec["code_vintage"] == "468474ca6f84"
    assert rec["git_sha"] and rec["git_sha"] != ""
    assert rec["config"]["primary"]["horizon_min"] == 60
    assert os.path.exists(lockout.ledger_path(str(tmp_path)))


def test_in_sample_runs_never_touch_the_ledger(monkeypatch, tmp_path):
    _no_write(monkeypatch)
    ctx = dataclasses.replace(_context(effect=0.5, seed=50),
                              results_dir=str(tmp_path))
    gates.run_primary(ctx, in_sample=True)
    assert not lockout.is_claimed(str(tmp_path)), "in-sample must not burn anything"


def test_running_the_holdout_claims_it(monkeypatch, tmp_path):
    _no_write(monkeypatch)
    ctx = dataclasses.replace(_context(effect=0.5, seed=51),
                              results_dir=str(tmp_path))
    gates.run_primary(ctx, in_sample=False)
    rec = lockout.read_ledger(str(tmp_path))
    assert rec is not None
    assert rec["spec_fingerprint"] == lockout.config_fingerprint(ctx.config)


def test_a_second_holdout_run_under_a_moved_spec_raises(monkeypatch, tmp_path):
    _no_write(monkeypatch)
    ctx = dataclasses.replace(_context(effect=0.5, seed=52),
                              results_dir=str(tmp_path))
    gates.run_primary(ctx, in_sample=False)
    moved = dataclasses.replace(
        ctx, config=dataclasses.replace(
            ctx.config, primary=dataclasses.replace(ctx.config.primary,
                                                    z_threshold=0.5)))
    with pytest.raises(lockout.LockoutAlreadyBurned):
        gates.run_primary(moved, in_sample=False)


def test_the_claim_can_be_skipped_for_a_dry_run(monkeypatch, tmp_path):
    """Needed so a smoke test of the machinery cannot burn the real holdout."""
    _no_write(monkeypatch)
    ctx = dataclasses.replace(_context(effect=0.5, seed=53),
                              results_dir=str(tmp_path))
    gates.run_primary(ctx, in_sample=False, claim_lockout=False)
    assert not lockout.is_claimed(str(tmp_path))


def test_timestamps_are_injected_not_read_from_the_clock(tmp_path):
    """So the ledger a findings doc quotes is reproducible from the repo."""
    rec = lockout.claim(_conf(), str(tmp_path), timestamp="2026-07-30T09:00:00")
    assert rec["claimed_at"] == "2026-07-30T09:00:00"


def test_dates_in_the_config_survive_the_fingerprint(tmp_path):
    """The window IS part of the specification: sliding the lockout boundary would
    otherwise be a free re-registration."""
    a = lockout.config_fingerprint(_conf())
    moved = _conf(window=dataclasses.replace(
        cfg.WindowConfig(), lockout_start=pd.Timestamp("2026-06-17").date()))
    assert lockout.config_fingerprint(moved) != a


def test_the_holdout_cannot_be_evaluated_with_nowhere_to_record_it():
    """Silently proceeding would be strictly worse than the promise this replaces:
    an unrecorded evaluation, with no way to tell later that it happened."""
    with pytest.raises(ValueError, match="claim_lockout=False"):
        lockout.claim(_conf(), "", timestamp="t0")
    with pytest.raises(ValueError):
        lockout.claim(_conf(), None, timestamp="t0")
