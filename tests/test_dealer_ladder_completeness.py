"""The completeness pass must find gaps nobody thought of.

Its whole value is that the inventory comes from the DECLARATIONS in code rather than
from recollection, and that an absence WITHOUT a machine-recorded reason is flagged
separately from one with. These tests pin both, plus the property that makes the
"reason" column trustworthy: it is only accepted from the file the runner wrote at the
moment it skipped something, never supplied afterwards.
"""
import importlib.util
import itertools
import os

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "dealer_ladder_completeness",
    os.path.join(REPO, "scripts", "dealer_ladder_completeness.py"))
C = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(C)

from BT.dealer_ladder import config as cfg, controls  # noqa: E402


def _write(d, name, frame):
    frame.to_csv(os.path.join(str(d), f"{name}.csv"), index=False)


def _conf():
    return cfg.LadderStudyConfig()


def test_the_declared_grid_is_the_full_cross_product():
    g = _conf().grid
    want = (len(g.target_spaces) * len(g.spaces) * len(g.half_lives_min)
            * len(g.weightings) * len(g.horizons_min))
    got = C.declared_grid(_conf())
    assert len(got) == want == 288
    assert len(set(got)) == len(got), "variant labels must be unique"


def test_an_empty_results_dir_reports_everything_as_missing(tmp_path):
    inv = C.audit(str(tmp_path), _conf())["inventory"]
    assert not inv["ran"].any()
    assert inv["unexplained"].all()
    n_stages = len(C.STAGES)
    assert (inv["kind"] == "stage").sum() == n_stages
    assert (inv["kind"] == "grid variant").sum() == 288


def test_a_recorded_reason_moves_an_item_out_of_unexplained(tmp_path):
    """The distinction the pass exists to draw: skipped-and-accounted-for versus
    silently absent."""
    variants = C.declared_grid(_conf())
    _write(tmp_path, "g4_skipped_variants", pd.DataFrame(
        [{"variant": variants[0], "reason": "MEETING not built for this window"}]))
    inv = C.audit(str(tmp_path), _conf())["inventory"]
    row = inv[(inv["kind"] == "grid variant") & (inv["item"] == variants[0])].iloc[0]
    assert row["reason"] == "MEETING not built for this window"
    assert not row["unexplained"]
    others = inv[(inv["kind"] == "grid variant") & (inv["item"] != variants[0])]
    assert others["unexplained"].all()


def test_a_variant_that_ran_is_not_listed_at_all(tmp_path):
    variants = C.declared_grid(_conf())
    _write(tmp_path, "g4_league", pd.DataFrame(
        {"variant": variants[:5], "t": range(5)}))
    inv = C.audit(str(tmp_path), _conf())["inventory"]
    listed = set(inv[inv["kind"] == "grid variant"]["item"])
    assert not set(variants[:5]) & listed
    assert len(listed) == 283


def test_controls_absent_from_the_fitted_race_are_reported(tmp_path):
    kept = list(controls.DEFAULT_CONTROLS)[:3]
    _write(tmp_path, "g3_horse_race_FUTURES", pd.DataFrame(
        {"spec": "signal + controls", "term": ["signal"] + kept,
         "coef": 0.0, "t": 0.0}))
    inv = C.audit(str(tmp_path), _conf())["inventory"]
    reported = set(inv[inv["kind"] == "control"]["item"])
    assert not set(kept) & reported
    assert reported == set(controls.DEFAULT_CONTROLS) - set(kept)


def test_a_pre_specified_placebo_that_vanished_is_reported(tmp_path):
    _write(tmp_path, "g4_placebos", pd.DataFrame(
        {"placebo": list(C.DECLARED_PLACEBOS)[:2], "mean": 0.0}))
    inv = C.audit(str(tmp_path), _conf())["inventory"]
    missing = set(inv[inv["kind"] == "placebo"]["item"])
    assert "pre-arrival window" in missing
    assert "none (reference)" not in missing


def test_the_audit_battery_is_checked_by_name(tmp_path):
    _write(tmp_path, "g1_audits", pd.DataFrame(
        {"audit": ["future_poison"], "pass": [True]}))
    inv = C.audit(str(tmp_path), _conf())["inventory"]
    missing = set(inv[inv["kind"] == "audit"]["item"])
    assert "trailing_moments" in missing and "future_poison" not in missing


def test_conditioning_splits_are_matched_loosely(tmp_path):
    """The runner labels strata like "amihud tercile 2", so an exact match would
    report every split as missing."""
    _write(tmp_path, "g4_conditioning", pd.DataFrame(
        {"split": ["amihud tercile 1", "amihud tercile 2", "block_share tercile 1"],
         "mean": 0.0}))
    inv = C.audit(str(tmp_path), _conf())["inventory"]
    missing = set(inv[inv["kind"] == "conditioning split"]["item"])
    assert "amihud" not in missing and "block_share" not in missing
    assert "level_prox_bp" in missing


def test_the_lockout_ledger_counts_as_an_artifact(tmp_path):
    """It is JSON, not CSV, so _exists has to look for the bare filename too."""
    inv = C.audit(str(tmp_path), _conf())["inventory"]
    assert not inv[(inv["kind"] == "stage")
                   & (inv["item"] == "One-shot lockout")].iloc[0]["ran"]
    with open(os.path.join(str(tmp_path), "LOCKOUT_USED.json"), "w",
              encoding="utf-8") as fh:
        fh.write("{}")
    inv = C.audit(str(tmp_path), _conf())["inventory"]
    assert inv[(inv["kind"] == "stage")
               & (inv["item"] == "One-shot lockout")].iloc[0]["ran"]


def test_strict_fails_while_any_gap_is_unexplained(tmp_path):
    assert C.main(["--results", str(tmp_path), "--strict"]) == 1
    assert C.main(["--results", str(tmp_path)]) == 0


def test_missing_results_dir_is_an_error(tmp_path):
    assert C.main(["--results", str(tmp_path / "nope")]) == 2


def test_the_report_separates_explained_from_unexplained(tmp_path):
    variants = C.declared_grid(_conf())
    _write(tmp_path, "g4_skipped_variants", pd.DataFrame(
        [{"variant": v, "reason": "MEETING not built"} for v in variants]))
    res = C.audit(str(tmp_path), _conf())
    md = C.render(res, str(tmp_path))
    assert "### Not run, with a recorded reason" in md
    assert "MEETING not built" in md
    inv = res["inventory"]
    grid = inv[inv["kind"] == "grid variant"]
    assert not grid["unexplained"].any()
    # the stages are still unexplained, so the section must remain
    assert "Not run, and NOT explained" in md


def test_every_declared_stage_names_at_least_one_artifact():
    for stage, artifacts in C.STAGES.items():
        assert artifacts, stage
        assert all(isinstance(a, str) and a for a in artifacts), stage


def test_the_stage_list_covers_every_gate():
    joined = " ".join(C.STAGES)
    for gate in ("G0", "G1", "G2", "G3", "G4", "G5"):
        assert gate in joined, gate
