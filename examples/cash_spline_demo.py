"""Comprehensive example: UST Cash Spline Framework

Demonstrates the full cash spline workflow:
  1. Building splines with different methods
  2. Accessing yield errors and z-scores
  3. Using presets (JPM par curve, MMSS, roll)
  4. Caching (CORE pattern)
  5. Integration with FixedRateBondsMDP
  6. Using for backtesting yield error time series

Run with:  conda activate stir && python examples/cash_spline_demo.py
"""

import datetime
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Ensure ARBS root is on path ────────────────────────────────────────────
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def section(title: str) -> None:
    print(f"\n{'='*72}")
    print(f"  {title}")
    print(f"{'='*72}\n")


# ══════════════════════════════════════════════════════════════════════════
# SECTION 1: Core API — fit a spline from raw arrays
# ══════════════════════════════════════════════════════════════════════════
def demo_core_api():
    section("1. Core API: Fit from raw arrays")

    from MDP.FixedRateBonds.cash_spline import (
        CashSpline,
        CashSplineBuilder,
        CashSplineConfig,
        SplineMethod,
    )

    # Synthetic UST data (TTM in years, YTM in %)
    cusips = np.array([
        "91282CJN6", "91282CKP0", "91282CLR5", "91282CMT0",
        "91282CNV4", "91282CPX8", "91282CQZ2", "91282CRB4",
        "91282CSA5", "91282CTD8", "912810TM0", "912810TN8",
        "912810TP3", "912810TQ1", "912810TR9", "912810TS7",
    ])
    ttm = np.array([
        1.2, 1.8, 2.3, 2.9, 3.4, 4.1, 5.2, 6.8,
        7.5, 9.8, 12.1, 15.3, 18.7, 21.5, 25.2, 29.1,
    ])
    ytm = np.array([
        4.35, 4.28, 4.22, 4.18, 4.15, 4.12, 4.08, 4.05,
        4.04, 4.06, 4.15, 4.25, 4.38, 4.48, 4.55, 4.58,
    ])
    ranks = np.array([3, 4, 5, 3, 4, 5, 3, 4, 5, 3, 4, 5, 3, 4, 5, 3])

    # --- B-Spline with custom knots (JPM-style) ---
    cfg = CashSplineConfig(
        method="b_spline_with_knots",
        knots=(2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 25.0),
        degree=3,
        exclude_ranks=(0, 1, 2),
        min_ttm=1.0,
    )
    builder = CashSplineBuilder(cfg)
    spline = builder.fit(ttm=ttm, y=ytm, cusips=cusips, ranks=ranks,
                         as_of_date=datetime.date(2025, 3, 28))

    print(f"Method:   {cfg.method}")
    print(f"Bonds:    {len(spline.fit_ttm)}")
    print(f"RMSE:     {spline.rmse:.2f} bp")
    print(f"MAE:      {spline.mae:.2f} bp")
    print()

    # Evaluate at arbitrary maturities
    eval_ttm = np.array([2.0, 5.0, 10.0, 20.0, 30.0])
    eval_y = spline.yield_at(eval_ttm)
    print("Interpolated yields:")
    for t, y in zip(eval_ttm, eval_y):
        print(f"  {t:5.1f}Y  →  {y:.3f}%")
    print()

    # Per-bond yield errors
    print("Per-bond yield errors (bp):")
    errs = spline.yield_errors
    print(errs.to_string())
    print()

    # Summary frame
    print("Summary DataFrame:")
    print(spline.to_frame().to_string())


