"""Mutation check for the AGGREGATE ladder.

A test that does not fail when its defect is reintroduced is decoration. Each entry below
reintroduces one specific wrong answer -- most of them wrong answers this study could
plausibly have shipped -- and requires the named test to go red.

Run:  C:/Users/chris/anaconda3/envs/stir/python.exe tests/_mutate_etf_aggregate.py
"""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

MUTATIONS = [
    # ---- THE LOOKAHEAD. The single biggest way this study could fake a positive: key the
    # as-of join on the N-PORT report date instead of the date the filing became public,
    # and SPTL/VGLT get a 53-62 day view of the future.
    ("RVUtils/ETFRebalance/aggregate.py",
     '            left_on="date", right_on="avail", direction="backward",',
     '            left_on="date", right_on="obs_date", direction="backward",  # MUTATED: 53-62 day lookahead',
     "test_an_nport_book_does_not_enter_the_panel_before_it_was_filed"),

    # ---- THE DENOMINATOR TRAP. Remove the only check that can see two funds being
    # measured against different boards -- no shape, dtype or range test can.
    ("RVUtils/ETFRebalance/aggregate.py",
     "        if worst > tol:",
     "        if False:  # MUTATED: benchmarks may silently differ",
     "test_active_weights_measured_against_DIFFERENT_benchmarks_are_refused"),

    # ---- The same trap from the other side: the guard must not be a blanket refusal.
    ("RVUtils/ETFRebalance/aggregate.py",
     "    if len(names) < 2:\n        return",
     "    raise DifferentDenominators('MUTATED: refuses everything')\n    if len(names) < 2:\n        return",
     "test_active_weights_on_ONE_common_benchmark_are_accepted"),

    # ---- A bond nobody holds must sit at -w_i, not at zero. Dropping the term deletes
    # the most underweight name on the board -- the observation the signal is most about.
    ("RVUtils/ETFRebalance/aggregate.py",
     '    j["active_agg"] = j["held_w"] - j["w_i"]',
     '    j["active_agg"] = j["held_w"]  # MUTATED: an unheld bond reads as neutral',
     "test_a_bond_no_fund_holds_carries_the_full_negative_index_weight"),

    # ---- The z must not contain the observation it is scoring.
    ("RVUtils/ETFRebalance/aggregate.py",
     "    prior = f.groupby(key)[value_col].shift(1)",
     "    prior = f[value_col]  # MUTATED: the spike deflates its own z",
     "test_the_bucket_z_is_strictly_backward_looking"),

    # ---- A missing float must not become a zero denominator.
    ("RVUtils/ETFRebalance/aggregate.py",
     '    denom = denom.where(~j["float_fallback"], pd.to_numeric(j["outstanding_amt"], errors="coerce"))',
     '    denom = denom  # MUTATED: a missing float stays missing and the bucket vanishes',
     "test_a_missing_free_float_falls_back_and_is_FLAGGED_never_treated_as_zero"),

    # ---- The off-slice residual must be measured against the WHOLE book, or construction
    # (b) reports that it discarded nothing.
    ("RVUtils/ETFRebalance/aggregate.py",
     '    book_par = asof.groupby(["date", "ticker"], as_index=False)["par"].sum() \\',
     '    book_par = inside.groupby(["date", "ticker"], as_index=False)["par"].sum() \\  # MUTATED: off-slice always zero',
     "test_the_offslice_residual_is_reported_and_not_silently_dropped"),

    # ---- A fund set is not complete until its LAST fund has published.
    ("RVUtils/ETFRebalance/aggregate.py",
     "    return pd.Timestamp(firsts.max())",
     "    return pd.Timestamp(firsts.min())  # MUTATED: aggregate starts before it exists",
     "test_a_fund_set_starts_only_when_every_fund_in_it_has_published"),

    # ---- The bucket index must saturate above the band rather than running away.
    ("RVUtils/ETFRebalance/aggregate.py",
     "    return k.clip(lower=0, upper=hi)",
     "    return k  # MUTATED: unbounded bucket index",
     "test_the_bucket_is_a_constant_maturity_offset_from_the_bands_lower_edge"),

    # ---- "no data here" must not be reported as "no signal here".
    ("RVUtils/ETFRebalance/signals.py",
     "    if column not in df.columns:",
     "    if False:  # MUTATED: a missing column becomes an all-NaN score",
     "test_precomputed_refuses_a_missing_column_instead_of_returning_all_nan"),

    # ---- An unrecognised z_mode must not fall through to raw pass-through.
    ("RVUtils/ETFRebalance/signals.py",
     "    if z_mode not in valid_modes:",
     "    if False:  # MUTATED: a typo silently disables standardisation",
     "test_an_unknown_z_mode_is_refused_rather_than_falling_through_to_raw"),

    # ---- The matched placebo must be an EVENT, not a maturity tilt.
    ("RVUtils/ETFRebalance/signals.py",
     "        crosses = (ttm_at < boundary) & (df[\"ttm\"] >= boundary)",
     "        crosses = (ttm_at < boundary)  # MUTATED: flags the whole board below the boundary",
     "test_the_placebo_fires_on_a_CROSSING_not_on_everything_below_the_boundary"),
]

env = dict(os.environ,
           ARBS_SUPABASE_ENABLED="0",
           ARBS_ETF_HOLDINGS_DIR="C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
py = r"C:/Users/chris/anaconda3/envs/stir/python.exe"

ok = True
for rel, old, new, test in MUTATIONS:
    p = ROOT / rel
    src = p.read_text(encoding="utf-8")
    if old not in src:
        print(f"[SKIP] anchor not found in {rel}: {old[:60]!r}")
        ok = False
        continue
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    try:
        r = subprocess.run(
            [py, "-m", "pytest", "tests/test_etf_aggregate.py", "-q", "-k", test],
            cwd=ROOT, capture_output=True, text=True, env=env, timeout=300)
        failed = r.returncode != 0
        print(f"[{'PASS' if failed else 'FAIL'}] {test:66s} "
              f"{'caught the mutation' if failed else 'DID NOT CATCH IT'}")
        ok &= failed
    finally:
        p.write_text(src, encoding="utf-8")

print("\nALL MUTATIONS CAUGHT" if ok else "\nSOME TESTS ARE DECORATION")
sys.exit(0 if ok else 1)
