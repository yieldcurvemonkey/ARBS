"""Second battery: what do the CONSTANT-vs-CONSTANT tests actually catch?

Review item 3 said ``test_headline_shares_sit_inside_the_quoted_sensitivity_band``
and friends "compare module constants to module constants; they pin a story,
they measure nothing". The fix added
``test_the_headline_satisfies_its_own_model_free_cross_check``. Three probes:

  H1/H2  hand-edit a headline constant -> is transcription caught?
  H3     move the FIT (one shipped multiplier) and leave the headline
         constants alone -> does anything tie the headline to the table?
"""
from __future__ import annotations

import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"

MUTANTS = [
    ("H1 EFFECTIVE_MULTIPLIER 2.3664 -> 2.50 (hand-edited constant)",
     "EFFECTIVE_MULTIPLIER = 2.3664", "EFFECTIVE_MULTIPLIER = 2.50"),
    ("H2 IMPUTED_DV01_SHARE 0.1597 -> 0.30 (outside its own band)",
     "IMPUTED_DV01_SHARE = 0.1597", "IMPUTED_DV01_SHARE = 0.30"),
    ("H3 shipped multiplier V1 5y-10y 4.2176 -> 3.0, headline untouched",
     "multiplier=4.217577034379514", "multiplier=3.0000000000000000"),
    ("H4 IMPUTED_SHARE_BY_BUCKET '2-10y' dv01 0.1749 -> 0.1600",
     '"2-10y": (0.1565, 0.1749),', '"2-10y": (0.1565, 0.1600),'),
]

for label, old, new in MUTANTS:
    env = dict(os.environ, ARBS_SUPABASE_ENABLED="0",
               ARBS_VIMP_MUT=json.dumps([old, new]),
               PYTHONPATH=HERE + os.pathsep + ROOT)
    r = subprocess.run(
        [PY, "-m", "pytest", "tests/test_dealer_direction_imputation.py", "-q",
         "--no-header", "-p", "no:cacheprovider", "-p", "vimp_mutplug"],
        capture_output=True, text=True, cwd=ROOT, env=env)
    assert "[vimp] imputation loaded from" in r.stderr, r.stderr[-600:]
    tail = [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l]
    killers = sorted({l.split("::")[1].split(" ")[0]
                      for l in r.stdout.splitlines() if l.startswith("FAILED")})
    print(f"{'GREEN (survives)' if r.returncode == 0 else 'red (killed)':17s} {label}")
    print(f"{'':17s}   {tail[-1] if tail else ''}")
    if killers:
        print(f"{'':17s}   killed by: {', '.join(killers)}")
