"""Mutation harness for ``package_price`` AFTER the D1-D5 fixes.

Supersedes ``scratch/rev_pp_mutate.py``, whose anchors no longer match: five of
its mutants would print SKIP against the fixed file, which is a clean-looking
survivors list that tested nothing. Every anchor here is asserted to appear
exactly once before the run starts, and a run with any SKIP is a failed run.

Mutates in place, runs the two suites, restores the original bytes and checks
the sha256 round-trips. Nothing is committed.

    C:/Users/chris/anaconda3/envs/stir/python.exe scratch/ppfix_mutate.py
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(r"C:\Users\chris\clee\ARBS-dd")
PP = ROOT / "SDRUtils" / "dealer_direction" / "package_price.py"
UNI = ROOT / "SDRUtils" / "dealer_direction" / "universe.py"
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
LF = chr(10)
CRLF = chr(13) + chr(10)

TESTS = ["tests/test_dealer_direction_package_price.py",
         "tests/test_dealer_direction_universe.py"]

MUTANTS = [
    # --- the original 26, re-anchored where the fix moved the line ----------
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
     "    if is_lifecycle:\n        dealer_sign = -dealer_sign",
     "    if False and is_lifecycle:\n        dealer_sign = -dealer_sign"),
    ("M06 near-mid comparison inverted", PP,
     "        if p > 0 and abs(fi) / p < float(leg_sign_resolution_bps):",
     "        if p > 0 and abs(fi) / p > float(leg_sign_resolution_bps):"),
    ("M07 tieout gate disabled", PP,
     "    if tieout_bps > float(tieout_max_bps) or cash.net == 0.0:",
     "    if tieout_bps > 1e18 * float(tieout_max_bps) or cash.net == 0.0:"),
    ("M08 net==0 guard dropped (classify)", PP,
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
     "    if tie > TIEOUT_MAX_BPS or cash.net == 0.0:",
     "    if tie > 1e18 or cash.net == 0.0:"),
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
     "                     exact=len(vals) <= EXACT_SOLVE_MAX_LEGS,",
     "                     exact=True,"),
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

    # --- one per fix landed this session ------------------------------------
    ("D1 lifecycle negation moved back to received_signs", PP,
     "    dealer_sign = conventions.dealer_side(dev_bps)\n"
     "    if is_lifecycle:\n"
     "        dealer_sign = -dealer_sign\n"
     "    received = None\n"
     "    if dealer_sign != 0:\n"
     "        received = tuple(dealer_sign * oi for oi in o)",
     "    dealer_sign = conventions.dealer_side(dev_bps)\n"
     "    received = None\n"
     "    if dealer_sign != 0:\n"
     "        received = tuple(dealer_sign * oi for oi in o)\n"
     "        if is_lifecycle:\n"
     "            received = tuple(-r for r in received)"),
    ("D2 identification gate disabled (classify)", PP,
     "    if not (tieout_bps + margin_bps > float(tieout_max_bps)):",
     "    if False and not (tieout_bps + margin_bps > float(tieout_max_bps)):"),
    ("D2 identification gate disabled (tape_gate)", PP,
     "    if not (tie + margin > TIEOUT_MAX_BPS):",
     "    if False and not (tie + margin > TIEOUT_MAX_BPS):"),
    ("D2 margin ignores the global complement (2^n not 2^(n-1))", PP,
     "    nets = np.array([vals[0]], dtype=float)\n    for v in vals[1:]:",
     "    nets = np.array([0.0], dtype=float)\n    for v in vals:"),
    ("D2 margin returns the runner-up instead of the gap", PP,
     "    return float(max(two.max() - two.min(), 0.0))",
     "    return float(two.max())"),
    ("D2 one-leg unit gets a zero margin, not an infinite one", PP,
     '    if n == 1:\n        return float("inf")',
     '    if n == 1:\n        return 0.0'),
    ("D2 over-cap margin returns inf (accept) not nan (refuse)", PP,
     '    if n > MARGIN_MAX_LEGS:\n        return float("nan")',
     '    if n > MARGIN_MAX_LEGS:\n        return float("inf")'),
    ("D4 gate net==0 guard dropped", PP,
     "    if tie > TIEOUT_MAX_BPS or cash.net == 0.0:",
     "    if tie > TIEOUT_MAX_BPS:"),
    ("D4 gate non-finite fee guard dropped", PP,
     "    return v.where(np.isfinite(v.to_numpy(dtype=float)))",
     "    return v"),
    ("D4 classify stratum order reverted (PRICING_ERROR first)", PP,
     "    ptp = _num(package_price)\n"
     "    if ptp is None or abs(ptp) <= PTP_USD_FLOOR:\n"
     "        return refuse(EXCL_NO_PACKAGE_PRICE)\n"
     "\n"
     "    if any(_num(o) is None for o in opas):\n"
     "        return refuse(EXCL_OPA_MISSING)\n"
     "\n"
     "    dv01 = _num(structure_dv01)\n"
     "    if dv01 is None or dv01 <= 0:\n"
     "        return refuse(EXCL_PRICING_ERROR)",
     "    dv01 = _num(structure_dv01)\n"
     "    if dv01 is None or dv01 <= 0:\n"
     "        return refuse(EXCL_PRICING_ERROR)\n"
     "\n"
     "    ptp = _num(package_price)\n"
     "    if ptp is None or abs(ptp) <= PTP_USD_FLOOR:\n"
     "        return refuse(EXCL_NO_PACKAGE_PRICE)\n"
     "\n"
     "    if any(_num(o) is None for o in opas):\n"
     "        return refuse(EXCL_OPA_MISSING)"),
    ("D5 exact-solve cap hand-copied again", PP,
     "EXACT_SOLVE_MAX_LEGS = _MAX_BRUTE_N",
     "EXACT_SOLVE_MAX_LEGS = 24 + 1"),
    ("D5 ambiguous dropped from STRATA", PP,
     "STRATA = (EXCL_NO_PACKAGE_PRICE, EXCL_OPA_MISSING, EXCL_PRICING_ERROR,\n"
     "          EXCL_TIEOUT_FAIL, EXCL_SIGNS_AMBIGUOUS, EXCL_LEG_AT_MID)",
     "STRATA = (EXCL_NO_PACKAGE_PRICE, EXCL_OPA_MISSING, EXCL_PRICING_ERROR,\n"
     "          EXCL_TIEOUT_FAIL, EXCL_LEG_AT_MID)"),
]


def run_suite() -> tuple:
    env = dict(os.environ)
    env.update({"ARBS_SUPABASE_ENABLED": "0", "TMP": r"D:\ddfix3\tmp",
                "TEMP": r"D:\ddfix3\tmp",
                "PYTHONPYCACHEPREFIX": r"D:\ddfix3\pyc"})
    p = subprocess.run(
        [PY, "-m", "pytest", *TESTS, "-q", "-p", "no:cacheprovider",
         "--no-header", "-x", "--tb=no"],
        cwd=ROOT, capture_output=True, text=True, env=env)
    tail = [ln for ln in p.stdout.splitlines()
            if "passed" in ln or "failed" in ln or "error" in ln.lower()]
    return p.returncode, (tail[-1] if tail else p.stdout.strip()[-200:])


def main() -> int:
    orig = {PP: PP.read_bytes(), UNI: UNI.read_bytes()}
    digest = {k: hashlib.sha256(v).hexdigest() for k, v in orig.items()}

    # The tree is CRLF on disk (git autocrlf). Match and mutate on an
    # LF-normalised copy and write the file back in its own convention, or
    # every multi-line anchor silently misses and the mutant tests nothing.
    norm = {k: v.decode().replace(CRLF, LF) for k, v in orig.items()}

    bad = []
    for name, path, old, _new in MUTANTS:
        n = norm[path].count(old)
        if n != 1:
            bad.append(f"{name}: anchor appears {n}x")
    if bad:
        print("ANCHORS DO NOT MATCH -- a SKIP is a mutant that tested nothing:")
        print("\n".join("  " + b for b in bad))
        return 1

    rc, line = run_suite()
    print(f"BASELINE rc={rc}  {line}")
    if rc != 0:
        print("baseline is not green; aborting")
        return 1
    survivors = []
    try:
        for name, path, old, new in MUTANTS:
            src = norm[path].replace(old, new)
            path.write_bytes(src.replace(LF, CRLF).encode())
            rc, line = run_suite()
            if rc == 0:
                survivors.append(name)
            print(f"{name:<58s} {'RED  ' if rc else 'SURVIVED'}  {line}",
                  flush=True)
            path.write_bytes(orig[path])
    finally:
        for k, v in orig.items():
            k.write_bytes(v)
        for k, v in digest.items():
            now = hashlib.sha256(k.read_bytes()).hexdigest()
            print(f"RESTORED {k.name}: {'OK' if now == v else 'MISMATCH'}")
    print()
    print(f"SURVIVORS ({len(survivors)}/{len(MUTANTS)}): "
          + ("; ".join(survivors) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