# ══════════════════════════════════════════════════════════════════════════
# SECTION 2: Compare multiple interpolation methods
# ══════════════════════════════════════════════════════════════════════════
def demo_compare_methods():
    section("2. Compare interpolation methods")

    from MDP.FixedRateBonds.cash_spline import CashSplineBuilder, CashSplineConfig

    ttm = np.array([1.5, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 25.0, 30.0])
    ytm = np.array([4.30, 4.25, 4.18, 4.10, 4.06, 4.08, 4.22, 4.38, 4.50, 4.55])

    methods = [
        ("b_spline_with_knots", {"knots": (3.0, 7.0, 15.0, 25.0), "degree": 3}),
        ("pchip", {}),
        ("nelson_siegel", {"ns_tau0": 2.0}),
        ("nelson_siegel_svensson", {"ns_tau0": (2.0, 5.0)}),
        ("loess", {"loess_frac": 0.4}),
        ("smoothing_spline", {}),
        ("cubic_spline", {}),
    ]

    eval_pts = np.array([2.0, 5.0, 10.0, 20.0, 30.0])
    header = f"{'Method':<30s}" + "".join(f"{t:>8.0f}Y" for t in eval_pts) + f"{'RMSE(bp)':>10s}"
    print(header)
    print("-" * len(header))

    for method_name, extra_kw in methods:
        cfg = CashSplineConfig(
            method=method_name,
            exclude_ranks=(),
            min_ttm=0.0,
            min_points=3,
            **extra_kw,
        )
        builder = CashSplineBuilder(cfg)
        try:
            spline = builder.fit(ttm=ttm, y=ytm)
            vals = spline.yield_at(eval_pts)
            rmse = spline.rmse
            row = f"{method_name:<30s}" + "".join(f"{v:8.3f}%" for v in vals) + f"{rmse:10.2f}"
            print(row)
        except Exception as e:
            print(f"{method_name:<30s}  FAILED: {e}")


# ══════════════════════════════════════════════════════════════════════════
# SECTION 3: Using preset configs
# ══════════════════════════════════════════════════════════════════════════
def demo_presets():
    section("3. Preset configurations")

    from MDP.FixedRateBonds.cash_spline import (
        CashSplineBuilder,
        JPM_PAR_CURVE_CONFIG,
        MMSS_SPLINE_CONFIG,
        ROLL_SPLINE_CONFIG,
    )

    ttm = np.array([1.5, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 25.0, 30.0])
    ytm = np.array([4.30, 4.25, 4.18, 4.10, 4.06, 4.08, 4.22, 4.38, 4.50, 4.55])
    ranks = np.array([3, 4, 5, 3, 4, 5, 3, 4, 5, 3])

    for name, cfg in [
        ("JPM Par Curve", JPM_PAR_CURVE_CONFIG),
        ("MMSS Spline", MMSS_SPLINE_CONFIG),
        ("Roll Spline", ROLL_SPLINE_CONFIG),
    ]:
        builder = CashSplineBuilder(cfg)
        try:
            spline = builder.fit(ttm=ttm, y=ytm, ranks=ranks)
            print(f"{name:20s}  method={cfg.method:<25s}  "
                  f"knots={cfg.knots}  RMSE={spline.rmse:.2f}bp")
        except ValueError as e:
            print(f"{name:20s}  SKIPPED: {e}")


# ══════════════════════════════════════════════════════════════════════════
# SECTION 4: Config overrides & customization
# ══════════════════════════════════════════════════════════════════════════
def demo_config_overrides():
    section("4. Config overrides")

    from MDP.FixedRateBonds.cash_spline import (
        CashSplineBuilder,
        CashSplineConfig,
        JPM_PAR_CURVE_CONFIG,
    )

    # Start from JPM preset, customize
    custom = JPM_PAR_CURVE_CONFIG.with_overrides(
        method="nelson_siegel_svensson",
        exclude_ranks=(0,),
        min_ttm=2.0,
    )
    print(f"Base:     {JPM_PAR_CURVE_CONFIG.method}")
    print(f"Custom:   {custom.method}")
    print(f"Ranks:    {custom.exclude_ranks}")
    print(f"Min TTM:  {custom.min_ttm}")
    print(f"Hash:     {custom.config_hash}")

    # Show that hash changes
    print(f"\nJPM hash:    {JPM_PAR_CURVE_CONFIG.config_hash}")
    print(f"Custom hash: {custom.config_hash}")
    assert JPM_PAR_CURVE_CONFIG.config_hash != custom.config_hash


