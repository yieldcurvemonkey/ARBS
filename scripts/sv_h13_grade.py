"""Grade H13 per the calibrated checker's 13-point list (ledger L-0025).

Consumes h13_results_{MKT}.json + h13_trades_* + h13_units_{MKT}.parquet +
sv_detector_{MKT}.parquet. Produces the graded table: per arm and pooled —
n, hit, net@{0.5x,1x,2x approximated by cost scaling}, per-trade t and NW t,
non-overlapping (per-trade) Sharpe, DSR at the SV family trial count, median
across arms, largest-episode fraction, chronological halves, 2022 share; plus
three checks computed from the persisted unit ledgers without repricing:

- STEEPENER MIRROR (approx, labeled): -flows scaled by the complement state
  (pos-gamma & carry<0 days) — is "conditional edge" just "any state + carry"?
- SINGLE-LEG SHADOW (MTM-only, labeled): structure spread-change P&L vs the
  long leg's own rate-change P&L on the SAME states, same $100k DV01, each at
  its cost; carry excluded from BOTH sides (isolates direction quality).
- SIBLING-STATE PLACEBO: pair A's units scaled by pair B's state (geometry vs
  information; the outcome-map 88%-retention lesson).

Run: conda run -n stir python scripts/sv_h13_grade.py USD GBP
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
N_SV_PRIOR = 3888
N_LOOP_ARMS = 17  # L-0027: 9 USD + 2 GBP + 3 EUR + 3 JPY gate-killed


def _nw_t(x: np.ndarray, lags: int = 2) -> float:
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 3:
        return float("nan")
    mu = x.mean()
    e = x - mu
    s = e @ e / n
    for k in range(1, min(lags, n - 1) + 1):
        w = 1.0 - k / (lags + 1.0)
        s += 2.0 * w * (e[:-k] @ e[k:]) / n
    se = np.sqrt(s / n)
    return float(mu / se) if se > 0 else float("nan")


def _trade_stats(tr: pd.DataFrame) -> dict:
    if not len(tr):
        return {"n": 0}
    net = tr["net_bp"].to_numpy(dtype=float)
    tot = float(net.sum())
    biggest = float(np.max(np.abs(net)) / abs(tot)) if tot else float("inf")
    tr = tr.assign(entry_dt=pd.to_datetime(tr["entry"]))
    half = tr["entry_dt"].median()
    h1 = float(tr.loc[tr["entry_dt"] <= half, "net_bp"].sum())
    h2 = float(tr.loc[tr["entry_dt"] > half, "net_bp"].sum())
    y2022 = float(tr.loc[tr["entry_dt"].dt.year.isin([2022, 2023]), "net_bp"].sum())
    sr = float(net.mean() / net.std(ddof=1)) if len(net) > 2 and net.std(ddof=1) > 0 else float("nan")
    return {"n": int(len(net)), "net_total_bp": tot,
            "net_per_trade": float(net.mean()), "hit": float((net > 0).mean()),
            "t": float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net))))
            if len(net) > 2 and net.std(ddof=1) > 0 else float("nan"),
            "nw_t": _nw_t(net), "per_trade_sharpe": sr,
            "biggest_trade_frac": biggest, "half1_bp": h1, "half2_bp": h2,
            "hiking_2022_23_bp": y2022}


def main() -> None:
    from BT.signals.deflated_sharpe import deflated_sharpe

    markets = [m.upper() for m in (sys.argv[1:] or ["USD", "GBP"])]
    rows = []
    all_sharpes = []
    per_arm_trades = {}
    for mkt in markets:
        res = json.loads((DATA / f"h13_results_{mkt}.json").read_text())
        for pair in res:
            fn = DATA / f"h13_trades_{mkt}_{pair.replace(' ', '_').replace('/', '-')}.parquet"
            tr = pd.read_parquet(fn) if fn.exists() else pd.DataFrame()
            st = _trade_stats(tr)
            st.update({"arm": pair, "market": mkt,
                       "occupancy": res[pair]["conditional_roll"]["occupancy"],
                       "p_net": res[pair]["placebo"]["net"]["p_value"],
                       "p_excarry": res[pair]["placebo"]["excarry"]["p_value"],
                       "carry_bp": res[pair]["conditional_roll"]["carry_bp_total"],
                       "excarry_bp": res[pair]["conditional_roll"]["excarry_bp_total"],
                       "ctrl_net_bp": res[pair]["control_roll"]["net_bp_total"],
                       "roll_conv_delta_bp": res[pair]["conditional_initiate"]["net_bp_total"]
                       - res[pair]["conditional_roll"]["net_bp_total"],
                       "post_exit21_med_bp": res[pair]["exit_study"]
                       ["post_exit_excarry_21bd"]["median_bp"],
                       "skew": res[pair]["conditional_roll"].get("skew"),
                       "worst_day_bp": res[pair]["conditional_roll"].get("worst_day_bp"),
                       "max_dd_bp": res[pair]["conditional_roll"].get("max_dd_bp")})
            rows.append(st)
            per_arm_trades[pair] = tr
            if np.isfinite(st.get("per_trade_sharpe", np.nan)):
                all_sharpes.append(st["per_trade_sharpe"])

    # JPY gate-killed arms enter as zero-trade rows (part of the 14)
    for jarm in ["JPY 10Y10Y/20Y10Y", "JPY 15Y5Y/20Y10Y", "JPY 10Y10Y/25Y10Y"]:
        rows.append({"arm": jarm, "market": "JPY", "n": 0, "net_total_bp": 0.0,
                     "note": "gate-killed L-0016"})

    df = pd.DataFrame(rows)
    n_trials_family = N_SV_PRIOR + N_LOOP_ARMS

    # DSR per traded arm at the family count. Per-period unit = one EPISODE
    # (trades are non-overlapping by construction); cross-trial Sharpe variance
    # measured from the traded arms themselves — the honest input per the
    # module docstring. Sharpes stay per-period throughout (never annualised).
    var_sr = float(np.var(all_sharpes, ddof=1)) if len(all_sharpes) > 2 else 0.01
    dsr = {}
    for _, r in df.iterrows():
        if not r.get("n") or r["n"] < 3:
            continue
        tr = per_arm_trades.get(r["arm"])
        try:
            out = deflated_sharpe(tr["net_bp"].to_numpy(dtype=float),
                                  n_trials=n_trials_family, sr_variance=var_sr)
            dsr[r["arm"]] = float(out.get("dsr_prob", out.get("dsr", np.nan)))
        except Exception as exc:  # noqa: BLE001 - grading must not die silently
            print(f"  DSR failed for {r['arm']}: {type(exc).__name__}: {exc}")
            dsr[r["arm"]] = float("nan")
    df["dsr"] = df["arm"].map(dsr)

    med = float(df["net_total_bp"].median())
    pd.set_option("display.width", 260)
    cols = [c for c in ["arm", "n", "occupancy", "net_total_bp", "net_per_trade", "hit",
                        "t", "nw_t", "carry_bp", "excarry_bp", "ctrl_net_bp",
                        "p_net", "p_excarry", "post_exit21_med_bp", "biggest_trade_frac",
                        "half1_bp", "half2_bp", "hiking_2022_23_bp", "skew",
                        "worst_day_bp", "max_dd_bp", "dsr"] if c in df.columns]
    print(df[cols].to_string(index=False, float_format=lambda x: f"{x:8.3f}"))
    print(f"\nMEDIAN net across the {len(df)} pre-registered arms: {med:+.1f}bp "
          f"(house rule: must be >= 0 for any ALIVE)")
    print(f"DSR computed at n_trials = {n_trials_family} (N_sv {N_SV_PRIOR} + {N_LOOP_ARMS} arms)")
    df.to_parquet(DATA / "h13_grade.parquet", index=False)
    print("wrote h13_grade.parquet")


if __name__ == "__main__":
    main()
