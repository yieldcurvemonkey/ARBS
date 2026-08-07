"""The MEETING-INDEXED fly, which the calendar-consecutive study did not test.

The ZQ lab built structures from ``codes[i:i+n]`` -- strictly consecutive
delivery months. That is **not** what a STIR desk means by an FOMC fly.

A desk indexes by MEETING, and picks the contract month that reads each one:

    as of 2026-07-30, the next three decisions are Sep-16, Oct-28 and Dec-09.
    Their readers are OCTOBER, NOVEMBER and JANUARY-27 -- ZQV26 / ZQX26 / ZQF27.
    DECEMBER IS SKIPPED, because it is the blended month (9/31 at the post-Oct
    rate, 22/31 at the post-Dec rate) and reads neither decision cleanly.

So the meeting fly is ``2*Nov - Oct - Jan``, whose legs are NOT adjacent. In
exposure terms it is close to ``jump(Oct) - jump(Dec)`` -- the **second
difference of the policy path in meeting space**, which is the object the whole
kink thesis is actually about. The calendar-consecutive fly ``2*Nov - Oct - Dec``
is a diluted version of the same thing: it loads the December decision at ~-0.71
instead of -1.00, because December only spends 22/31 of itself at the new rate.

This probe builds the meeting-indexed structures, measures their differential
exposure and their ORACLE CEILING, and compares them against the
calendar-consecutive ones the lab already ran.

Its result is now first-class: ``zq_kink_fade_common.meeting_reader_map`` /
``zq_meeting_structures``, families F4-F6 in ``zq_kink_fade_backtest``, and the
2026-07-30 case pinned as a golden test in ``tests/test_meanrev_ff.py``.

Run: conda run -n stir python notebooks/rv/_probe_zq_meeting_fly.py
"""
import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "notebooks" / "backtests"))

import numpy as np
import pandas as pd

pd.set_option("display.width", 250, "display.max_columns", 40)

from RVUtils.MeanRev.diagnostics import move_profile
from RVUtils.MeanRev.ff import ZQ_TICK_BP, delivery_window, zq_exposure_vector
from RVUtils.MeanRev.meetings import fomc_decisions, solve_smooth_path

DATA = REPO / "notebooks" / "data" / "zq_kink_fade"
MAX_RANK = 12