# ══════════════════════════════════════════════════════════════════════════
# SECTION 5: Caching (CORE pattern)
# ══════════════════════════════════════════════════════════════════════════
def demo_caching():
    section("5. Caching (compute once, read everywhere)")

    import time
    from MDP.FixedRateBonds.cash_spline import (
        CashSplineBuilder,
        CashSplineConfig,
        clear_spline_cache,
        get_cached_spline,
        put_cached_spline,
    )

    clear_spline_cache(include_persistent=False)

    cfg = CashSplineConfig(method="pchip", exclude_ranks=(), min_ttm=0.0, min_points=3)
    ttm = np.array([1.0, 2.0, 5.0, 10.0, 20.0, 30.0])
    ytm = np.array([4.30, 4.22, 4.10, 4.08, 4.38, 4.55])
    date = datetime.date(2025, 3, 28)

    # First fit
    t0 = time.perf_counter()
    builder = CashSplineBuilder(cfg)
    spline = builder.fit(ttm=ttm, y=ytm, as_of_date=date)
    put_cached_spline(spline)
    t_fit = (time.perf_counter() - t0) * 1000

    # Cache retrieval
    t0 = time.perf_counter()
    cached = get_cached_spline(date, cfg)
    t_cache = (time.perf_counter() - t0) * 1000

    print(f"Initial fit:    {t_fit:.1f} ms")
    print(f"Cache lookup:   {t_cache:.3f} ms")
    print(f"Cache hit:      {cached is not None}")
    print(f"Values match:   {np.allclose(spline.yield_at(5.0), cached.yield_at(5.0))}")


# ══════════════════════════════════════════════════════════════════════════
# SECTION 6: Integration with FixedRateBondsMDP
# ══════════════════════════════════════════════════════════════════════════
def demo_mdp_integration():
    section("6. MDP Integration: fetch_cash_spline()")

    from MDP.FixedRateBonds.cash_spline import CashSplineConfig, JPM_PAR_CURVE_CONFIG
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    as_of = datetime.date(2025, 3, 27)

    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    with mdp:
        # Use default JPM config
        spline = mdp.fetch_cash_spline(as_of)
        if spline is None:
            print("No data for this date (expected if no market data cached).")
            print("In production, this fetches pricers → builds spline → caches.")
            return

        print(f"Date:     {spline.as_of_date}")
        print(f"Bonds:    {len(spline.fit_ttm)}")
        print(f"RMSE:     {spline.rmse:.2f} bp")
        print(f"MAE:      {spline.mae:.2f} bp")
        print()

        # Yield curve
        eval_pts = [2, 3, 5, 7, 10, 20, 30]
        print("Fitted par curve:")
        for t in eval_pts:
            print(f"  {t:3d}Y  →  {spline.yield_at(t):.3f}%")

        # Rich/cheap
        print("\nTop 5 richest (most negative yield error):")
        errs = spline.yield_errors.sort_values()
        print(errs.head(5).to_string())

        print("\nTop 5 cheapest (most positive yield error):")
        print(errs.tail(5).to_string())

        # Custom config override
        nss_cfg = JPM_PAR_CURVE_CONFIG.with_overrides(
            method="nelson_siegel_svensson",
        )
        nss_spline = mdp.fetch_cash_spline(as_of, config=nss_cfg)
        if nss_spline:
            print(f"\nNSS fit — RMSE: {nss_spline.rmse:.2f} bp (vs B-spline {spline.rmse:.2f} bp)")


