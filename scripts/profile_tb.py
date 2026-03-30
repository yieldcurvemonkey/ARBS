"""
Performance profiling script for TimeseriesBuilder system.

Profiles:
1. Warm-cache IRS EOD (1Y, single tenor)
2. Warm-cache FRB EOD (1Y, single CUSIP)
3. Cold-cache FRB EOD (bypass caches)
4. Large IRS (2Y, 10 tenors)
5. Mixed product (IRS + FRB together)

Run: /c/Users/chris/anaconda3/envs/stir/python.exe scripts/profile_tb.py
"""

import cProfile
import datetime
import io
import logging
import os
import pstats
import sys
import time

# Ensure repo root on path — use the actual repo, not the worktree
REPO_ROOT = r"C:\Users\chris\clee\ARBS"
os.chdir(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

# Reduce logging noise during profiling
logging.basicConfig(level=logging.WARNING)

# ──────────────────────────────────────────────────────────────────────
# Scenario definitions
# ──────────────────────────────────────────────────────────────────────

def _make_irs_queries_1():
    """Single IRS RATE query: USD-SOFR-1D-Q12STIRT 5Y"""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    return [IRSwapQuery(curve="USD-SOFR-1D-Q12STIRT", tenor="5Y", value=IRSwapValue.RATE)]


def _make_irs_queries_10():
    """10 IRS RATE queries: USD-SOFR-1D-Q12STIRT 1Y-30Y"""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    tenors = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "25Y", "30Y"]
    return [IRSwapQuery(curve="USD-SOFR-1D-Q12STIRT", tenor=t, value=IRSwapValue.RATE) for t in tenors]


def _make_frb_queries_1():
    """Single FRB YTM query: CT10"""
    from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
    from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
    return [FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)]


def _make_frb_queries_5():
    """5 FRB YTM queries: CT2, CT5, CT10, CT20, CT30"""
    from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
    from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
    cusips = ["CT2", "CT5", "CT10", "CT20", "CT30"]
    return [FixedRateBondQuery(cusip=c, value=FixedRateBondValue.YTM) for c in cusips]


def _date_range(years_back=1):
    """Return (start, end) for N years back from today."""
    end = datetime.date.today() - datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=int(365 * years_back))
    return start, end


# ──────────────────────────────────────────────────────────────────────
# Profiling harness
# ──────────────────────────────────────────────────────────────────────

def profile_scenario(name, fn, n_top=40):
    """Run fn under cProfile, print cumulative stats."""
    print(f"\n{'='*72}")
    print(f" SCENARIO: {name}")
    print(f"{'='*72}")

    # Wall-clock time
    t0 = time.perf_counter()

    pr = cProfile.Profile()
    pr.enable()
    try:
        result = fn()
    except Exception as e:
        pr.disable()
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        return None
    pr.disable()

    elapsed = time.perf_counter() - t0

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(n_top)
    print(s.getvalue())

    print(f"  Wall time: {elapsed:.2f}s")
    if result is not None:
        print(f"  Result shape: {result.shape}")
        print(f"  Columns: {list(result.columns)[:5]}{'...' if len(result.columns) > 5 else ''}")

    return result


def timed(name, fn):
    """Simple wall-clock measurement without cProfile overhead."""
    t0 = time.perf_counter()
    try:
        result = fn()
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  [{name}] ERROR after {elapsed:.2f}s: {e}")
        return None
    elapsed = time.perf_counter() - t0
    shape = result.shape if result is not None else "N/A"
    print(f"  [{name}] {elapsed:.2f}s  shape={shape}")
    return result


# ──────────────────────────────────────────────────────────────────────
# Scenario runners
# ──────────────────────────────────────────────────────────────────────

