"""The writer and the two reporting layers must agree on artifact names.

They did not. The renderer declared `g0_flip_rate`, `g0_direction_skew` and
`g0_implied_accuracy` while `run_g0` wrote `g0_skew_vs_independent`,
`g0_skew_vs_independent_by_hour` and `g0_flip_by_trade_type` — so three stages that DO
run would have been reported as MISSING, and three that run would not have appeared at
all. A report that lists a stage as not-run when it ran is exactly as misleading as the
reverse, and it is the failure the completeness pass exists to prevent rather than to
commit.

These tests read the names out of the source instead of restating them, so the only way
to break them is to actually break the agreement.
"""
import importlib.util
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load("scripts/render_findings_tables.py", "render_findings_tables")
C = _load("scripts/dealer_ladder_completeness.py", "dealer_ladder_completeness")

GATES_SRC = open(os.path.join(REPO, "BT", "dealer_ladder", "gates.py"),
                 encoding="utf-8").read()


SPACES = ("FUTURES", "FED_FUNDS")


def written_names() -> set:
    """Artifact names `gates.py` actually writes.

    Three forms, all read from the source rather than restated here, because a list
    restated in a test drifts exactly like the one it is meant to guard:

      1. a literal ``_write(ctx, "name", ...)``;
      2. a per-space name ``_write(ctx, f"g3_horse_race_{space}", ...)``, expanded over
         both spaces — missing this form was itself a bug in the first version of this
         test, which then reported two REQUIRED artifacts as unwritten when they are
         written on every run;
      3. the G0 loop over a tuple of suffixes.
    """
    names = set(re.findall(r'_write\(ctx,\s*"([a-z0-9_]+)"', GATES_SRC))
    for stem in re.findall(r'_write\(ctx,\s*f"([a-z0-9_]+_)\{space\}"', GATES_SRC):
        names |= {f"{stem}{s}" for s in SPACES}
    for block in re.findall(r'for name in \(([^)]*)\):\s*\n\s*if name in out:\s*\n'
                            r'\s*_write\(ctx, f"g0_\{name\}"', GATES_SRC):
        names |= {f"g0_{n}" for n in re.findall(r'"([a-z0-9_]+)"', block)}
    return names


def declared_by_renderer() -> set:
    return {s[0] for s in R.SECTIONS}


def declared_by_completeness() -> set:
    return {a for arts in C.STAGES.values() for a in arts}


def test_the_source_actually_yields_names():
    """A guard on the guard: if the regexes stop matching, every other test here would
    pass vacuously."""
    w = written_names()
    assert len(w) > 15, w
    assert "verdicts" in w and "g0_flip_mechanism" in w


def test_every_written_artifact_is_declared_by_the_renderer():
    missing = written_names() - declared_by_renderer() - RENDER_EXEMPT
    assert not missing, f"written but never rendered: {sorted(missing)}"


# g0_label_recon is the per-unit reconciliation frame -- hundreds of rows, one per
# sampled print. The completeness inventory uses it as PROOF the flip study ran; the
# renderer deliberately does not print it, because a per-unit dump is not a report table.
RENDER_EXEMPT = {"g0_label_recon"}


def test_the_two_reporting_layers_agree_on_g0():
    """Where the drift actually happened: the renderer and the completeness inventory
    disagreed with the writer AND with each other."""
    r = {n for n in declared_by_renderer() if n.startswith("g0_")}
    c = {n for n in declared_by_completeness() if n.startswith("g0_")} - RENDER_EXEMPT
    assert r == c, f"renderer only: {sorted(r - c)}; completeness only: {sorted(c - r)}"


def test_no_declared_g0_artifact_is_one_nothing_writes():
    """The exact defect: `g0_flip_rate` and `g0_direction_skew` were declared by both
    reporting layers and written by nothing, so those stages could only ever read as
    missing."""
    declared = ({n for n in declared_by_renderer() if n.startswith("g0_")}
                | {n for n in declared_by_completeness() if n.startswith("g0_")})
    orphans = declared - written_names()
    assert not orphans, f"declared but nothing writes them: {sorted(orphans)}"


def test_required_renderer_artifacts_are_all_written():
    required = {s[0] for s in R.SECTIONS if s[2]}
    missing = required - written_names() - {"trial_ledger", "verdicts"}
    assert not missing, f"marked REQUIRED but nothing writes them: {sorted(missing)}"


def test_the_completeness_inventory_covers_every_rendered_section():
    """Anything worth a table is worth accounting for when it is absent.

    No slack list: an exemption here is exactly how a diagnostic goes missing from the
    completeness pass while still being promised by the report.
    """
    missing = declared_by_renderer() - declared_by_completeness()
    assert not missing, (
        f"rendered but not in the completeness inventory: {sorted(missing)}")


def test_the_zq_cross_check_is_actually_run():
    """The brief makes ZQ the comparison the mechanism turns on -- leading SR3 but not
    ZQ reads as liquidity-routed hedging, leading ZQ specifically reads as
    meeting-targeted. Both gates take `space=`, but the runner asked only for FUTURES,
    so the tables existed in the code and were never produced."""
    runner = open(os.path.join(REPO, "scripts", "run_dealer_ladder_gates.py"),
                  encoding="utf-8").read()
    assert 'run_g2(ctx, space="FED_FUNDS")' in runner
    assert 'run_g3(ctx, space="FED_FUNDS")' in runner
