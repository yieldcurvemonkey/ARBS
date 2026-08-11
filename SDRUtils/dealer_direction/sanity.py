"""Is this leg's ``risk`` a number that follows from its own notional and tenor?

WHY THIS IS NOT A "DROP THE CORRUPT ROWS" MODULE
------------------------------------------------

55 legs on the v3 tape carry ``notional = 1e20`` exactly and 54 of those also
carry ``fixed_rate = 9.9`` (=990%). It is tempting to read that as corruption.
It is not. Field #31 in the Part 43/45 technical specification is ``Num(25,5)``
and footnote 42 states that ``'99999999999999999999.99999'`` is accepted "when
the value is not available at the time of reporting". ``9.9`` is the same idea
for the rate. **These are the spec's own not-available sentinels**, so the row
is a placeholder print whose real economics are supposed to arrive in a later
``CORR`` or ``MODI`` — and the tape ingests ``NEWT`` only, so they never do.

That changes the right treatment. "Corrupt, drop" implies a data defect
somebody could fix; the truth is that these 55 prints are *economically
unknowable from this tape* and will stay that way. They are excluded, counted,
and named — never repaired, never imputed, and never summed into an aggregate:
``sum(abs(risk))`` over flow legs is 1.425e17, of which **99.99994% is these 55
rows**, and the totals reproduce exactly as single platforms (BILT for
FED_FUNDS, XXXX for SOFR) which is why the platform breakdown once looked like
two bad venues.

WHY THE OBVIOUS BOUND DOES NOT WORK
-----------------------------------

The suggested test — ``|risk|/notional ~= tenor * 1e-4`` within a factor of two
— **catches 0 of the 55**. Their scaled ratio is 1.004-1.006, because ``risk``
was computed *correctly from* the sentinel notional. Worse, it mis-flags 58.1%
of deep forward-start legs, since ``tenor * 1e-4`` is not the DV01 scale when
37% of flow legs start forward. Two corrections, both measured:

1. **DV01 per unit notional is an annuity, not a tenor.** Using
   ``E = N * (A(f+T) - A(f)) * 1e-4`` with ``A(x) = (1 - exp(-0.04 x)) / 0.04``
   the median ratio is flat at 1.00 in every tenor band
   (1.009 / 1.000 / 0.999 / 1.006 / 1.003 / 1.001 from <6m to >25y) instead of
   sliding from 1.00 to 0.59. That flatness is the evidence the shape is right.
   Against the same populations the annuity bound flags 0.000% of deep
   forward-starts and 0.005% of >25y legs.
2. **``risk`` is quantised to $100.** All 2,289,189 non-null flow values are
   integer multiples of 100 and the smallest non-zero value is exactly 100, so
   a $2mm three-month print whose true DV01 is ~$50 is stored as 100 and a
   purely multiplicative band flags it. With the additive :data:`RISK_QUANTUM`
   allowance, rows above the upper band go from 253 to **0**.

The sentinels are therefore caught by an absolute bound on the *inputs*, not by
a ratio test: the largest legitimate notional measured anywhere on the tape is
2.86e10, so :data:`NOTIONAL_ABS_MAX` at 1e11 sits 3.5x above real data and nine
orders of magnitude below the sentinel.

WHAT THE RATIO CODES DO AND DO NOT MEAN
---------------------------------------

Only ``NOTIONAL_SENTINEL`` and ``RATE_SENTINEL`` are corruption in the strict
sense. The ratio codes say "this row's risk does not follow from its own
notional and tenor" — exclude it from an aggregate, but do not read them as
proof of which field is wrong. The ``RISK_VS_NOTIONAL_LOW`` band (4,875 flow
legs, 0.21%) is still unexplained: the obvious candidate, an amortising
schedule inflating the flat-annuity ``E``, was tested and **rejected** — only
220 of the 4,875 carry a non-Constant ``upi_notional_schedule``, and the
residual concentrates at 2-10y (0.41% / 0.29% / 0.20%) with literally zero
below 2y.

Validate against prod (read-only; exits non-zero on failure)::

    ARBS_SUPABASE_ENABLED=0 python -m SDRUtils.dealer_direction.sanity --validate
"""
from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "BAND_HI",
    "BAND_LO",
    "FLAT_YIELD",
    "NOTIONAL_ABS_MAX",
    "RATE_ABS_MAX",
    "REASONS",
    "RISK_QUANTUM",
    "annuity",
    "expected_dv01",
    "flag_risk_implausible",
    "implausibility_reason",
    "is_risk_implausible",
    "synthetic_cases",
]