# ══════════════════════════════════════════════════════════════════════════
# SECTION 7: Backtesting yield error time series
# ══════════════════════════════════════════════════════════════════════════
def demo_backtest_yield_errors():
    section("7. Backtesting: yield error time series")

    from MDP.FixedRateBonds.cash_spline import CashSplineBuilder, CashSplineConfig

    # Simulate 5 dates of bond data
    np.random.seed(42)
    base_ttm = np.array([1.5, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 25.0, 30.0])
    base_ytm = np.array([4.30, 4.25, 4.18, 4.10, 4.06, 4.08, 4.22, 4.38, 4.50, 4.55])
    cusips = [f"CUSIP_{i:02d}" for i in range(len(base_ttm))]

    # Use b_spline_with_knots with fewer knots than data points
    # so residuals are non-zero (smoothing, not interpolating)
    cfg = CashSplineConfig(
        method="b_spline_with_knots",
        knots=(3.0, 7.0, 20.0),
        degree=3,
        exclude_ranks=(),
        min_ttm=0.0,
        min_points=3,
    )
    builder = CashSplineBuilder(cfg)

    dates = pd.bdate_range("2025-03-24", periods=5).date
    all_errors = {}

    for dt in dates:
        noise = np.random.normal(0, 0.03, len(base_ttm))
        ytm_t = base_ytm + noise
        spline = builder.fit(
            ttm=base_ttm, y=ytm_t, cusips=np.array(cusips),
            as_of_date=dt,
        )
        all_errors[dt] = spline.yield_errors

    # Build yield error panel
    error_panel = pd.DataFrame(all_errors).T
    error_panel.index.name = "date"
    print("Yield error panel (bp):")
    print(error_panel.round(2).to_string())
    print()

    # Z-scores using historical lookback
    latest_spline = builder.fit(
        ttm=base_ttm,
        y=base_ytm + np.random.normal(0, 0.03, len(base_ttm)),
        cusips=np.array(cusips),
    )
    lookback_residuals = pd.DataFrame({
        c: error_panel[c].values / 100.0  # bp back to pct
        for c in error_panel.columns
    })
    z = latest_spline.z_scores(lookback_residuals=lookback_residuals)
    if z is not None:
        print("Z-scores (latest vs. 5-day lookback):")
        print(z.round(2).to_string())


# ══════════════════════════════════════════════════════════════════════════
# SECTION 8: Roll spline bridge
# ══════════════════════════════════════════════════════════════════════════
def demo_roll_bridge():
    section("8. Roll spline bridge (carry_roll.py integration)")

    from Query.FixedRateBonds.carry_roll import fit_roll_spline, fit_roll_spline_via_cash_spline

    ttm = np.array([1.5, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 25.0, 30.0])
    ytm = np.array([4.30, 4.25, 4.18, 4.10, 4.06, 4.08, 4.22, 4.38, 4.50, 4.55])

    # Legacy approach
    legacy_func = fit_roll_spline(ttm, ytm)

    # New CashSpline-based approach
    new_func = fit_roll_spline_via_cash_spline(
        ttm, ytm,
        as_of_date=datetime.date(2025, 3, 28),
    )

    if legacy_func and new_func:
        eval_pts = np.array([2.0, 5.0, 10.0, 20.0, 30.0])
        print(f"{'TTM':>6s}  {'Legacy':>10s}  {'CashSpline':>10s}  {'Diff(bp)':>10s}")
        print("-" * 42)
        for t in eval_pts:
            v_old = float(legacy_func(t))
            v_new = float(new_func(np.array([t]))[0])
            diff_bp = (v_new - v_old) * 100
            print(f"{t:6.1f}  {v_old:10.4f}  {v_new:10.4f}  {diff_bp:10.2f}")
    else:
        print("One or both spline fits returned None.")


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    demo_core_api()
    demo_compare_methods()
    demo_presets()
    demo_config_overrides()
    demo_caching()
    demo_roll_bridge()
    demo_backtest_yield_errors()

    # MDP integration requires actual market data / cache
    try:
        demo_mdp_integration()
    except Exception as e:
        section("6. MDP Integration (skipped)")
        print(f"Skipped MDP demo: {e}")
        print("This is expected if running without market data cache.")

    print("\n" + "=" * 72)
    print("  All demos completed successfully!")
    print("=" * 72)
