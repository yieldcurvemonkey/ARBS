"""Extension of rev_universe_mutate.py: the 7 review survivors that file omits.

M1, M2, M3, M5, M6, M7, M9 (review sections 2.1, 2.3, 2.6, 2.9). Anchors
re-grepped against the CURRENT source -- M9's old `3.0 * quantum` no longer
exists, it is now the named `RISK_ZERO_SLACK`.

Same protocol as the original: snapshot bytes, patch, pytest, restore, assert
sha256 equality. Nothing is left changed.
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
    ("M1 drop the n_index > 1 gate", UNIV,
     'EXCL_UNSUPPORTED_INDEX: u["bad_index"] | u["term_sofr"] | (u["n_index"] > 1),',
     'EXCL_UNSUPPORTED_INDEX: u["bad_index"] | u["term_sofr"],'),

    ("M2 on_facility: off-facility codes -> True", UNIV,
     "    if pid in OFF_FACILITY_PLATFORMS:" + NL + "        return False",
     "    if pid in OFF_FACILITY_PLATFORMS:" + NL + "        return True"),

    ("M3 swap the CME_TERM_SOFR / MIXED_INDEX detail strings", UNIV,
     'out.loc[m & u["term_sofr"]] = "CME_TERM_SOFR"' + NL
     + '    out.loc[(u["exclusion"] == EXCL_UNSUPPORTED_INDEX) & out.isna()] = "MIXED_INDEX"',
     'out.loc[m & u["term_sofr"]] = "MIXED_INDEX"' + NL
     + '    out.loc[(u["exclusion"] == EXCL_UNSUPPORTED_INDEX) & out.isna()] = "CME_TERM_SOFR"'),

    ("M5 delete the mixed-platform venue guard", UNIV,
     '    u.loc[u["n_platform"] > 1, "venue_class"] = VENUE_UNKNOWN' + NL,
     ''),

    ("M6 UWIN no longer outranks UFRO on a lifecycle unit", UNIV,
     'take = (uwin > 0) & (u["is_lifecycle"] | (ufro <= 0))',
     'take = (uwin > 0) & (ufro <= 0)'),

    ("M7 drop .abs() from the PTP", UNIV,
     'ptp = pd.to_numeric(u["ptp"], errors="coerce").abs()',
     'ptp = pd.to_numeric(u["ptp"], errors="coerce")'),

    ("M9 sanity: RISK_ZERO_SLACK 3.0 -> 300.0", SAN,
     "RISK_ZERO_SLACK = 3.0", "RISK_ZERO_SLACK = 300.0"),

    # control: a mutation that MUST go red, to prove the harness reports red
    ("CONTROL RISK_QUANTUM -> 0 (must be red)", SAN,
     "RISK_QUANTUM = 100.0", "RISK_QUANTUM = 0.0"),
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
print(f"BASELINE  rc={rc}  {line}", flush=True)
assert rc == 0, "baseline is not green; aborting"

results = []
for name, path, old, new in MUTATIONS:
    src = base[path][0].decode("utf-8")
    if src.count(old) != 1:
        print(f"{name:<52} SKIP (anchor x{src.count(old)})", flush=True)
        results.append((name, "SKIP"))
        continue
    try:
        path.write_bytes(src.replace(old, new, 1).encode("utf-8"))
        rc, line = run_suite()
    finally:
        path.write_bytes(base[path][0])
        assert sha(path) == base[path][1], f"RESTORE FAILED for {path}"
    verdict = "GREEN (undetected)" if rc == 0 else "red (detected)"
    print(f"{name:<52} {verdict:<20} {line}", flush=True)
    results.append((name, verdict))

for p in (UNIV, SAN):
    assert sha(p) == base[p][1], f"final restore check failed {p}"
print(NL + "all files restored, sha256 verified")
rc, line = run_suite()
print(f"POST-RESTORE  rc={rc}  {line}")

print(NL + "UNDETECTED / SKIPPED:")
for n, v in results:
    if not v.startswith("red"):
        print(f"  {v:<20} {n}")