# --- calibration constants, every one of them measured ---------------------
#: Flat continuous yield behind the annuity approximation. Deliberately crude:
#: this is a plausibility scale, not a pricer.
FLAT_YIELD = 0.04
#: Largest legitimate notional measured on the tape is 2.86e10 (a $28.6bn 1.5y
#: print on 2024-03-11); the sentinel is 1e20. Anywhere in between works.
NOTIONAL_ABS_MAX = 1e11
#: ``fixed_rate`` is a decimal fraction (flow median 0.0394). 1,465 flow legs
#: carry |rate| >= 1.0, ranging -40.05 to 785.5.
RATE_ABS_MAX = 1.0
#: Every non-null ``risk`` on the tape is an integer multiple of 100.
RISK_QUANTUM = 100.0
BAND_LO = 0.5
BAND_HI = 2.0

REASONS = (
    "NOTIONAL_SENTINEL",
    "RATE_SENTINEL",
    "RISK_NULL",
    "RISK_ZERO_MATERIAL",
    "RISK_VS_NOTIONAL_LOW",
    "RISK_VS_NOTIONAL_HIGH",
    "INPUTS_MISSING",
)


def annuity(years, flat_yield: float = FLAT_YIELD):
    """``A(x) = (1 - exp(-y x)) / y``, the continuous-discount annuity factor."""
    x = np.asarray(years, dtype=float)
    if flat_yield == 0.0:
        return x
    return (1.0 - np.exp(-flat_yield * x)) / flat_yield


def expected_dv01(
    notional,
    tenor_years,
    forward_start_years=None,
    flat_yield: float = FLAT_YIELD,
):
    """Order-of-magnitude DV01 for a forward-starting swap, in currency units.

    The *difference* of two annuities, not one annuity of the tenor — that is
    the whole correction, and it is what makes the ratio flat across tenor
    bands instead of sliding to 0.59 at the long end.
    """
    n = np.asarray(notional, dtype=float)
    t = np.asarray(tenor_years, dtype=float)
    f = (
        np.zeros_like(t)
        if forward_start_years is None
        else np.nan_to_num(np.asarray(forward_start_years, dtype=float), nan=0.0)
    )
    f = np.where(f < 0, 0.0, f)
    return n * (annuity(f + t, flat_yield) - annuity(f, flat_yield)) * 1e-4


def flag_risk_implausible(
    df: pd.DataFrame,
    *,
    notional_col: str = "notional",
    tenor_col: str = "tenor_years",
    risk_col: str = "risk",
    forward_col: str = "forward_start_years",
    rate_col: str = "fixed_rate",
    flat_yield: float = FLAT_YIELD,
    band_lo: float = BAND_LO,
    band_hi: float = BAND_HI,
    quantum: float = RISK_QUANTUM,
) -> pd.DataFrame:
    """Per-reason booleans aligned to ``df.index``.

    Columns: ``exp_dv01``, ``risk_ratio``, one bool per code in
    :data:`REASONS`, ``reason`` (comma-joined, empty when clean) and
    ``is_risk_implausible``.
    """
    n = pd.to_numeric(df[notional_col], errors="coerce").to_numpy(dtype=float)
    t = pd.to_numeric(df[tenor_col], errors="coerce").to_numpy(dtype=float)
    r = pd.to_numeric(df[risk_col], errors="coerce").to_numpy(dtype=float)
    f = (
        pd.to_numeric(df[forward_col], errors="coerce").to_numpy(dtype=float)
        if forward_col in df.columns
        else np.zeros_like(t)
    )
    rate = (
        pd.to_numeric(df[rate_col], errors="coerce").to_numpy(dtype=float)
        if rate_col in df.columns
        else np.full_like(t, np.nan)
    )

    with np.errstate(invalid="ignore", divide="ignore"):
        exp = expected_dv01(n, t, f, flat_yield=flat_yield)
        ratio = np.where(exp > 0, np.abs(r) / exp, np.nan)

    inputs_ok = np.isfinite(n) & np.isfinite(t) & (n > 0) & (t > 0) & (exp > 0)
    risk_null = ~np.isfinite(r)
    testable = inputs_ok & ~risk_null

    out = pd.DataFrame(index=df.index)
    out["exp_dv01"] = exp
    out["risk_ratio"] = ratio

    out["NOTIONAL_SENTINEL"] = np.isfinite(n) & (np.abs(n) >= NOTIONAL_ABS_MAX)
    out["RATE_SENTINEL"] = np.isfinite(rate) & (np.abs(rate) >= RATE_ABS_MAX)
    out["RISK_NULL"] = risk_null
    out["RISK_ZERO_MATERIAL"] = testable & (r == 0.0) & (exp > 3.0 * quantum)
    out["RISK_VS_NOTIONAL_LOW"] = (
        testable & (r != 0.0) & (np.abs(r) < band_lo * exp - quantum)
    )
    out["RISK_VS_NOTIONAL_HIGH"] = testable & (np.abs(r) > band_hi * exp + quantum)
    out["INPUTS_MISSING"] = ~inputs_ok

    bools = out[list(REASONS)].to_numpy(dtype=bool)
    out["is_risk_implausible"] = bools.any(axis=1)
    cols = np.array(REASONS, dtype=object)
    out["reason"] = [",".join(cols[row]) for row in bools]
    return out


