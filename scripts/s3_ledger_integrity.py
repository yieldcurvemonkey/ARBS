"""Integrity check on the ledger and session-3 artifacts.

Run against an input whose answer is known: every row must parse, ids must be
unique, trials_total must be non-decreasing and must equal the running sum of
trials_delta, every `supersedes` target must exist, and every artifact cited in a
session-3 row must be on disk.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/s3_ledger_integrity.py
"""
import json
import re
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
LEDGER = _REPO / "docs" / "superpowers" / "ledgers" / "2026-08-08-citivelo-rv-loop-ledger.jsonl"
DATA = _REPO / "notebooks" / "data" / "citivelo_rv"

S3_ARTIFACTS = [
    "f7_packages.parquet", "f7_extract_diag.parquet", "f7_capacity.parquet",
    "f7_capacity_verdict.json", "f7_collision_check.json", "f7_enrichment.parquet",
    "f7_enrichment.json", "f7_universe.json", "f7_gate.parquet", "f7_gate_diag.parquet",
    "f7_gate_increment.parquet", "f7_gate_verdict.json", "f7_qdb_verdict.json",
    "f8_composition_probe.json", "f8_composition_daily.parquet", "f8_gate.parquet",
    "f8_gate_increment.parquet", "f8_gate_verdict.json",
    "cm3_roll_cells.parquet", "cm3_roll_verdict.json", "cm3_homogeneity.parquet",
    "cm3_homogeneity.json", "cm4_pairs.parquet", "cm4_eta_verdict.json",
]
S3_SCRIPTS = [
    "s3_sdr_diag.py", "s3_comp_check.py", "s3_ledger_open.py", "s3_register_f7.py",
    "s3_f7_package_extract.py", "s3_f7_amend_and_validate.py", "s3_f7_collision_check.py",
    "s3_f7_enrichment.py", "s3_f7_universe.py", "s3_f7_gate.py", "s3_verdict_f7.py",
    "s3_build_notebook.py", "s3_f8_composition_probe.py", "s3_f8_gate.py", "s3_verdict_f8.py",
    "s3_cm3_roll_spread.py", "s3_cm3_homogeneity.py", "s3_record_cm3.py",
    "s3_park_momentum.py", "s3_cm4_impact_exponent.py", "s3_record_cm4.py",
    "s3_ledger_integrity.py",
]
NOTEBOOK = _REPO / "notebooks" / "backtests" / "citivelo_rv" / "f7_flow_conditioned_qdb.ipynb"


ID_RE = re.compile(r"\b((?:L|C)-\d{4}|(?:V|H)-[A-Z0-9-]+)\b")


def check_supersedes(rows, idset) -> list:
    """Every id-shaped token in a `supersedes` field must name a real row.

    The field is prose -- rows legitimately supersede a CLAUSE ("H-F7 clause (8a)
    and L-0069's fill-lag import"), so tokens are extracted by pattern rather
    than by splitting, which is what an earlier version of this check got wrong.
    """
    out = []
    for r in rows:
        sup = r.get("supersedes")
        if not sup:
            continue
        for tok in ID_RE.findall(sup):
            if tok not in idset:
                out.append(f"{r['id']} supersedes unknown row {tok!r}")
    return out


def selftest_supersedes() -> None:
    """The checker must be able to FAIL. Verified against a known-bad input."""
    known = {"L-0001", "H-F7", "V-V-17B"}
    good = [{"id": "L-0002", "supersedes": "H-F7 clause (8a) and L-0001's rule"},
            {"id": "L-0003", "supersedes": "V-V-17B (its grounds)"}]
    bad = [{"id": "L-0004", "supersedes": "L-9999 (a row that does not exist)"}]
    assert check_supersedes(good, known) == [], "self-test: clean input flagged"
    assert len(check_supersedes(bad, known)) == 1, "self-test: BLIND to a dangling reference"
    print("supersedes self-test: PASS (clean input clean, dangling reference caught)")


def main() -> int:
    selftest_supersedes()
    fails = []
    rows = []
    for i, ln in enumerate(LEDGER.read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError as exc:
            fails.append(f"line {i} does not parse: {exc}")
    print(f"rows parsed: {len(rows)}")

    ids = [r["id"] for r in rows]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        fails.append(f"duplicate ids: {sorted(dupes)}")

    run = 0
    for r in rows:
        run += int(r.get("trials_delta", 0))
        if int(r["trials_total"]) != run:
            fails.append(f"{r['id']}: trials_total {r['trials_total']} != running sum {run}")
    print(f"trials_total final: {rows[-1]['trials_total']} (running sum {run})")

    prev = -1
    for r in rows:
        t = int(r["trials_total"])
        if t < prev:
            fails.append(f"{r['id']}: trials_total decreased {prev} -> {t}")
        prev = t

    idset = set(ids)
    bad_refs = check_supersedes(rows, idset)
    fails.extend(bad_refs)

    missing_a = [a for a in S3_ARTIFACTS if not (DATA / a).exists()]
    missing_s = [s for s in S3_SCRIPTS if not (_REPO / "scripts" / s).exists()]
    if missing_a:
        fails.append(f"missing artifacts: {missing_a}")
    if missing_s:
        fails.append(f"missing scripts: {missing_s}")
    print(f"artifacts present: {len(S3_ARTIFACTS) - len(missing_a)}/{len(S3_ARTIFACTS)}; "
          f"scripts present: {len(S3_SCRIPTS) - len(missing_s)}/{len(S3_SCRIPTS)}")

    if NOTEBOOK.exists():
        nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        errs = [o for c in nb["cells"] if c["cell_type"] == "code"
                for o in c.get("outputs", []) if o.get("output_type") == "error"]
        plotly = any("application/vnd.plotly.v1+json" in o.get("data", {})
                     for c in nb["cells"] if c["cell_type"] == "code"
                     for o in c.get("outputs", []) if o.get("output_type") == "display_data")
        imgs = sum(1 for c in nb["cells"] if c["cell_type"] == "code"
                   for o in c.get("outputs", []) if "image/png" in o.get("data", {}))
        print(f"notebook: {len(nb['cells'])} cells, {len(errs)} errors, "
              f"tearsheet rendered {plotly}, {imgs} rendered figures")
        if errs:
            fails.append(f"notebook has {len(errs)} error outputs")
        if not plotly:
            fails.append("notebook tearsheet did not render (L-0076 directive unmet)")
        if imgs < 2:
            fails.append(f"notebook has only {imgs} figures; equity curve + timeline expected")
    else:
        fails.append("executed notebook missing")

    # negative control: the checker must be able to fail. Assert a known-bad id is absent.
    if "L-9999" in idset:
        fails.append("negative control tripped")

    print()
    if fails:
        print("INTEGRITY FAILURES:")
        for f in fails:
            print("  -", f)
        return 1
    print("INTEGRITY: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
