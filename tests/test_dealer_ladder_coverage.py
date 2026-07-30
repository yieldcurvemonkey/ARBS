"""The coverage report is the acceptance gate, so it gets tests.

`--strict` is what decides the dataset is complete, and every other check in this study
defers to it. Two properties matter more than formatting:

  * a trading session that is ABSENT must be an anomaly, because an empty month exits zero
    and reads as success everywhere else;
  * a vintage that appears only in rows no gate can reach must NOT fail the gate, because a
    gate that fails for benign reasons is a gate that gets relaxed.

The DB-touching parts are not exercised here; `problems()` and `render()` are pure.
"""
import importlib.util
import os

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "dealer_ladder_coverage", os.path.join(REPO, "scripts", "dealer_ladder_coverage.py"))
C = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(C)


def _cov(rows):
    base = dict(classified=100, paid=70, received=30, unknown=0, curve_suspect=10,
                n_methods=3, projected_units=100, ladder_rows=3600, n_spaces=3,
                futures_rows=1200, ff_rows=1200, meeting_rows=1200, serff_rows=0,
                null_p_flip=0, null_delta=0, marked_units=100, entry_marked_units=100,
                eod_marked_units=30, marks=130, null_npv=0)
    out = []
    for i, over in enumerate(rows):
        r = dict(base)
        r.update(over)
        r["day"] = pd.Timestamp("2026-03-02") + pd.Timedelta(days=i)
        out.append(r)
    df = pd.DataFrame(out)
    for c, num, den in (("unknown_pct", "unknown", "classified"),
                        ("projected_pct", "projected_units", "classified"),
                        ("marked_pct", "marked_units", "projected_units"),
                        ("eod_marked_pct", "eod_marked_units", "projected_units"),
                        ("paid_pct", "paid", "classified")):
        df[c] = 100.0 * df[num] / df[den].replace(0, np.nan)
    return df


def _res(rows, study_vint=None, vint=None):
    return {"coverage": _cov(rows),
            "vintages": vint if vint is not None else pd.DataFrame(
                columns=["tbl", "code_vintage", "rows"]),
            "study_vintages": study_vint if study_vint is not None else pd.DataFrame(
                [{"ladder_vintage": "468474ca6f84",
                  "direction_vintage": "468474ca6f84", "rows": 1000}])}


def test_a_clean_window_has_no_anomalies():
    assert C.problems(_res([{}, {}, {}])) == []


def test_an_absent_session_is_an_anomaly():
    """The failure mode that hid May: an empty month exits zero everywhere else."""
    probs = C.problems(_res([{}, {"classified": 0, "projected_units": 0,
                                  "marked_units": 0, "eod_marked_units": 0,
                                  "marks": 0, "paid": 0, "received": 0}]))
    assert any("ZERO classified" in p for p in probs)


def test_classified_but_never_projected_is_reported_separately():
    """It means the risk model failed for the whole day -- the failure that once collapsed
    projection coverage from 74% to 0% behind a bare except: pass."""
    probs = C.problems(_res([{"projected_units": 0, "marked_units": 0,
                              "eod_marked_units": 0}]))
    assert any("NEVER PROJECTED" in p for p in probs)


def test_projected_but_unmarked_is_a_different_diagnosis():
    probs = C.problems(_res([{"marked_units": 0, "eod_marked_units": 0, "marks": 0}]))
    assert any("never marked" in p for p in probs)
    assert not any("NEVER PROJECTED" in p for p in probs)


def test_null_delta_dv01_is_flagged_as_the_all_nan_risk_hazard():
    probs = C.problems(_res([{"null_delta": 12}]))
    assert any("NULL delta_dv01" in p for p in probs)


def test_a_vintage_only_in_unreachable_rows_does_NOT_fail_the_gate():
    """147 direction rows predate the code_vintage column and have no ladder rows, so no
    gate can reach them -- and July's purge can never remove them, because it is skipped
    whenever any day errored and 2026-07-03 is a market holiday that errors every time.
    Failing --strict on those would be failing for a benign reason, and a gate that does
    that is a gate that gets relaxed."""
    table_wide = pd.DataFrame([
        {"tbl": "arbs_stir_direction_v1", "code_vintage": "468474ca6f84", "rows": 73074},
        {"tbl": "arbs_stir_direction_v1", "code_vintage": "(null)", "rows": 147}])
    probs = C.problems(_res([{}], vint=table_wide))
    assert probs == [], probs


def test_a_mixed_vintage_among_STUDY_VISIBLE_rows_DOES_fail_the_gate():
    mixed = pd.DataFrame([
        {"ladder_vintage": "468474ca6f84", "direction_vintage": "468474ca6f84",
         "rows": 900},
        {"ladder_vintage": "aaaaaaaaaaaa", "direction_vintage": "468474ca6f84",
         "rows": 100}])
    probs = C.problems(_res([{}], study_vint=mixed))
    assert any("STUDY-VISIBLE" in p and "vintage pairs" in p for p in probs)


def test_a_null_vintage_among_study_visible_rows_fails():
    nulls = pd.DataFrame([{"ladder_vintage": "(null)",
                           "direction_vintage": "468474ca6f84", "rows": 5}])
    probs = C.problems(_res([{}], study_vint=nulls))
    assert any("NULL code_vintage" in p for p in probs)


def test_render_separates_the_two_vintage_tables():
    table_wide = pd.DataFrame([
        {"tbl": "arbs_stir_direction_v1", "code_vintage": "(null)", "rows": 147}])
    md = C.render(_res([{}], vint=table_wide), "2026-01-12", "2026-07-29")
    assert "STUDY-VISIBLE rows only" in md
    assert "every row in each table" in md
    assert "no gate can reach" in md


def test_render_says_when_there_are_no_anomalies():
    md = C.render(_res([{}, {}]), "2026-01-12", "2026-07-29")
    assert "None: every session classified" in md