def main() -> int:
    c = pd.read_parquet(DATA / "contracts.parquet")
    c["as_of"] = pd.to_datetime(c["as_of"])
    live = c[~c["accruing"]].copy()
    live["rank"] = live.groupby("as_of")["imm_start"].rank(method="first").astype(int)
    live = live[live["rank"] <= MAX_RANK]

    codes = sorted(live["code"].unique(), key=lambda k: delivery_window(k)[0])
    win = {k: delivery_window(k) for k in codes}
    # ⚠ Bound the meetings to the STRIP's own span. A wider list silently
    # corrupts the reader map: a meeting the strip cannot reach has near-equal
    # shares everywhere, its argmax lands on an edge contract, and many such
    # meetings then look like they "share a reader". An earlier version of this
    # probe used 2017-2031 and reported a bogus "111 meetings -> 77 readers";
    # bounded properly it is 77 decisions, 76 transitions, 76 DISTINCT readers.
    meetings = fomc_decisions(min(win[k][0] for k in codes),
                              max(win[k][1] for k in codes))
    exp = {k: zq_exposure_vector(win[k][:2], meetings) for k in codes}

    # share of a contract's month spent in regime k = between meeting k and k+1
    E = np.vstack([exp[k] for k in codes])                     # codes x meetings
    share = E[:, :-1] - E[:, 1:]                               # codes x (M-1)
    share_df = pd.DataFrame(share, index=codes,
                            columns=[m for m in meetings[:-1]])

    # the READER of a meeting is the delivery month that spends the largest share
    # of itself at that meeting's rate
    reader = share_df.idxmax(axis=0)
    clean = share_df.max(axis=0)
    readers = pd.DataFrame({"meeting": share_df.columns, "reader": reader.to_numpy(),
                            "day_share": clean.to_numpy()})
    readers["reader_month"] = [win[r][0].strftime("%b-%y") for r in readers["reader"]]

    print("=" * 100, flush=True)
    print("MEETING -> READER CONTRACT", flush=True)
    print("=" * 100, flush=True)
    show = readers[(readers["meeting"] >= datetime.date(2026, 6, 1))
                   & (readers["meeting"] <= datetime.date(2027, 12, 31))]
    print(show.to_string(index=False), flush=True)

    # ---------------------------------------------- the user's worked example
    print("\n" + "=" * 100, flush=True)
    print("SANITY CHECK: the FOMC 1/2/3 fly as of 2026-07-30", flush=True)
    print("=" * 100, flush=True)
    asof = datetime.date(2026, 7, 30)
    nxt = [m for m in meetings if m > asof][:3]
    print(f"  next three decisions: {nxt}", flush=True)
    got = [readers.set_index("meeting").loc[m, "reader"] for m in nxt]
    print(f"  their reader contracts: {['ZQ' + g for g in got]}", flush=True)
    print(f"  expected (from the desk): ['ZQV26', 'ZQX26', 'ZQF27']", flush=True)
    print(f"  MATCH: {['ZQ' + g for g in got] == ['ZQV26', 'ZQX26', 'ZQF27']}",
          flush=True)
    skipped = [k for k in codes
               if datetime.date(2026, 10, 1) <= win[k][0] <= datetime.date(2027, 1, 1)
               and k not in got]
    print(f"  months in that span that read NO meeting cleanly: {skipped}", flush=True)
    for k in ["V26", "X26", "Z26", "F27"]:
        s = share_df.loc[k]
        top = s.sort_values(ascending=False).head(2)
        print(f"    ZQ{k} ({win[k][0].strftime('%b-%y')}): "
              f"largest regime shares {[(str(i), round(v, 3)) for i, v in top.items()]}",
              flush=True)

    # ------------------------------------------------------------ structures
    wide = live.pivot_table(index="as_of", columns="code", values="rate_pct",
                            aggfunc="first").sort_index()
    rank = live.pivot_table(index="as_of", columns="code", values="rank",
                            aggfunc="first").reindex(index=wide.index,
                                                     columns=wide.columns)

    def build(legs_list, w):
        lv, de = {}, {}
        for legs in legs_list:
            if any(l not in wide.columns for l in legs):
                continue
            key = "-".join(legs)
            ok = np.ones(len(wide), dtype=bool)
            for l in legs:
                ok &= (rank[l] <= MAX_RANK).fillna(False).to_numpy()
            lv[key] = (sum(x * wide[l] for x, l in zip(w, legs)) * 100.0).where(ok)
            de[key] = float(np.abs(sum(x * exp[l] for x, l in zip(w, legs))).max())
        return pd.DataFrame(lv), pd.Series(de)

    # meeting-indexed: consecutive READERS (which skip blended months)
    rd = [r for r in readers["reader"].tolist()]
    # collapse consecutive duplicates -- two meetings can share a reader when no
    # month sits cleanly inside one of the regimes
    rd_uniq = [rd[0]]
    for x in rd[1:]:
        if x != rd_uniq[-1]:
            rd_uniq.append(x)
    m_pairs = [(rd_uniq[i], rd_uniq[i + 1]) for i in range(len(rd_uniq) - 1)]
    m_flies = [(rd_uniq[i], rd_uniq[i + 1], rd_uniq[i + 2])
               for i in range(len(rd_uniq) - 2)]
    print(f"\n  {len(rd)} readable transitions -> {len(rd_uniq)} distinct readers "
          f"({len(rd) - len(rd_uniq)} share a reader with the previous one)",
          flush=True)
    print(f"  cleanliness of the read: min {readers['day_share'].min():.3f}, "
          f"median {readers['day_share'].median():.3f}", flush=True)

    # calendar-consecutive, for the comparison
    c_pairs = [(codes[i], codes[i + 1]) for i in range(len(codes) - 1)]
    c_flies = [(codes[i], codes[i + 1], codes[i + 2]) for i in range(len(codes) - 2)]

    sets = {
        "calendar spread": (c_pairs, (-1.0, 1.0), 1.0),
        "MEETING spread": (m_pairs, (-1.0, 1.0), 1.0),
        "calendar fly": (c_flies, (-1.0, 2.0, -1.0), 2.0),
        "MEETING fly": (m_flies, (-1.0, 2.0, -1.0), 2.0),
    }

    print("\n" + "=" * 100, flush=True)
    print("DIFFERENTIAL EXPOSURE AND DISPERSION", flush=True)
    print("=" * 100, flush=True)
    built = {}
    rows = []
    for nm, (legs_list, w, cost) in sets.items():
        lv, de = build(legs_list, w)
        built[nm] = (lv, de, cost, w)
        d = lv.diff().stack()
        rows.append({"structure": nm, "n_keys": lv.shape[1], "cost_bp": cost,
                     "diff_exposure_median": float(de.median()),
                     "diff_exposure_max": float(de.max()),
                     "sd_bp": float(lv.stack().std()),
                     "sd_ticks": float(lv.stack().std() / ZQ_TICK_BP),
                     "daily_sd_bp": float(d.std()),
                     "pct_unchanged": float((d.abs() < 1e-9).mean())})
    print(pd.DataFrame(rows).round(3).to_string(index=False), flush=True)

    print("\n" + "=" * 100, flush=True)
    print("ORACLE CEILING -- raw structures", flush=True)
    print("=" * 100, flush=True)
    rows = []
    for nm, (lv, de, cost, w) in built.items():
        p = move_profile(lv, None, horizons=(5, 10, 21), round_trip_bp=cost)
        for _, r in p.iterrows():
            rows.append({"structure": nm, "cost_bp": cost, **r.to_dict()})
    orc = pd.DataFrame(rows)
    print(orc[["structure", "cost_bp", "horizon", "n", "mean_abs_bp",
               "oracle_net_bp", "p_beat_cost", "sd_bp"]].round(3).to_string(index=False),
          flush=True)
    orc.to_csv(DATA / "oracle_meeting_indexed.csv", index=False)

    # ------------------------------------------------ the residual (the kink)
    print("\n" + "=" * 100, flush=True)
    print("THE KINK ON MEETING-INDEXED LEGS -- residual after the meeting-step fit",
          flush=True)
    print("=" * 100, flush=True)
    m_arr = np.array([pd.Timestamp(m) for m in meetings])
    rows = []
    for lam in (1.0, 10.0, 100.0, 1e5):
        resid = pd.DataFrame(np.nan, index=wide.index, columns=wide.columns)
        for d in wide.index:
            row = wide.loc[d].dropna()
            legs = [k for k in row.index if rank.at[d, k] <= MAX_RANK]
            if len(legs) < 6:
                continue
            lo = min(win[k][0] for k in legs)
            hi = max(win[k][1] for k in legs)
            sel = np.flatnonzero((m_arr >= pd.Timestamp(lo)) & (m_arr < pd.Timestamp(hi)))
            if sel.size == 0:
                continue
            W = np.vstack([exp[k][sel] for k in legs])
            y = row[legs].to_numpy(dtype=float) * 100.0
            resid.loc[d, legs] = solve_smooth_path(y, W, lam=float(lam))["resid"]
        out = {"lam": lam}
        for nm, (legs_list, w, cost) in sets.items():
            lv = {}
            for legs in legs_list:
                if any(l not in resid.columns for l in legs):
                    continue
                ok = np.ones(len(wide), dtype=bool)
                for l in legs:
                    ok &= (rank[l] <= MAX_RANK).fillna(False).to_numpy()
                lv["-".join(legs)] = (sum(x * resid[l]
                                          for x, l in zip(w, legs))).where(ok)
            lv = pd.DataFrame(lv)
            p = move_profile(lv, None, horizons=(21,), round_trip_bp=cost).iloc[0]
            out[f"{nm} sd"] = float(lv.stack().std())
            out[f"{nm} oracle"] = p["oracle_net_bp"]
            out[f"{nm} pbeat"] = p["p_beat_cost"]
        rows.append(out)
        print(f"  lam={lam:<8g} " + "  ".join(
            f"{nm}: sd {out[f'{nm} sd']:5.2f} oracle {out[f'{nm} oracle']:+6.2f}"
            for nm in sets), flush=True)
    sw = pd.DataFrame(rows)
    sw.to_csv(DATA / "residual_meeting_indexed.csv", index=False)

    print("\nBEST ORACLE ACROSS THE SWEEP, net of cost:", flush=True)
    for nm in sets:
        print(f"  {nm:18s} {sw[f'{nm} oracle'].max():+7.3f} bp "
              f"(cost {sets[nm][2]}bp)", flush=True)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
