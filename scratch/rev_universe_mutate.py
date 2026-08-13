"""Mutation sweep: does the suite actually detect each defect it names?

Patches a file, runs pytest, restores the ORIGINAL bytes and verifies the
sha256 matches. Nothing is left changed.
"""
import hashlib
import os
import pathlib
import subprocess

ROOT = pathlib.Path(r"C:\Users\chris\clee\ARBS-dd")
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
UNIV = ROOT / "SDRUtils" / "dealer_direction" / "universe.py"
SAN = ROOT / "SDRUtils" / "dealer_direction" / "sanity.py"

NL = "\n"

MUTATIONS = [
    ("M4b precedence: RISK_IMPLAUSIBLE before PRICING_ERROR", UNIV,
     "    EXCL_UNORIENTABLE," + NL + "    EXCL_PRICING_ERROR," + NL
     + "    EXCL_RISK_IMPLAUSIBLE," + NL + "    EXCL_NO_FIXED_RATE,",
     "    EXCL_UNORIENTABLE," + NL + "    EXCL_RISK_IMPLAUSIBLE," + NL
     + "    EXCL_PRICING_ERROR," + NL + "    EXCL_NO_FIXED_RATE,"),

    ("M24 on_facility: unrecognised code -> False instead of None", UNIV,
     "    if pid in VENUE_EVIDENCE:" + NL + "        return True" + NL + "    return None",
     "    if pid in VENUE_EVIDENCE:" + NL + "        return True" + NL + "    return False"),

    ("M25 NON_CONSTANT_SCHEDULES: drop 'Custom' (11,960 flow legs)", UNIV,
     'NON_CONSTANT_SCHEDULES = frozenset({"Amortizing", "Custom", "Accreting"})',
     'NON_CONSTANT_SCHEDULES = frozenset({"Amortizing", "Accreting"})'),

    ("M32 _pybool: None -> False instead of None", UNIV,
     "    if v is None or (isinstance(v, float) and v != v):" + NL
     + "        return None" + NL + "    return bool(v)",
     "    return bool(v)"),

    ("M35 not_flow aggregated with all() instead of any()", UNIV,
     'not_flow=("_not_flow", "any"),', 'not_flow=("_not_flow", "all"),'),

    ("M36 exer_nova aggregated with all() instead of any()", UNIV,
     'exer_nova=("_exer_nova", "any"),', 'exer_nova=("_exer_nova", "all"),'),

    ("M37 nonconstant aggregated with all() instead of any()", UNIV,
     'nonconstant=("_nonconstant", "any"),', 'nonconstant=("_nonconstant", "all"),'),

    ("M38 risk_bad aggregated with all() instead of any()", UNIV,
     'risk_bad=("_risk_bad", "any"),', 'risk_bad=("_risk_bad", "all"),'),

    ("M39 is_block/is_capped aggregated with all() not any()", UNIV,
     'is_block=("is_block", "any"),' + NL + '        is_capped=("is_capped", "any"),',
     'is_block=("is_block", "all"),' + NL + '        is_capped=("is_capped", "all"),'),

    ("M40 sanity: INPUTS_MISSING never fires", SAN,
     'out["INPUTS_MISSING"] = ~inputs_ok',
     'out["INPUTS_MISSING"] = np.zeros(len(out), dtype=bool)'),

    ("M41 sanity: RISK_NULL never fires", SAN,
     'out["RISK_NULL"] = risk_null',
     'out["RISK_NULL"] = np.zeros(len(out), dtype=bool)'),

    ("M42 sanity: FLAT_YIELD 0.04 -> 0.02", SAN,
     "FLAT_YIELD = 0.04", "FLAT_YIELD = 0.02"),

    ("M43 no_rate aggregated with all() instead of any()", UNIV,
     'no_rate=("_no_rate", "any"),', 'no_rate=("_no_rate", "all"),'),

    ("M44 bad_index aggregated with all() instead of any()", UNIV,
     'bad_index=("_bad_index", "any"),', 'bad_index=("_bad_index", "all"),'),
]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_suite():
    env = dict(os.environ, ARBS_SUPABASE_ENABLED="0")
    r = subprocess.run(
        [PY, "-m", "pytest", "tests/test_dealer_direction_universe.py", "-q",
         "--no-header", "-p", "no:cacheprovider"],
        cwd=str(ROOT), env=env, capture_output=True, text=True)
    tail = [ln for ln in r.stdout.strip().splitlines()
            if "passed" in ln or "failed" in ln or "error" in ln.lower()]
    return r.returncode, (tail[-1] if tail else r.stdout.strip()[-200:])


base = {p: (p.read_bytes(), sha(p)) for p in (UNIV, SAN)}
rc, line = run_suite()
print(f"BASELINE  rc={rc}  {line}")
assert rc == 0, "baseline is not green; aborting"

results = []
for name, path, old, new in MUTATIONS:
    src = base[path][0].decode("utf-8")
    if src.count(old) != 1:
        print(f"{name:<56} SKIP (anchor x{src.count(old)})")
        results.append((name, "SKIP"))
        continue
    try:
        path.write_bytes(src.replace(old, new, 1).encode("utf-8"))
        rc, line = run_suite()
    finally:
        path.write_bytes(base[path][0])
        assert sha(path) == base[path][1], f"RESTORE FAILED for {path}"
    verdict = "GREEN (undetected)" if rc == 0 else "red (detected)"
    print(f"{name:<56} {verdict:<20} {line}")
    results.append((name, verdict))

for p in (UNIV, SAN):
    assert sha(p) == base[p][1], f"final restore check failed {p}"
print(NL + "all files restored, sha256 verified")
rc, line = run_suite()
print(f"POST-RESTORE  rc={rc}  {line}")

print(NL + "UNDETECTED MUTATIONS:")
for n, v in results:
    if v.startswith("GREEN"):
        print("  -", n)
