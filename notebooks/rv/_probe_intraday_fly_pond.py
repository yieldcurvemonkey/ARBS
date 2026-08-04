"""The decisive scoping number: how far does a 12m SR3 fly move in 4 hours?

The EOD labs died on one ratio -- E|move| over the holding period against the
round trip. That ratio is what going intraday changes, and it changes it in a
direction that is arithmetic, not empirical:

    the round trip costs the SAME 2.0bp at every frequency,
    but E|move| SHRINKS with the horizon.

So before building an intraday lab the question is simply whether a 4h move of a
wide fly clears 2.0bp. SQU26 / SQU27 / SQU28 are exactly 12 months apart, so
``2*SQU27 - SQU26 - SQU28`` IS a 12m butterfly and the number can be measured
directly rather than extrapolated from an OU fit on daily data.

Three things are measured here, and the second two exist to stop the first from
lying:

1. **The pond.** E|move| of the fly at 4h / 8h / 1d, against a 2.0bp cost.
2. **Roll's effective spread.** ``s = 2*sqrt(-Cov(r_t, r_{t-1}))`` when the
   autocovariance is negative. Bar closes are TRADE prints, so they alternate
   between bid and offer, and that alternation is mechanically mean-reverting.
   If the measured edge is the size of the Roll spread, the edge IS the bounce.
3. **The variance ratio.** ``VR(q) = Var(r_q) / (q * Var(r_1))``. VR < 1 is
   short-horizon reversion; the question is always whether it survives once the
   bounce is accounted for.

Pre-registered expectations, written before running it: the fly's 4h move will
be somewhere near 2bp -- i.e. MARGINAL against the round trip rather than
clearly alive or clearly dead -- and a material part of the 4h autocovariance
will be bid-ask bounce. If the pond is well under 2bp the intraday-horizon study
is over before it starts, which is a complete answer.

Run: conda run -n stir python notebooks/rv/_probe_intraday_fly_pond.py
"""
import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd
import pytz

pd.set_option("display.width", 250, "display.max_columns", 40)



CME_TZ = pytz.timezone("America/Chicago")
TICK_BP = 0.5
FLY_COST_BP = 2.0          # 4 contracts x 0.5bp round trip each
SPREAD_COST_BP = 1.0


