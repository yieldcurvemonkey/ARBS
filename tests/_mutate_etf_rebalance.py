"""Mutation check: a test that does not fail when its defect is reintroduced is decoration."""
import pathlib, subprocess, sys, shutil, os
ROOT = pathlib.Path(__file__).resolve().parents[1]   # the repo root, not tests/
MUTATIONS = [
    ("RVUtils/ETFRebalance/signals.py",
     "    scale = scale.where(scale > 0, sd)",
     "    scale = scale  # MUTATED: drop the sparse-signal fallback",
     "test_cross_sectional_z_survives_a_sparse_signal"),
    ("RVUtils/ETFRebalance/engine.py",
     "        a = (t_k - t_b) / (t_k - t_f)",
     "        a = 0.5  # MUTATED: fixed weights, no longer slope neutral",
     "test_fly_weights_are_neutral_to_level_and_slope"),
    # Target the line the 403 path actually reaches: with 403 in BLOCKED_STATUSES the
    # loop retries and then falls through to the FINAL raise. Mutating the "!= 200"
    # branch was a no-op, which the first mutation run showed.
    ("MDP/ETFHoldings/providers/ishares.py",
     '    raise Blocked(f"{ticker} {date}: refused after {max_attempts} attempts ({last})")',
     "    return None  # MUTATED: a refusal recorded as absence",
     "test_a_refusal_is_an_exception_not_absence"),
    ("RVUtils/ETFRebalance/costs.py",
     # TWO independent guards keep a quoted zero out -- the .where() screen and the
     # .clip() floor -- so no single-line edit can break this, which is the point. The
     # mutation therefore bypasses the whole branch, i.e. "someone rewrote it to use the
     # raw quoted spread".
     "            return (px_bp / panel[\"mod_dur\"].astype(float)) * self.multiplier",
     "            return (panel[\"spread_price_bp\"].fillna(0.0).astype(float) / panel[\"mod_dur\"].astype(float)) * self.multiplier  # MUTATED",
     "test_measured_cost_never_returns_zero_for_a_zero_quoted_spread"),
    # The vectorised marking loop: drop the step that keeps the daily curve and the
    # trade log on the same footing.
    ("RVUtils/ETFRebalance/engine.py",
     "            pnl_arr[i0 + 1:i1 + 1] += step[1:]",
     "            pnl_arr[i0 + 1:i1 + 1] += step[1:] * 0.999  # MUTATED: curve drifts off the log",
     "test_daily_marks_reconcile_to_the_trade_log_exactly"),
    ("RVUtils/ETFRebalance/engine.py",
     "            cost_bp = float(np.nansum(np.abs(w) * LC[i0][idx]))",
     "            cost_bp = float(np.nansum(np.abs(w) * LC[i0][idx])) * 0.5  # MUTATED: half a round trip",
     "test_the_charged_cost_is_a_FULL_round_trip_on_all_three_legs"),
    ("RVUtils/ETFRebalance/engine.py",
     "                carry_cum = np.nancumsum(side * per_year * dt)",
     "                carry_cum = np.cumsum(side * per_year * dt)  # MUTATED: NaN eats the trade",
     "test_a_mid_hold_pricing_hole_does_not_nan_the_whole_trade"),
    ("RVUtils/ETFRebalance/engine.py",
     '    out["ytm"] = out["ytm"].where(~ok, out["ytm_eod"])',
     '    out["ytm"] = out["ytm"]  # MUTATED: the price-basis knob becomes inert',
     "test_price_basis_knob_actually_changes_the_book"),
    ("RVUtils/ETFRebalance/holdings_panel.py",
     "    dates = np.sort(df[date_col].unique())",
     "    dates = np.sort(df[date_col].unique())\n    exec_lag = 0  # MUTATED: lookahead",
     "test_exec_lag_moves_the_trade_date_along_the_panels_own_axis"),
]
env = dict(os.environ, ARBS_ETF_HOLDINGS_DIR="C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
py = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
ok = True
for rel, old, new, test in MUTATIONS:
    p = ROOT / rel
    src = p.read_text(encoding="utf-8")
    if old not in src:
        print(f"[SKIP] anchor not found in {rel}: {old[:50]!r}"); ok = False; continue
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    try:
        r = subprocess.run([py, "-m", "pytest", "tests/test_etf_rebalance.py", "-q", "-k", test],
                           cwd=ROOT, capture_output=True, text=True, env=env, timeout=180)
        failed = r.returncode != 0
        print(f"[{'PASS' if failed else 'FAIL'}] {test:62s} "
              f"{'caught the mutation' if failed else 'DID NOT CATCH IT'}")
        ok &= failed
    finally:
        p.write_text(src, encoding="utf-8")
print("\nALL MUTATIONS CAUGHT" if ok else "\nSOME TESTS ARE DECORATION")
sys.exit(0 if ok else 1)
