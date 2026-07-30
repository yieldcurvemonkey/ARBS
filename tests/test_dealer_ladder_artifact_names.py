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


# ============== two orchestration paths must not drift apart
RUNNER_SRC = open(os.path.join(REPO, "scripts", "run_dealer_ladder_gates.py"),
                  encoding="utf-8").read()


def _stages_in_run_all() -> set:
    block = GATES_SRC[GATES_SRC.index("def run_all("):]
    return set(re.findall(r"(?<![\w.])(run_[a-z_0-9]+)\s*\(", block)) - {"run_all"}


def _stages_in_runner() -> set:
    return set(re.findall(r"gates\.(run_[a-z_0-9]+)\s*\(", RUNNER_SRC))


def test_run_all_and_the_runner_script_call_the_same_stages():
    """`gates.run_all` is a programmatic entry point that NOTHING currently calls -- not a
    test, not a script, not the notebook -- while `scripts/run_dealer_ladder_gates.py` is
    what actually produced the results. Two orchestration paths, one exercised, are a
    standing invitation to drift: a stage added to the runner and forgotten in run_all
    means a later caller silently gets a different set of gates than the report was built
    from. They are pinned equal here rather than kept equal by attention."""
    a, b = _stages_in_run_all(), _stages_in_runner()
    assert a == b, (f"only in run_all: {sorted(a - b)}; "
                    f"only in the runner: {sorted(b - a)}")


def test_both_paths_include_every_gate_and_the_cross_check():
    stages = _stages_in_runner()
    for required in ("run_g0", "run_g1", "run_g2", "run_g3", "run_primary", "run_g5",
                     "run_cross_check_comparison", "run_placebos", "run_label_free",
                     "run_conditioning", "run_staleness_sensitivity", "run_grid"):
        assert required in stages, required


def test_the_runner_releases_its_db_connection_after_g0():
    """Nothing after G0 needs the database -- every later stage works on panels already in
    ctx -- so a connection held for the remaining hours is pure occupancy in a shared
    pgbouncer pool. This study noticed because its own long-lived connection stalled the
    production backfill for 35 minutes."""
    src = RUNNER_SRC
    g0 = src.index('stage("G0"')
    primary = src.index('stage("G4-primary"')
    between = src[g0:primary]
    assert "conn.close()" in between, "the connection must be released right after G0"
    assert "conn = None" in between
