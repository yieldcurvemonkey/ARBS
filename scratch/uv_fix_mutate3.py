"""Third pass: do the tests written for the CODE changes actually bite?

Each mutation reverts one of this session's code fixes; the matching new test
must go red.
"""
import hashlib
import os
import pathlib
import subprocess

ROOT = pathlib.Path(r"C:\Users\chris\clee\ARBS-dd")
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
UNIV = ROOT / "SDRUtils" / "dealer_direction" / "universe.py"
NL = "\n"

MUTATIONS = [
    ("R1 revert the by_venue column rename", UNIV,
     'by_venue["dv01_share_of_kept_pct"] = (', 'by_venue["dv01_share_pct"] = ('),
    ("R2 revert the _print_report zero-unit guard", UNIV,
     '    if n == 0:' + NL + '        raise ValueError("nothing to report: 0 units")' + NL,
     ''),
    ("R3 revert the unwind counters in aggregate_units", UNIV,
     '        "unwind_units_kept": int(kept["is_unwind"].sum()),' + NL
     + '        "lifecycle_units_kept": int(kept["is_lifecycle"].sum()),' + NL,
     ''),
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


base_bytes, base_sha = UNIV.read_bytes(), sha(UNIV)
rc, line = run_suite()
print(f"BASELINE rc={rc}  {line}", flush=True)
assert rc == 0

for name, path, old, new in MUTATIONS:
    src = base_bytes.decode("utf-8")
    if src.count(old) != 1:
        print(f"{name:<48} SKIP (anchor x{src.count(old)})", flush=True)
        continue
    try:
        path.write_bytes(src.replace(old, new, 1).encode("utf-8"))
        rc, line = run_suite()
    finally:
        path.write_bytes(base_bytes)
        assert sha(path) == base_sha, "RESTORE FAILED"
    v = "GREEN (undetected)" if rc == 0 else "red (detected)"
    print(f"{name:<48} {v:<20} {line}", flush=True)

assert sha(UNIV) == base_sha
rc, line = run_suite()
print(f"{NL}restored, sha256 verified.  POST-RESTORE rc={rc}  {line}", flush=True)
