"""Re-run the review's five silent-degradation probes, one exception boundary
each. ``rev_imp_probes.py`` runs them in one script and stops at the first
raise -- and after the fix, raising IS the correct behaviour for three of them,
so the script's own traceback would hide the other probes.
"""
from __future__ import annotations

import os
import sys
import traceback
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
from scipy import optimize

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from SDRUtils.dealer_direction import imputation as imp  # noqa: E402


def probe(n, title, fn):
    print(f"\n=== {n}. {title}")
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fn()
        for w in caught:
            print(f"  WARNING {w.category.__name__}: {str(w.message)[:220]}")
    except Exception as e:                                  # noqa: BLE001
        print(f"  RAISES {type(e).__name__}: {str(e)[:260]}")


def p1():
    freq = pd.DataFrame({
        "vintage": ["V1"] * 6, "lo": [0.0] * 6, "cap": [1e9] * 6,
        "notional": [3e8, 4e8, 5e8, 6e8, 7e8, 1e9],
        "is_capped": [False] * 5 + [True], "n": [3, 3, 3, 3, 3, 40]})
    out = imp.fit_frequency_table(freq)
    print(f"  returned {type(out).__name__} of len {len(out)}; NO exception")


def p2():
    rng = np.random.default_rng(0)
    z = np.exp(rng.normal(19.0, 1.5, 60_000))
    sub = z[(z >= 2.5e8) & (z < 1e9)]
    vals, cnts = np.unique(np.round(sub / 1e6) * 1e6, return_counts=True)
    freq2 = pd.DataFrame({
        "vintage": "V1", "lo": 0.0, "cap": 1e9,
        "notional": list(vals) + [1_000_000_001.0],
        "is_capped": [False] * len(vals) + [True],
        "n": list(cnts.astype(float)) + [900.0]})
    fits = imp.fit_frequency_table(freq2)
    f = fits[("V1", 0.0)]
    print(f"  n_cap = {f.n_cap}, multiplier still produced = {f.multiplier:.4f}")
    print(f"  capped_count_error = {f.capped_count_error}")


def p3():
    calls = {"n": 0, "fail": 0}
    real = optimize.minimize

    def spy(*a, **k):
        r = real(*a, **k)
        calls["n"] += 1
        calls["fail"] += (not r.success)
        return r
    imp.optimize.minimize = spy
    try:
        f = pd.read_csv(os.path.join(HERE, "partB_freq_cache.csv")).dropna(
            subset=["cell"])
        m = f["cell"].str.split("|", expand=True)
        f["vintage"], f["lo"], f["cap"] = m[0], m[1].astype(float), m[3].astype(float)
        imp.fit_frequency_table(f[["vintage", "lo", "cap", "notional",
                                   "is_capped", "n"]])
    finally:
        imp.optimize.minimize = real
    print(f"  Nelder-Mead runs {calls['n']}, non-converged {calls['fail']}")
    print("  -- the shipped calibration still contains non-converged RESTARTS; "
          "the question is whether the SELECTED optimum may be one.")

    # the selected-optimum question, directly: force every run to report failure
    def never(*a, **k):
        r = real(*a, **k)
        r.success = False
        return r
    imp.optimize.minimize = never
    try:
        imp.lognormal_censored_mle(np.array([2e8, 3e8, 4e8, 5e8, 6e8]),
                                   np.ones(5), 1e8, 1e9, 50.0)
        print("  censored MLE returned a number with success=False everywhere")
    except RuntimeError as e:
        print(f"  censored MLE RAISES RuntimeError: {str(e)[:150]}")
    finally:
        imp.optimize.minimize = real


def p4():
    s = imp.impute(250e6, "2025-05-01", is_capped=False)
    fr = imp.impute_frame(pd.DataFrame({
        "notional": [250e6], "as_of_date": ["2025-05-01"], "is_capped": [False]}))
    print(f"  scalar factor = {s.notional_impute_factor!r}")
    print(f"  frame  factor = {fr.loc[0, 'notional_impute_factor']!r}")
    print(f"  frame columns = {[c for c in fr.columns]}")
    print(f"  'notional_expected' present: {'notional_expected' in fr.columns}")
    for bad in (None, float('nan')):
        try:
            imp.apply_to_signed_krd({"5Y": 1.0}, bad)
            print(f"  apply_to_signed_krd({bad!r}) ACCEPTED")
        except Exception as e:                              # noqa: BLE001
            print(f"  apply_to_signed_krd({bad!r}) -> {type(e).__name__}")


def p5():
    print("  ", imp.weighted_ks([1.0, 2.0], [0.0, 0.0], lambda q: np.zeros_like(q)))


probe(1, "fit_frequency_table on a table where no cell is fittable", p1)
probe(2, "a cell whose capped prints all sit OFF the exact cap value", p2)
probe(3, "does _ln_mle check convergence?", p3)
probe(4, "impute() vs impute_frame(): None or NaN, and the column name", p4)
probe(5, "weighted_ks on zero total weight", p5)
