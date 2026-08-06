"""Fast CURVE-ONLY panel: bf_bps + rates for all 28 flies, full year.

No options. This is the forward-return target (Delta bf_bps) for ALL strategies
and the signal for the naive (fade-by-magnitude) baseline. Cheap vs the options
backfill, so we can run the full year immediately.

Output: butterfly_curve_panel.parquet  (date x fly_id x {bf_bps, rates, sp_*})
"""
import argparse, datetime, sys, time
sys.path.insert(0, r"C:\Users\chris\clee\ARBS")
import numpy as np, pandas as pd, QuantLib as ql, pytz

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import get_fomc_meetings_list
from Query.IRSwaps.IRSwapQuery import IRSwapQuery

NYC_tz = pytz.timezone("America/New_York")
CURVE = "USD-SOFR-1D-Q12STIRT"
OUTPUT_PATH = r"C:\Users\chris\clee\ARBS\notebooks\backtests\SFR_screeners\butterfly_curve_panel.parquet"
SPACINGS = {1: "3mo", 2: "6mo", 3: "9mo", 4: "12mo"}
IMM_TENORS = [f"IMM_{i}xIMM_{i+1}" for i in range(1, 13)]
IMM_MONTH_MAP = {"H": 3, "M": 6, "U": 9, "Z": 12}


def imm_sym(c):
    return f"SFR{c[0]}2{c[1]}"


def biz_days(start, end):
    cal = ql.UnitedStates(ql.UnitedStates.NYSE)
    d, end_ql, out = ql.Date(start.day, start.month, start.year), ql.Date(end.day, end.month, end.year), []
    while d <= end_ql:
        if cal.isBusinessDay(d):
            out.append(datetime.date(d.year(), d.month(), d.dayOfMonth()))
        d = d + 1
    return out


def imm_dates(code):
    y, m = 2020 + int(code[1]), IMM_MONTH_MAP[code[0]]
    s = datetime.date(y, m, 15)
    em, ey = (m + 3, y) if m + 3 <= 12 else (m - 9, y + 1)
    return s, datetime.date(ey, em, 15)


def fomc_dates(as_of):
    raw = get_fomc_meetings_list(as_of=as_of, n_plus_years=2)
    out = []
    for d in raw:
        if isinstance(d, datetime.datetime):
            d = d.date()
        elif hasattr(d, "date") and not isinstance(d, datetime.date):
            d = d.date()
        out.append(d)
    return [d for d in out if d > as_of]


def cnt(s, e, fl):
    return sum(1 for d in fl if s <= d < e)


def curve_for_date(as_of, curve_mdp):
    ts = NYC_tz.localize(datetime.datetime.combine(as_of, datetime.time(17, 0)))
    try:
        ch = curve_mdp.get_pricer(request=dict(curve_name=CURVE, timestamp=ts))
    except Exception:
        return []
    contracts, prices, rates = [], [], []
    for t in IMM_TENORS:
        try:
            q = IRSwapQuery(curve=CURVE, tenor=t).resolve_query(ts, pricer_or_curve=ch)
            pkg, _ = q.resolve_package(pricer_or_curve=ch)
            eff = pkg[0].leg1.schedule.effective
            prices.append(100 - pkg[0].kwargs.leg1["fixed_rate"])
            rates.append(pkg[0].kwargs.leg1["fixed_rate"] * 100)
            contracts.append(ql.IMM.code(ql.Date(eff.day, eff.month, eff.year)))
        except Exception:
            return []
    if len(contracts) < 3:
        return []
    fl = fomc_dates(as_of)
    ld = {c: imm_dates(c) for c in contracts}
    rows = []
    for sp, gap in SPACINGS.items():
        for i in range(len(contracts) - 2 * sp):
            ni, mi, fi = i, i + sp, i + 2 * sp
            n, m, f = contracts[ni], contracts[mi], contracts[fi]
            ns, ms, fs_ = ld[n][0], ld[m][0], ld[f][0]
            rows.append({
                "date": as_of, "fly_id": f"{imm_sym(n)}_{imm_sym(m)}_{imm_sym(f)}",
                "butterfly": f"BF {n}-{m}-{f}", "spacing": sp, "gap": gap,
                "near": n, "mid": m, "far": f,
                "bf_bps": (prices[ni] - 2 * prices[mi] + prices[fi]) * 10000,
                "sp_near_bps": (prices[ni] - prices[mi]) * 10000,
                "sp_far_bps": (prices[mi] - prices[fi]) * 10000,
                "near_rate": rates[ni], "mid_rate": rates[mi], "far_rate": rates[fi],
                "fomc_near_gap": cnt(ns, ms, fl), "fomc_far_gap": cnt(ms, fs_, fl),
                "fomc_asym": abs(cnt(ns, ms, fl) - cnt(ms, fs_, fl)),
            })
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2025-05-22")
    p.add_argument("--end", default="2026-05-22")
    p.add_argument("--timing", action="store_true", help="time N dates only, no write")
    p.add_argument("--n", type=int, default=20)
    a = p.parse_args()
    curve_mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    start, end = datetime.date.fromisoformat(a.start), datetime.date.fromisoformat(a.end)
    days = biz_days(start, end)

    if a.timing:
        sample = days[:a.n]
        t0 = time.time()
        n_ok = 0
        for d in sample:
            td = time.time()
            r = curve_for_date(d, curve_mdp)
            n_ok += 1 if r else 0
            print(f"  {d}: {len(r)} flies  {time.time()-td:.2f}s")
        dt = time.time() - t0
        print(f"\n{len(sample)} dates in {dt:.1f}s = {dt/len(sample):.2f}s/date | "
              f"full-year est: {dt/len(sample)*len(days)/60:.1f} min")
        return

    print(f"CURVE PANEL {start} -> {end} | {len(days)} biz days")
    all_rows, t0 = [], time.time()
    for i, d in enumerate(days):
        r = curve_for_date(d, curve_mdp)
        all_rows.extend(r)
        if (i + 1) % 25 == 0 or i == 0:
            print(f"  [{i+1}/{len(days)}] {d}: {len(r)} flies "
                  f"({(i+1)/max(time.time()-t0,1e-6)*60:.0f} dates/min)")
    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "spacing", "fly_id"]).reset_index(drop=True)
    df.to_parquet(OUTPUT_PATH, index=False)
    print(f"\nSaved {df.shape} to {OUTPUT_PATH} | {df['date'].nunique()} dates, "
          f"{df['fly_id'].nunique()} flies, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
