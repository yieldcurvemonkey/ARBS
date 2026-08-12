"""Second pass: the 5 mutations that survived the first round of new cases."""
import hashlib
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(r"C:\Users\chris\clee\ARBS-dd")
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
UNIV = ROOT / "SDRUtils" / "dealer_direction" / "universe.py"
SAN = ROOT / "SDRUtils" / "dealer_direction" / "sanity.py"
TESTS = ROOT / "tests" / "test_dealer_direction_universe.py"
NL = "\n"

MUTATIONS = [
    ("M3  swap the CME_TERM_SOFR detail string", UNIV,
     'out.loc[m & u["term_sofr"]] = "CME_TERM_SOFR"',
     'out.loc[m & u["term_sofr"]] = "MIXED_INDEX"'),
    ("M4b precedence: RISK_IMPLAUSIBLE before PRICING_ERROR", UNIV,
     "    EXCL_UNORIENTABLE," + NL + "    EXCL_PRICING_ERROR," + NL
     + "    EXCL_RISK_IMPLAUSIBLE," + NL + "    EXCL_NO_FIXED_RATE,",
     "    EXCL_UNORIENTABLE," + NL + "    EXCL_RISK_IMPLAUSIBLE," + NL
     + "    EXCL_PRICING_ERROR," + NL + "    EXCL_NO_FIXED_RATE,"),
    ("M4c precedence: NO_FIXED_RATE above UNSUPPORTED_INDEX", UNIV,
     "    EXCL_UNSUPPORTED_INDEX," + NL + "    EXCL_UNORIENTABLE,",
     "    EXCL_NO_FIXED_RATE," + NL + "    EXCL_UNSUPPORTED_INDEX," + NL
     + "    EXCL_UNORIENTABLE,"),
    ("M5  delete the mixed-platform venue guard", UNIV,
     '    u.loc[u["n_platform"] > 1, "venue_class"] = VENUE_UNKNOWN',
     '    pass  # guard deleted'),
    ("M7  drop .abs() from the PTP resolution", UNIV,
     'ptp = pd.to_numeric(u["ptp"], errors="coerce").abs()',
     'ptp = pd.to_numeric(u["ptp"], errors="coerce")'),
    ("M48 is_unwind any -> all", UNIV,
     'is_unwind=("_is_unwind", "any"),', 'is_unwind=("_is_unwind", "all"),'),
    # controls that must stay red
    ("M39 is_block/is_capped any -> all  [CONTROL]", UNIV,
     'is_block=("is_block", "any"),' + NL + '        is_capped=("is_capped", "any"),',
     'is_block=("is_block", "all"),' + NL + '        is_capped=("is_capped", "all"),'),
    ("M42 FLAT_YIELD 0.04 -> 0.02        [CONTROL]", SAN,
     "FLAT_YIELD = 0.04", "FLAT_YIELD = 0.02"),
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


FILES = (UNIV, SAN, TESTS)
base = {p: (p.read_bytes(), sha(p)) for p in FILES}
rc, line = run_suite()
print(f"BASELINE rc={rc}  {line}", flush=True)
assert rc == 0

for name, path, old, new in MUTATIONS:
    src = base[path][0].decode("utf-8")
    if src.count(old) != 1:
        print(f"{name:<56} SKIP (anchor x{src.count(old)})", flush=True)
        continue
    try:
        path.write_bytes(src.replace(old, new, 1).encode("utf-8"))
        rc, line = run_suite()
    finally:
        path.write_bytes(base[path][0])
        assert sha(path) == base[path][1], f"RESTORE FAILED {path}"
    v = "GREEN (undetected)" if rc == 0 else "red (detected)"
    print(f"{name:<56} {v:<20} {line}", flush=True)

for p in FILES:
    assert sha(p) == base[p][1], f"final restore failed {p}"
rc, line = run_suite()
print(f"{NL}all restored, sha256 verified.  POST-RESTORE rc={rc}  {line}", flush=True)
sys.exit(0)
