"""Did the new cases actually kill the surviving mutations?

For every mutation: patch the source, run the suite as it was BEFORE this
session (git HEAD version of the test file) and as it is NOW, and print both
verdicts. "Fixed" means GREEN before / red after.

Snapshots bytes, patches, runs pytest, restores and asserts sha256 equality on
every file it touches. Nothing is left modified.
"""
import hashlib
import os
import pathlib
import subprocess

ROOT = pathlib.Path(r"C:\Users\chris\clee\ARBS-dd")
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
UNIV = ROOT / "SDRUtils" / "dealer_direction" / "universe.py"
SAN = ROOT / "SDRUtils" / "dealer_direction" / "sanity.py"
TESTS = ROOT / "tests" / "test_dealer_direction_universe.py"

NL = "\n"

MUTATIONS = [
    ("M1  drop the n_index>1 gate", UNIV,
     'EXCL_UNSUPPORTED_INDEX: u["bad_index"] | u["term_sofr"] | (u["n_index"] > 1),',
     'EXCL_UNSUPPORTED_INDEX: u["bad_index"] | u["term_sofr"],'),

    ("M2  on_facility: off-facility codes -> True", UNIV,
     "    if pid in OFF_FACILITY_PLATFORMS:" + NL + "        return False",
     "    if pid in OFF_FACILITY_PLATFORMS:" + NL + "        return True"),

    ("M3  swap the CME_TERM_SOFR detail string", UNIV,
     'out.loc[m & u["term_sofr"]] = "CME_TERM_SOFR"',
     'out.loc[m & u["term_sofr"]] = "MIXED_INDEX"'),

    ("M4b precedence: RISK_IMPLAUSIBLE before PRICING_ERROR", UNIV,
     "    EXCL_UNORIENTABLE," + NL + "    EXCL_PRICING_ERROR," + NL
     + "    EXCL_RISK_IMPLAUSIBLE," + NL + "    EXCL_NO_FIXED_RATE,",
     "    EXCL_UNORIENTABLE," + NL + "    EXCL_RISK_IMPLAUSIBLE," + NL
     + "    EXCL_PRICING_ERROR," + NL + "    EXCL_NO_FIXED_RATE,"),

    ("M5  delete the mixed-platform venue guard", UNIV,
     '    u.loc[u["n_platform"] > 1, "venue_class"] = VENUE_UNKNOWN',
     '    pass  # guard deleted'),

    ("M6  UWIN no longer outranks UFRO on a lifecycle print", UNIV,
     'take = (uwin > 0) & (u["is_lifecycle"] | (ufro <= 0))',
     'take = (uwin > 0) & (ufro <= 0)'),

    ("M7  drop .abs() from the PTP resolution", UNIV,
     'ptp = pd.to_numeric(u["ptp"], errors="coerce").abs()',
     'ptp = pd.to_numeric(u["ptp"], errors="coerce")'),

    ("M9  RISK_ZERO_SLACK 3.0 -> 300.0", SAN,
     "RISK_ZERO_SLACK = 3.0", "RISK_ZERO_SLACK = 300.0"),

    ("M24 on_facility: unrecognised -> False instead of None", UNIV,
     "    if pid in VENUE_EVIDENCE:" + NL + "        return True" + NL + "    return None",
     "    if pid in VENUE_EVIDENCE:" + NL + "        return True" + NL + "    return False"),

    ("M25 NON_CONSTANT_SCHEDULES: drop 'Custom'", UNIV,
     'NON_CONSTANT_SCHEDULES = frozenset({"Amortizing", "Custom", "Accreting"})',
     'NON_CONSTANT_SCHEDULES = frozenset({"Amortizing", "Accreting"})'),

    ("M32 _pybool: None -> False instead of None", UNIV,
     "    if v is None or (isinstance(v, float) and v != v):" + NL
     + "        return None" + NL + "    return bool(v)",
     "    return bool(v)"),

    ("M35 not_flow  any -> all", UNIV,
     'not_flow=("_not_flow", "any"),', 'not_flow=("_not_flow", "all"),'),
    ("M36 exer_nova any -> all", UNIV,
     'exer_nova=("_exer_nova", "any"),', 'exer_nova=("_exer_nova", "all"),'),
    ("M37 nonconstant any -> all", UNIV,
     'nonconstant=("_nonconstant", "any"),', 'nonconstant=("_nonconstant", "all"),'),
    ("M38 risk_bad  any -> all", UNIV,
     'risk_bad=("_risk_bad", "any"),', 'risk_bad=("_risk_bad", "all"),'),
    ("M43 no_rate   any -> all", UNIV,
     'no_rate=("_no_rate", "any"),', 'no_rate=("_no_rate", "all"),'),
    ("M44 bad_index any -> all", UNIV,
     'bad_index=("_bad_index", "any"),', 'bad_index=("_bad_index", "all"),'),
    ("M45 term_sofr any -> all", UNIV,
     'term_sofr=("_term_sofr", "any"),', 'term_sofr=("_term_sofr", "all"),'),
    ("M46 excluded_type any -> all", UNIV,
     'excluded_type=("_excluded_type", "any"),',
     'excluded_type=("_excluded_type", "all"),'),
    ("M47 is_mac    any -> all", UNIV,
     'is_mac=("is_mac", "any"),', 'is_mac=("is_mac", "all"),'),
    ("M48 is_unwind any -> all", UNIV,
     'is_unwind=("_is_unwind", "any"),', 'is_unwind=("_is_unwind", "all"),'),

    ("M42 FLAT_YIELD 0.04 -> 0.02", SAN, "FLAT_YIELD = 0.04", "FLAT_YIELD = 0.02"),
    ("M42b FLAT_YIELD 0.04 -> 0.038", SAN, "FLAT_YIELD = 0.04", "FLAT_YIELD = 0.038"),

    # --- controls: these were RED before and must stay red -------------------
    ("M39 is_block/is_capped any -> all  [CONTROL]", UNIV,
     'is_block=("is_block", "any"),' + NL + '        is_capped=("is_capped", "any"),',
     'is_block=("is_block", "all"),' + NL + '        is_capped=("is_capped", "all"),'),
    ("M40 INPUTS_MISSING never fires     [CONTROL]", SAN,
     'out["INPUTS_MISSING"] = ~inputs_ok',
     'out["INPUTS_MISSING"] = np.zeros(len(out), dtype=bool)'),
    ("M41 RISK_NULL never fires          [CONTROL]", SAN,
     'out["RISK_NULL"] = risk_null',
     'out["RISK_NULL"] = np.zeros(len(out), dtype=bool)'),
    ("M12 visibility from raw #96        [CONTROL]", UNIV,
     "visible = pd.Timestamp(instant) + pd.Timedelta(",
     "visible = pd.Timestamp(row.get('execution_timestamp')) + pd.Timedelta("),
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
    return r.returncode, (tail[-1] if tail else r.stdout.strip()[-160:])


OLD_TESTS = subprocess.run(
    ["git", "-C", str(ROOT), "show", "HEAD:tests/test_dealer_direction_universe.py"],
    capture_output=True).stdout

FILES = (UNIV, SAN, TESTS)
base = {p: (p.read_bytes(), sha(p)) for p in FILES}

try:
    rc_new, ln_new = run_suite()
    print(f"BASELINE new suite   rc={rc_new}  {ln_new}")
    TESTS.write_bytes(OLD_TESTS)
    rc_old, ln_old = run_suite()
    print(f"BASELINE old suite   rc={rc_old}  {ln_old}")
finally:
    TESTS.write_bytes(base[TESTS][0])
assert rc_new == 0 and rc_old == 0, "a baseline is not green; aborting"

print()
hdr = f"{'mutation':<44} {'BEFORE (old suite)':<20} {'AFTER (new suite)':<20}"
print(hdr)
print("-" * len(hdr))

rows = []
for name, path, old, new in MUTATIONS:
    src = base[path][0].decode("utf-8")
    if src.count(old) != 1:
        print(f"{name:<44} SKIP (anchor x{src.count(old)})")
        rows.append((name, "SKIP", "SKIP"))
        continue
    verdicts = {}
    for label, test_bytes in (("BEFORE", OLD_TESTS), ("AFTER", base[TESTS][0])):
        try:
            path.write_bytes(src.replace(old, new, 1).encode("utf-8"))
            TESTS.write_bytes(test_bytes)
            rc, _line = run_suite()
        finally:
            path.write_bytes(base[path][0])
            TESTS.write_bytes(base[TESTS][0])
        verdicts[label] = "GREEN (undetected)" if rc == 0 else "red (detected)"
    print(f"{name:<44} {verdicts['BEFORE']:<20} {verdicts['AFTER']:<20}")
    rows.append((name, verdicts["BEFORE"], verdicts["AFTER"]))

for p in FILES:
    assert sha(p) == base[p][1], f"final restore check failed {p}"
print(NL + "all files restored, sha256 verified")
rc, line = run_suite()
print(f"POST-RESTORE  rc={rc}  {line}")

fixed = [n for n, b, a in rows if b.startswith("GREEN") and a.startswith("red")]
still = [n for n, b, a in rows if a.startswith("GREEN")]
regress = [n for n, b, a in rows if b.startswith("red") and a.startswith("GREEN")]
print(f"{NL}NEWLY KILLED ({len(fixed)}):")
for n in fixed:
    print("  +", n)
print(f"{NL}STILL GREEN ({len(still)}):")
for n in still:
    print("  -", n)
print(f"{NL}REGRESSIONS ({len(regress)}):")
for n in regress:
    print("  !", n)
