"""Control for the mutation harness itself: it must be able to print GREEN.

Every mutation in vfy_universe_mutate_ext.py came back red. A harness that
reports red unconditionally (wrong pytest path, import error counted as a
failure) would look identical. This patches something inert -- an extra member
in NON_CONSTANT_SCHEDULES that no test and no tape row can reach -- and the
harness must call it GREEN.
"""
import hashlib
import os
import pathlib
import subprocess

ROOT = pathlib.Path(r"C:\Users\chris\clee\ARBS-dd")
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
UNIV = ROOT / "SDRUtils" / "dealer_direction" / "universe.py"

OLD = 'NON_CONSTANT_SCHEDULES = frozenset({"Amortizing", "Custom", "Accreting"})'
NEW = ('NON_CONSTANT_SCHEDULES = frozenset('
       '{"Amortizing", "Custom", "Accreting", "ZZ_INERT_CONTROL"})')


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run():
    env = dict(os.environ, ARBS_SUPABASE_ENABLED="0")
    r = subprocess.run(
        [PY, "-m", "pytest", "tests/test_dealer_direction_universe.py", "-q",
         "--no-header", "-p", "no:cacheprovider"],
        cwd=str(ROOT), env=env, capture_output=True, text=True)
    tail = [ln for ln in r.stdout.strip().splitlines() if "passed" in ln or "failed" in ln]
    return r.returncode, (tail[-1] if tail else r.stdout[-200:])


orig, h = UNIV.read_bytes(), sha(UNIV)
src = orig.decode("utf-8")
assert src.count(OLD) == 1
try:
    UNIV.write_bytes(src.replace(OLD, NEW, 1).encode("utf-8"))
    rc, line = run()
finally:
    UNIV.write_bytes(orig)
    assert sha(UNIV) == h, "RESTORE FAILED"
print("inert control ->", "GREEN (undetected)" if rc == 0 else "red (detected)", line)
print("restored, sha256 verified")
