"""Mutation harness: does the package_price suite actually catch a sign slip?

Mutates the implementation in place, runs the suite, restores the original
bytes and verifies the sha256 round-trips. Nothing is committed and nothing
else in the tree is touched.
"""
from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PP = ROOT / "SDRUtils" / "dealer_direction" / "package_price.py"
UNI = ROOT / "SDRUtils" / "dealer_direction" / "universe.py"
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
TESTS = ["tests/test_dealer_direction_package_price.py",
         "tests/test_dealer_direction_universe.py"]

MUTANTS = [
    ("M01 deviation sign", PP,
     "    deviation = reported - model",
     "    deviation = model - reported"),
    ("M02 orientation global flip", PP,
     "        out.append(int(s) * (1 if v > 0 else -1))",
     "        out.append(-int(s) * (1 if v > 0 else -1))"),
    ("M03 received_signs sign", PP,
     "        received = tuple(dealer_sign * oi for oi in o)",
     "        received = tuple(-dealer_sign * oi for oi in o)"),
    ("M04 reported price from net, not PTP", PP,
     "    reported = math.copysign(abs(ptp), cash.net)",
     "    reported = cash.net"),
    ("M05 lifecycle negation dropped", PP,
     "            received = tuple(-r for r in received)",
     "            received = tuple(r for r in received)"),
    ("M06 near-mid comparison inverted", PP,
     "        if p > 0 and abs(fi) / p < float(leg_sign_resolution_bps):",
     "        if p > 0 and abs(fi) / p > float(leg_sign_resolution_bps):"),
    ("M07 tieout gate disabled", PP,
     "    if tieout_bps > float(tieout_max_bps) or cash.net == 0.0:",
     "    if tieout_bps > 1e18 * float(tieout_max_bps) or cash.net == 0.0:"),
    ("M08 net==0 guard dropped", PP,
     "    if tieout_bps > float(tieout_max_bps) or cash.net == 0.0:",
     "    if tieout_bps > float(tieout_max_bps):"),
    ("M09 PTP floor dropped", PP,
     "    if ptp is None or abs(ptp) <= PTP_USD_FLOOR:",
     "    if ptp is None:"),
    ("M10 tieout scaled by 2", PP,
     "    tieout_bps = cash.residual / dv01",
     "    tieout_bps = cash.residual / (2.0 * dv01)"),
    ("M11 leg-at-mid gate dropped", PP,
     "    if any(v == 0.0 for v in f):",
     "    if False and any(v == 0.0 for v in f):"),
    ("M12 model price sign", PP,
     "    model = package_value(o, f)",
     "    model = -package_value(o, f)"),
    ("M13 package_value ignores orientation", PP,
     "    return float(sum(int(o) * float(f) for o, f in zip(orientation, npv_pays)))",
     "    return float(sum(float(f) for o, f in zip(orientation, npv_pays)))"),
    ("M14 dealer_side zero branch bypassed", PP,
     "    dealer_sign = conventions.dealer_side(dev_bps)",
     "    dealer_sign = (1 if dev_bps >= 0 else -1)"),
    ("M15 gate tieout disabled", PP,
     "    if tie > TIEOUT_MAX_BPS:",
     "    if tie > 1e18:"),
    ("M16 gate dv01 halving dropped", PP,
     '    dv01 = float(np.nansum(sub["dv01"].to_numpy())) / 2.0',
     '    dv01 = float(np.nansum(sub["dv01"].to_numpy()))'),
    ("M17 gate OPA-missing check dropped", PP,
     '    if sub["opa"].isna().any():',
     '    if False and sub["opa"].isna().any():'),
    ("M18 unresolved_pv01 accumulates the wrong quantity", PP,
     "            unresolved += p",
     "            unresolved += abs(fi)"),
    ("M19 greedy flag never fires", PP,
     "    if not cash.exact:",
     "    if False and not cash.exact:"),
    ("M20 CashSigns.exact always true", PP,
     "                     exact=len(vals) <= EXACT_SOLVE_MAX_LEGS)",
     "                     exact=True)"),
    ("M21 OPA-missing gate dropped in classify", PP,
     "    if any(_num(o) is None for o in opas):",
     "    if False and any(_num(o) is None for o in opas):"),
    ("M22 UFRO disagree ratio inverted", PP,
     "            if lo > 0 and hi / lo > PTP_UFRO_DISAGREE_RATIO:",
     "            if lo > 0 and hi / lo < PTP_UFRO_DISAGREE_RATIO:"),
    ("M23 unresolved uses the resolution as a dollar bound", PP,
     "        if p > 0 and abs(fi) / p < float(leg_sign_resolution_bps):",
     "        if p > 0 and abs(fi) < float(leg_sign_resolution_bps):"),
    ("M24 universe routes EVERY pkg4 in", UNI,
     '        EXCL_UNORIENTABLE: u["excluded_type"] | (pkg4 & ~recoverable),',
     '        EXCL_UNORIENTABLE: u["excluded_type"],'),
    ("M25 universe recovers nothing", UNI,
     '        EXCL_UNORIENTABLE: u["excluded_type"] | (pkg4 & ~recoverable),',
     '        EXCL_UNORIENTABLE: u["excluded_type"] | pkg4,'),
    ("M26 universe pkg4 threshold off by one", UNI,
     '    pkg4 = u["n_legs"] >= 4',
     '    pkg4 = u["n_legs"] >= 5'),
]


def run_suite() -> tuple[int, str]:
    p = subprocess.run(
        [PY, "-m", "pytest", *TESTS, "-q", "-p", "no:cacheprovider",
         "--no-header", "-x", "--tb=no"],
        cwd=ROOT, capture_output=True, text=True)
    tail = [ln for ln in p.stdout.splitlines() if "passed" in ln or "failed" in ln
            or "error" in ln.lower()]
    return p.returncode, (tail[-1] if tail else p.stdout.strip()[-200:])


def main() -> int:
    orig = {PP: PP.read_bytes(), UNI: UNI.read_bytes()}
    digest = {k: hashlib.sha256(v).hexdigest() for k, v in orig.items()}
    rc, line = run_suite()
    print(f"BASELINE rc={rc}  {line}")
    if rc != 0:
        print("baseline is not green; aborting")
        return 1
    survivors = []
    try:
        for name, path, old, new in MUTANTS:
            src = orig[path].decode()
            if src.count(old) != 1:
                print(f"{name:52s} SKIP  (anchor appears {src.count(old)}x)")
                continue
            path.write_bytes(src.replace(old, new).encode())
            rc, line = run_suite()
            verdict = "RED  " if rc != 0 else "SURVIVED"
            if rc == 0:
                survivors.append(name)
            print(f"{name:52s} {verdict}  {line}")
            path.write_bytes(orig[path])
    finally:
        for k, v in orig.items():
            k.write_bytes(v)
        for k, v in digest.items():
            now = hashlib.sha256(k.read_bytes()).hexdigest()
            print(f"RESTORED {k.name}: {'OK' if now == v else 'MISMATCH'}")
    print()
    print(f"SURVIVORS ({len(survivors)}): " + ("; ".join(survivors) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
