"""Mutation test. A suite that passes on broken code is not a suite.

Each mutation is a defect that would produce a complete, plausible, monotone
`p` -- i.e. exactly the class of error nothing downstream could detect.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "SDRUtils", "dealer_direction", "probability.py")
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"

MUTATIONS = [
    ("tau := h  (the brief's reading of tau)",
     "return float(self.s) ** 2 / (2.0 * h)",
     "return h"),
    ("mid bias sign flipped in p",
     "z = (x - fit.b0) / fit.tau",
     "z = (x + fit.b0) / fit.tau"),
    ("moment closed form takes the WRONG root",
     "s2 = m2 - math.sqrt(disc)",
     "s2 = m2 + math.sqrt(disc)"),
    ("signed_weight := p  (half a long at a coin flip)",
     "signed_weight=conv.signed_weight(p),",
     "signed_weight=float(p),"),
    ("quantile trim instead of a robust-scale trim",
     "return np.isfinite(x) & (np.abs(x - float(np.median(x))) <= k * scale)",
     "lo, hi = np.quantile(x[np.isfinite(x)], [0.05, 0.95]); "
     "return np.isfinite(x) & (x >= lo) & (x <= hi)"),
    ("dead zone measured in bp not probability",
     "in_dead_zone=abs(p - 0.5) < delta,",
     "in_dead_zone=abs(float(deviation_bps)) < 0.05,"),
    ("EM drops the (1 - ubar^2) denominator",
     "h_new = (float((u * x).mean()) - xbar * ubar) / denom",
     "h_new = float((u * x).mean()) - xbar * ubar"),
]

original = io.open(SRC, encoding="utf-8").read()
env = dict(os.environ, ARBS_SUPABASE_ENABLED="0")
results = []
try:
    for name, old, new in MUTATIONS:
        if original.count(old) != 1:
            results.append((name, f"SKIP anchor appears {original.count(old)}x"))
            continue
        io.open(SRC, "w", encoding="utf-8").write(original.replace(old, new))
        p = subprocess.run(
            [PY, "-m", "pytest", "tests/test_dealer_direction_probability.py",
             "-x", "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=2400)
        tail = [ln for ln in p.stdout.splitlines() if ln.startswith("FAILED")]
        results.append((name, "CAUGHT by " + (tail[0][7:] if tail else "?")
                        if p.returncode else "*** SURVIVED ***"))
        print(f"{results[-1][1][:110]:112s} <- {name}")
finally:
    io.open(SRC, "w", encoding="utf-8").write(original)
    print("\nrestored:", io.open(SRC, encoding="utf-8").read() == original)

survived = [n for n, r in results if "SURVIVED" in r or "SKIP" in r]
print(f"\n{len(results) - len(survived)}/{len(results)} mutations caught")
sys.exit(1 if survived else 0)