def _make_mdps():
    """Build MDP dict for TimeseriesBuilder."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    return {
        "IRS": IRSwapsMDP(source="BARCHART_STIRF-RL"),
        "FRB": FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL"),
    }


def scenario_irs_warm_1y_1tenor():
    """Warm-cache IRS: 1Y, 1 tenor, EOD freq."""
    from TB.TimeseriesBuilder import TimeseriesBuilder
    start, end = _date_range(1)
    tb = TimeseriesBuilder()
    mdps = _make_mdps()
    queries = _make_irs_queries_1()
    return tb.get_timeseries(start, end, queries, freq="eod", mdps=mdps)


def scenario_irs_warm_2y_10tenors():
    """Warm-cache IRS: 2Y, 10 tenors, n_jobs=8."""
    from TB.TimeseriesBuilder import TimeseriesBuilder
    start, end = _date_range(2)
    tb = TimeseriesBuilder()
    mdps = _make_mdps()
    queries = _make_irs_queries_10()
    return tb.get_timeseries(start, end, queries, freq="eod", n_jobs=8, mdps=mdps)


def scenario_frb_warm_1y():
    """Warm-cache FRB: 1Y, 1 CUSIP, EOD freq."""
    from TB.TimeseriesBuilder import TimeseriesBuilder
    start, end = _date_range(1)
    tb = TimeseriesBuilder()
    mdps = _make_mdps()
    queries = _make_frb_queries_1()
    return tb.get_timeseries(start, end, queries, freq="eod", mdps=mdps)


def scenario_frb_cold_1y():
    """Cold-cache FRB: 1Y, 1 CUSIP, ignore_cache=True."""
    from TB.TimeseriesBuilder import TimeseriesBuilder
    start, end = _date_range(1)
    tb = TimeseriesBuilder()
    mdps = _make_mdps()
    queries = _make_frb_queries_1()
    return tb.get_timeseries(start, end, queries, freq="eod", ignore_cache=True, mdps=mdps)


def scenario_mixed_irs_frb():
    """Mixed: IRS 5Y + FRB CT10, 1Y, EOD."""
    from TB.TimeseriesBuilder import TimeseriesBuilder
    start, end = _date_range(1)
    tb = TimeseriesBuilder()
    mdps = _make_mdps()
    queries = _make_irs_queries_1() + _make_frb_queries_1()
    return tb.get_timeseries(start, end, queries, freq="eod", mdps=mdps)


# ──────────────────────────────────────────────────────────────────────
# Targeted sub-component profiling
# ──────────────────────────────────────────────────────────────────────

def profile_computed_ts_read():
    """Profile just the ComputedTimeseriesStore.read_rows call."""
    from Caching.computed_timeseries_store import ComputedTimeseriesStore
    import pandas as pd

    store = ComputedTimeseriesStore(base_dir="./data/ts")
    start, end = _date_range(1)
    ref_points = pd.bdate_range(start, end).date.tolist()

    # Find an IRS symbol that exists
    from pathlib import Path
    ts_dir = Path("./data/ts")
    irs_symbols = [d.name.replace("asset=", "") for d in ts_dir.iterdir()
                   if d.is_dir() and d.name.startswith("asset=IRS::")]

    if not irs_symbols:
        print("  No IRS symbols in computed TS store")
        return None

    symbol = irs_symbols[0]
    print(f"  Testing symbol: {symbol}")

    t0 = time.perf_counter()
    rows = store.read_rows(
        symbol=symbol,
        reference_points=ref_points,
        intraday=False,
        skip_current_eod=True,
        allow_partial=True,
    )
    elapsed = time.perf_counter() - t0
    print(f"  read_rows: {elapsed:.4f}s, {len(rows)} rows returned for {len(ref_points)} ref points")
    return rows


def profile_duckdb_read():
    """Profile raw DuckDB read performance."""
    import duckdb

    db_path = "./data/ts/computed_ts.duckdb"
    if not os.path.exists(db_path):
        print("  No DuckDB file found")
        return None

    conn = duckdb.connect(db_path, read_only=True)

    # Check what's in the DB
    t0 = time.perf_counter()
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"  Tables: {[t[0] for t in tables]}")

    # Count rows
    for tbl in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM \"{tbl[0]}\"").fetchone()[0]
        print(f"  {tbl[0]}: {count} rows")

    # Time a range query
    if tables:
        tbl_name = tables[0][0]
        t0 = time.perf_counter()
        result = conn.execute(f"""
            SELECT * FROM "{tbl_name}"
            WHERE trading_date >= '2025-01-01' AND trading_date <= '2025-12-31'
            LIMIT 1000
        """).fetchdf()
        elapsed = time.perf_counter() - t0
        print(f"  Range query ({tbl_name}): {elapsed:.4f}s, {len(result)} rows")

    conn.close()


def profile_frb_mdp_single_date():
    """Profile a single FRB MDP get_pricer call to measure HTTP overhead."""
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    # Use the QL source since it uses FedInvest (local data likely available)
    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")

    test_date = datetime.date(2025, 3, 1)

    t0 = time.perf_counter()
    try:
        result = mdp.get_pricer({"cusips": ["CT10"], "timestamp": test_date})
        elapsed = time.perf_counter() - t0
        print(f"  Single get_pricer (CT10, {test_date}): {elapsed:.4f}s")
        if result:
            print(f"  Keys returned: {list(result.keys())}")
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  Single get_pricer failed after {elapsed:.4f}s: {e}")


def profile_frb_bulk_get_data():
    """Profile FRB bulk_get_data for 30 days."""
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    import pandas as pd

    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")

    end = datetime.date(2025, 3, 1)
    start = end - datetime.timedelta(days=45)
    timestamps = pd.bdate_range(start, end).date.tolist()

    print(f"  Bulk fetch: {len(timestamps)} dates, cusips=['CT10']")

    t0 = time.perf_counter()
    try:
        result = mdp.bulk_get_data(
            timestamps=timestamps,
            cusips=["CT10"],
            show_tqdm=True,
            max_workers=8,
        )
        elapsed = time.perf_counter() - t0
        print(f"  bulk_get_data: {elapsed:.2f}s, {len(result)} dates returned")
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  bulk_get_data failed after {elapsed:.2f}s: {e}")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Profile TimeseriesBuilder")
    parser.add_argument("--scenario", type=str, default="all",
                       choices=["all", "irs_warm", "irs_large", "frb_warm",
                                "frb_cold", "mixed", "components", "quick"],
                       help="Which scenario to run")
    args = parser.parse_args()

    scenario = args.scenario

    if scenario in ("all", "quick", "components"):
        print("\n" + "="*72)
        print(" SUB-COMPONENT PROFILING")
        print("="*72)

        print("\n--- DuckDB Read Performance ---")
        profile_duckdb_read()

        print("\n--- ComputedTimeseriesStore.read_rows ---")
        profile_computed_ts_read()

        if scenario != "quick":
            print("\n--- FRB MDP Single Date ---")
            profile_frb_mdp_single_date()

            print("\n--- FRB MDP Bulk (30 days) ---")
            profile_frb_bulk_get_data()

    if scenario in ("all", "irs_warm"):
        profile_scenario("IRS Warm Cache (1Y, 1 tenor)", scenario_irs_warm_1y_1tenor)

    if scenario in ("all", "irs_large"):
        profile_scenario("IRS Large (2Y, 10 tenors, n_jobs=8)", scenario_irs_warm_2y_10tenors)

    if scenario in ("all", "frb_warm"):
        profile_scenario("FRB Warm Cache (1Y, CT10)", scenario_frb_warm_1y)

    if scenario in ("all", "frb_cold"):
        profile_scenario("FRB Cold Cache (1Y, CT10, ignore_cache)", scenario_frb_cold_1y)

    if scenario in ("all", "mixed"):
        profile_scenario("Mixed IRS+FRB (1Y)", scenario_mixed_irs_frb)

    print("\n" + "="*72)
    print(" PROFILING COMPLETE")
    print("="*72)