def is_risk_implausible(df: pd.DataFrame, **kw) -> pd.Series:
    """Boolean Series convenience wrapper over :func:`flag_risk_implausible`."""
    return flag_risk_implausible(df, **kw)["is_risk_implausible"]


def implausibility_reason(
    *,
    notional=None,
    tenor_years=None,
    forward_start_years=None,
    fixed_rate=None,
    risk=None,
    **kw,
) -> str | None:
    """The predicate, for one leg: a comma-joined reason string, or ``None``.

    Keyword-only because the argument order is not memorable and a positional
    swap of ``notional`` and ``risk`` would silently pass — the ratio test is
    symmetric enough that a transposed pair still lands inside some band.

    Same code path as :func:`flag_risk_implausible`, so the two can never
    disagree; a test asserts that on the synthetic set.
    """
    row = pd.DataFrame([{
        "notional": notional,
        "tenor_years": tenor_years,
        "forward_start_years": forward_start_years,
        "fixed_rate": fixed_rate,
        "risk": risk,
    }])
    reason = flag_risk_implausible(row, **kw)["reason"].iloc[0]
    return reason or None


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def synthetic_cases() -> tuple[pd.DataFrame, list[str]]:
    """Rows whose right answer is known before the predicate is run.

    Public because the pytest suite reuses them: a harness that only runs
    against prod is a harness that does not run.
    """
    rows = [
        # (label, notional, tenor, fwd, rate, risk, expected reason)
        ("clean 5y $100mm",        1e8,  5.0,  0.0, 0.0395,  45_300, ""),
        ("clean 30y $50mm",        5e7, 30.0,  0.0, 0.0410,  87_400, ""),
        ("clean 20y5y fwd $100mm", 1e8,  5.0, 20.0, 0.0400,  20_400, ""),
        ("tiny 3m $2mm risk=100",  2e6, 0.25,  0.0, 0.0366,     100, ""),
        ("risk=0, sub-quantum",    5e4,  5.0,  0.0, 0.0395,       0, ""),
        ("BILT sentinel",          1e20, 0.397, 0.0,   9.9, 3.96072e15,
         "NOTIONAL_SENTINEL,RATE_SENTINEL"),
        ("XXXX sentinel",          1e20, 2.748, 0.208, 0.035905, 2.58996e16,
         "NOTIONAL_SENTINEL"),
        ("risk 10x too big",       1e8,  5.0,  0.0, 0.0395, 453_000,
         "RISK_VS_NOTIONAL_HIGH"),
        ("risk 10x too small",     1e8,  5.0,  0.0, 0.0395,   4_500,
         "RISK_VS_NOTIONAL_LOW"),
        ("risk=0 but material",    1e8,  5.0,  0.0, 0.0395,       0,
         "RISK_ZERO_MATERIAL"),
        ("risk NULL",              1e8,  5.0,  0.0, 0.0395, np.nan, "RISK_NULL"),
        ("notional NULL",       np.nan,  5.0,  0.0, 0.0395,  45_300, "INPUTS_MISSING"),
        # naive-bound trap: the annuity-aware formula must NOT flag these
        ("30y5y fwd $500mm",       5e8,  5.0, 30.0, 0.0400,  67_000, ""),
        ("40y $100mm",             1e8, 40.0,  0.0, 0.0420, 202_000, ""),
    ]
    df = pd.DataFrame(
        [
            {
                "label": lb, "notional": n, "tenor_years": t,
                "forward_start_years": f, "fixed_rate": rt, "risk": rk,
            }
            for lb, n, t, f, rt, rk, _ in rows
        ]
    )
    return df, [r[-1] for r in rows]