def main() -> int:
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP, _to_barchart_symbol

    legs = ["SR3U26", "SR3U27", "SR3U28"]          # 12m spacing
    near = ["SR3U26", "SR3Z26", "SR3H27"]          # 3m spacing, for contrast
    syms = sorted(set(legs + near))
    end = CME_TZ.localize(datetime.datetime(2026, 7, 30, 23, 59))
    start = CME_TZ.localize(datetime.datetime(2022, 8, 26))

    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    bcf = mdp._get_barchart_fetcher(required_concurrency=len(syms) + 1)
    frames = bcf.barchart_timeseries_api(
        barchart_symbols=[_to_barchart_symbol(s) for s in syms],
        start_date=start, end_date=end, interval=240, one_df=False,
        show_tqdm=True)

    px = {}
    for sym, df in (frames.items() if isinstance(frames, dict) else zip(syms, frames)):
        if df is None or len(df) == 0:
            continue
        df = df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.set_index(df.columns[0])
        code = "SR3" + sym[2:] if sym.startswith("SQ") else sym
        px[code] = df.sort_index()["Close"].astype(float) * -100.0 + 10000.0
    wide = pd.DataFrame(px).sort_index()
    print(f"\npanel: {wide.shape[0]} bars x {wide.shape[1]} contracts, "
          f"{wide.index[0]} -> {wide.index[-1]}", flush=True)
    print(f"  bars with every leg present: {int(wide.dropna().shape[0])}", flush=True)

    def fly(a, b, c):
        return (2.0 * wide[b] - wide[a] - wide[c]).dropna()

    structures = {
        "12m fly (U26/U27/U28)": (fly(*legs), FLY_COST_BP),
        "3m fly (U26/Z26/H27)": (fly(*near), FLY_COST_BP),
        "12m spread (U26/U27)": ((wide[legs[1]] - wide[legs[0]]).dropna(), SPREAD_COST_BP),
    }

    print("\n" + "=" * 104)
    print("1. THE POND -- E|move| by horizon, against the round trip")
    print("=" * 104, flush=True)
    rows = []
    for nm, (s, cost) in structures.items():
        for h, lbl in ((1, "4h"), (2, "8h"), (6, "1d"), (30, "5d"), (126, "21d")):
            m = (s.shift(-h) - s).dropna()
            if len(m) < 50:
                continue
            rows.append({"structure": nm, "horizon": lbl, "bars": h, "n": len(m),
                         "mean_abs_bp": float(m.abs().mean()),
                         "sd_bp": float(m.std()),
                         "cost_bp": cost,
                         "oracle_net_bp": float(m.abs().mean()) - cost,
                         "p_beat_cost": float((m.abs() > cost).mean())})
    pond = pd.DataFrame(rows)
    print(pond.round(3).to_string(index=False), flush=True)

    print("\n" + "=" * 104)
    print("2. ROLL EFFECTIVE SPREAD -- how much of the reversion is bid-ask bounce?")
    print("=" * 104, flush=True)
    rows = []
    for nm, (s, cost) in structures.items():
        r = s.diff().dropna()
        cov = float(pd.Series(r).autocorr(lag=1) * r.var())
        roll = 2.0 * np.sqrt(-cov) if cov < 0 else np.nan
        rows.append({"structure": nm, "bar_sd_bp": float(r.std()),
                     "autocorr_lag1": float(pd.Series(r).autocorr(lag=1)),
                     "autocov": cov,
                     "roll_spread_bp": roll,
                     "roll_in_ticks": roll / TICK_BP if roll == roll else np.nan,
                     "cost_bp": cost})
    roll_t = pd.DataFrame(rows)
    print(roll_t.round(3).to_string(index=False), flush=True)
    print("""
  Read this against the round trip. Roll estimates the spread a liquidity TAKER
  pays; if it is comparable to the charged cost, the cost model is honest. If
  the strategy's edge later comes out near the Roll spread, the edge is the
  bounce and not a kink.""", flush=True)

    print("\n" + "=" * 104)
    print("3. VARIANCE RATIO -- is there reversion beyond one bar?")
    print("=" * 104, flush=True)
    rows = []
    for nm, (s, cost) in structures.items():
        r1 = s.diff().dropna()
        v1 = float(r1.var())
        row = {"structure": nm}
        for q in (2, 3, 6, 12, 30):
            rq = (s.shift(-q) - s).dropna()
            row[f"VR({q})"] = float(rq.var() / (q * v1)) if v1 > 0 else np.nan
        rows.append(row)
    vr = pd.DataFrame(rows)
    print(vr.round(3).to_string(index=False), flush=True)
    print("""
  VR < 1 = mean reverting, VR > 1 = trending, VR = 1 = random walk.
  A VR that is depressed at q=2 and recovers by q=6 is the signature of
  microstructure noise, NOT of a tradeable kink.""", flush=True)

    print("\n" + "=" * 104)
    print("4. TIME OF DAY -- 4h bars are not interchangeable")
    print("=" * 104, flush=True)
    s = structures["12m fly (U26/U27/U28)"][0]
    r = s.diff().dropna()
    tod = pd.DataFrame({"hour_ct": r.index.hour, "abs_move": r.abs().to_numpy(),
                        "move": r.to_numpy()})
    agg = tod.groupby("hour_ct").agg(n=("abs_move", "size"),
                                     mean_abs_bp=("abs_move", "mean"),
                                     sd_bp=("move", "std"),
                                     pct_unchanged=("abs_move",
                                                    lambda x: float((x < 1e-9).mean())))
    print(agg.round(3).to_string(), flush=True)

    out = REPO / "notebooks" / "data" / "stir_intraday"
    out.mkdir(parents=True, exist_ok=True)
    pond.to_csv(out / "probe_pond.csv", index=False)
    roll_t.to_csv(out / "probe_roll.csv", index=False)
    vr.to_csv(out / "probe_vr.csv", index=False)
    agg.to_csv(out / "probe_tod.csv")

    print("\n" + "=" * 104)
    print("VERDICT ON WHETHER TO BUILD THE INTRADAY-HORIZON LAB")
    print("=" * 104, flush=True)
    f4 = pond[(pond["structure"].str.startswith("12m fly")) & (pond["horizon"] == "4h")]
    if len(f4):
        o = float(f4["oracle_net_bp"].iloc[0])
        print(f"  12m fly, 4h horizon: E|move| {float(f4['mean_abs_bp'].iloc[0]):.3f}bp "
              f"vs {FLY_COST_BP}bp cost -> oracle {o:+.3f}bp", flush=True)
        print("  -> " + ("PROCEED, it is at least marginal" if o > -0.5
                         else "STOP, the pond is smaller than the boat"), flush=True)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
