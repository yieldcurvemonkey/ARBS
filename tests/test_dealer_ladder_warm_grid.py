"""The decision-grid warm pass.

Written because the first version of this script warmed NOTHING and reported success
in 0.0 seconds: `trading_days` yields Timestamps, the grid mask is built from `.date`
objects, and `Timestamp == date` is False, so every session selected zero minutes. A
warm pass that silently does nothing is worse than one that fails, because the cost
lands later as ~13,400 single-point curve builds in the middle of the gate run.
"""
import importlib.util
import json
import os

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "warm_dealer_ladder_grid",
    os.path.join(REPO, "scripts", "warm_dealer_ladder_grid.py"))
W = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(W)


def test_the_dry_run_sizes_the_real_work(capsys):
    """The regression: this printed 138 sessions while selecting zero minutes each."""
    assert W.main(["--start", "2026-01-12", "--end", "2026-01-31", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "sessions x 2 curves" in out
    per = [ln for ln in out.splitlines() if "per session" in ln]
    assert per, out
    n = int(per[0].split("(")[1].split(" per")[0])
    assert n > 50, f"a session must select a full grid, got {n}"


def test_every_session_maps_to_grid_minutes():
    """The guard that turns the silent-zero-work failure into an exit."""
    from BT.dealer_ladder import config as cfg, data
    conf = cfg.LadderStudyConfig()
    days = [pd.Timestamp(d).date() for d in
            data.trading_days((pd.Timestamp("2026-01-12").date(),
                               pd.Timestamp("2026-01-31").date()))]
    grid = data.decision_grid(days, conf.signal)
    et = pd.DatetimeIndex(grid).tz_convert("America/New_York")
    covered = set(pd.Series(et.date, index=pd.DatetimeIndex(grid)))
    assert covered == set(days), set(days) ^ covered


def test_a_date_never_equals_a_timestamp():
    """The comparison at the root of it, pinned so nobody re-derives it the hard way."""
    d = pd.Timestamp("2026-01-13").date()
    assert pd.Timestamp("2026-01-13") != d
    assert pd.Timestamp("2026-01-13").date() == d


def test_the_ledger_skips_sessions_already_recorded_ok(tmp_path, capsys):
    path = tmp_path / "ledger.jsonl"
    rows = [
        {"day": "2026-01-13", "curve": "USD-SOFR-1D-Q12xM12STIRT", "ok": True},
        {"day": "2026-01-14", "curve": "USD-SOFR-1D-Q12xM12STIRT", "ok": False},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    done = W._load_ledger(str(path))
    assert ("2026-01-13", "USD-SOFR-1D-Q12xM12STIRT") in done
    assert ("2026-01-14", "USD-SOFR-1D-Q12xM12STIRT") not in done, \
        "a FAILED session must be retried, not skipped"


def test_a_corrupt_ledger_line_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"day": "2026-01-13", "curve": "c", "ok": true}\n'
                    "{not json\n"
                    '{"day": "2026-01-14", "curve": "c", "ok": true}\n',
                    encoding="utf-8")
    done = W._load_ledger(str(path))
    assert done == {("2026-01-13", "c"), ("2026-01-14", "c")}


def test_a_missing_ledger_is_an_empty_set(tmp_path):
    assert W._load_ledger(str(tmp_path / "nope.jsonl")) == set()
    assert W._load_ledger(None) == set()


def test_append_then_load_round_trips(tmp_path):
    path = str(tmp_path / "l.jsonl")
    W._append(path, {"day": "2026-02-02", "curve": "c", "ok": True, "seconds": 1.5})
    assert W._load_ledger(path) == {("2026-02-02", "c")}


def test_dry_run_reports_what_the_ledger_already_covers(tmp_path, capsys):
    from SDRUtils.stir_flow import config as sconfig
    path = tmp_path / "ledger.jsonl"
    sofr = sconfig.CURVE_FOR["SOFR"]
    ff = sconfig.CURVE_FOR["FED_FUNDS"]
    path.write_text("\n".join(
        json.dumps({"day": d, "curve": c, "ok": True})
        for d in ("2026-01-12", "2026-01-13") for c in (sofr, ff)) + "\n",
        encoding="utf-8")
    assert W.main(["--start", "2026-01-12", "--end", "2026-01-31",
                   "--ledger", str(path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "4 already recorded" in out


@pytest.mark.parametrize("spaces, want", [("FUTURES", 1), ("FUTURES,FED_FUNDS", 2)])
def test_spaces_selects_which_curves_are_warmed(spaces, want, capsys):
    assert W.main(["--start", "2026-01-12", "--end", "2026-01-13",
                   "--spaces", spaces, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"x {want} curves" in out