def _validate() -> int:
    import os
    import sys

    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

    pd.set_option("display.width", 240)
    pd.set_option("display.max_columns", 40)
    failures: list[str] = []

    # ---- 1. synthetic cases with known answers ---------------------------
    print("=" * 72)
    print("1. SYNTHETIC CASES (answer known before the predicate runs)")
    print("=" * 72)
    syn, want = synthetic_cases()
    got = flag_risk_implausible(syn)
    tbl = pd.DataFrame(
        {
            "label": syn["label"],
            "exp_dv01": got["exp_dv01"].round(0),
            "ratio": got["risk_ratio"].round(3),
            "expected": want,
            "got": got["reason"],
        }
    )
    tbl["ok"] = tbl["expected"] == tbl["got"]
    print(tbl.to_string(index=False))
    if not tbl["ok"].all():
        failures.append(f"synthetic: {(~tbl['ok']).sum()} case(s) mismatched")

    # ---- 2. mutation test: does the check actually bite? -----------------
    print()
    print("=" * 72)
    print("2. MUTATION TEST (break a clean row, the predicate must notice)")
    print("=" * 72)
    clean = syn.iloc[[0]].copy()
    muts = {
        "risk *= 1e12":     ("risk", clean["risk"].iloc[0] * 1e12, "RISK_VS_NOTIONAL_HIGH"),
        "risk /= 1e3":      ("risk", clean["risk"].iloc[0] / 1e3, "RISK_VS_NOTIONAL_LOW"),
        "notional = 1e20":  ("notional", 1e20, "NOTIONAL_SENTINEL"),
        "fixed_rate = 9.9": ("fixed_rate", 9.9, "RATE_SENTINEL"),
        "notional = 0":     ("notional", 0.0, "INPUTS_MISSING"),
    }
    for name, (col, val, expect) in muts.items():
        m = clean.copy()
        m[col] = val
        got_reason = flag_risk_implausible(m)["reason"].iloc[0]
        ok = expect in got_reason.split(",")
        print(f"  {name:<20} -> {got_reason or '(clean)':<40} {'OK' if ok else 'FAIL'}")
        if not ok:
            failures.append(f"mutation {name}: expected {expect}, got '{got_reason}'")

    # ---- 3. the scalar predicate is the same predicate -------------------
    print()
    print("=" * 72)
    print("3. SCALAR vs VECTORISED (one predicate, two call shapes)")
    print("=" * 72)
    scalar = [
        implausibility_reason(
            notional=r.notional, tenor_years=r.tenor_years,
            forward_start_years=r.forward_start_years,
            fixed_rate=r.fixed_rate, risk=r.risk) or ""
        for r in syn.itertuples()
    ]
    n_bad = sum(a != b for a, b in zip(scalar, want))
    print(f"  {len(syn) - n_bad}/{len(syn)} agree")
    if n_bad:
        failures.append(f"scalar/vector disagree on {n_bad} synthetic case(s)")

    # ---- 4. live tape ----------------------------------------------------
    import warnings

    import psycopg2

    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    conn = psycopg2.connect(resolve_pg_url())

    def q(sql):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return pd.read_sql(sql, conn)

    COLS = ("trade_id, as_of_date, notional, tenor_years, forward_start_years, "
            "fixed_rate, risk, platform_identifier, rate_index_clean, "
            "quality_flags::text quality_flags")
    FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"

    print()
    print("=" * 72)
    print("4a. KNOWN-BROKEN: the 55 rows with notional = 1e20")
    print("=" * 72)
    bad = q(f"SELECT {COLS} FROM {LEGS_TABLE} WHERE notional >= 1e11")
    fb = flag_risk_implausible(bad)
    print(f"  rows                     : {len(bad)}")
    print(f"  flagged implausible      : {int(fb['is_risk_implausible'].sum())} "
          f"({fb['is_risk_implausible'].mean():.1%})")
    print(f"  NOTIONAL_SENTINEL        : {int(fb['NOTIONAL_SENTINEL'].sum())}")
    print(f"  RATE_SENTINEL            : {int(fb['RATE_SENTINEL'].sum())}")
    print(f"  caught by RATIO test only: "
          f"{int((fb['RISK_VS_NOTIONAL_LOW'] | fb['RISK_VS_NOTIONAL_HIGH']).sum())}"
          "   <- the suggested ratio bound alone")
    print(f"  median risk_ratio        : {fb['risk_ratio'].median():.4f}"
          "   <- indistinguishable from 1.0")
    missed_by_tape = bad["quality_flags"] == "{}"
    print(f"  rows the tape's own quality_flags left empty: {int(missed_by_tape.sum())}, "
          f"of which this predicate flags "
          f"{int(fb.loc[missed_by_tape, 'is_risk_implausible'].sum())}")
    if len(bad) == 0:
        failures.append("known-broken: the sentinel population is empty -- "
                        "the query, not the tape, is what changed")
    if not fb["is_risk_implausible"].all():
        failures.append(
            f"known-broken: {int((~fb['is_risk_implausible']).sum())} of {len(bad)} not flagged")
    if int(fb.loc[missed_by_tape, "is_risk_implausible"].sum()) != int(missed_by_tape.sum()):
        failures.append("known-broken: a row the tape missed is also missed here")

    print()
    print("=" * 72)
    print("4b. KNOWN-GOOD: 50k random flow legs (false-positive rate)")
    print("=" * 72)
    good = q(f"""
        SELECT {COLS} FROM {LEGS_TABLE}
        WHERE {FLOW} AND notional < 1e11 AND risk IS NOT NULL
        ORDER BY md5(trade_id || leg_order::text) LIMIT 50000
    """)
    fg = flag_risk_implausible(good)
    print(f"  rows                : {len(good)}")
    print(f"  flagged implausible : {int(fg['is_risk_implausible'].sum())} "
          f"({fg['is_risk_implausible'].mean():.3%})")
    for rc in REASONS:
        k = int(fg[rc].sum())
        if k:
            print(f"    {rc:<24} {k}")
    print(f"  risk_ratio p1/p50/p99: {fg['risk_ratio'].quantile(0.01):.3f} / "
          f"{fg['risk_ratio'].median():.3f} / {fg['risk_ratio'].quantile(0.99):.3f}")
    if fg["is_risk_implausible"].mean() > 0.01:
        failures.append(f"false-positive rate {fg['is_risk_implausible'].mean():.3%} > 1%")

    print()
    print("=" * 72)
    print("4c. KNOWN-GOOD, ADVERSARIAL: the populations the NAIVE bound gets wrong")
    print("=" * 72)
    for label, where in (
        ("deep forward-start (fwd > 10y)",
         f"{FLOW} AND notional<1e11 AND risk IS NOT NULL AND forward_start_years > 10"),
        ("long tenor (> 25y, spot)",
         f"{FLOW} AND notional<1e11 AND risk IS NOT NULL AND tenor_years > 25 "
         "AND coalesce(forward_start_years,0) < 0.02"),
        ("tiny prints (risk = 100)",
         f"{FLOW} AND notional<1e11 AND risk = 100"),
    ):
        d = q(f"SELECT {COLS} FROM {LEGS_TABLE} WHERE {where} "
              f"ORDER BY md5(trade_id || leg_order::text) LIMIT 20000")
        ff = flag_risk_implausible(d)
        naive_exp = d["notional"].astype(float) * d["tenor_years"].astype(float) * 1e-4
        naive_ratio = d["risk"].abs().astype(float) / naive_exp
        naive_bad = (naive_ratio < 0.5) | (naive_ratio > 2.0)
        print(f"  {label:<32} n={len(d):>6}  "
              f"this predicate flags {ff['is_risk_implausible'].mean():>7.3%}  |  "
              f"naive tenor*1e-4 bound flags {naive_bad.mean():>7.3%}")
        if ff["is_risk_implausible"].mean() > 0.02:
            failures.append(
                f"adversarial '{label}': FP {ff['is_risk_implausible'].mean():.3%} > 2%")

    print()
    print("=" * 72)
    print("4d. HEAD TO HEAD on the 55 known-broken rows")
    print("=" * 72)
    naive_exp = bad["notional"].astype(float) * bad["tenor_years"].astype(float) * 1e-4
    naive_ratio = bad["risk"].abs().astype(float) / naive_exp
    naive_bad = (naive_ratio < 0.5) | (naive_ratio > 2.0)
    print(f"  naive tenor*1e-4 bound catches : {int(naive_bad.sum())} / {len(bad)}")
    print(f"  this predicate catches         : {int(fb['is_risk_implausible'].sum())} / {len(bad)}")

    conn.close()

    print()
    print("=" * 72)
    if failures:
        print("VALIDATION FAILED")
        for f in failures:
            print("  -", f)
        return 1
    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    import sys

    if "--validate" in sys.argv:
        raise SystemExit(_validate())
    print(__doc__)
