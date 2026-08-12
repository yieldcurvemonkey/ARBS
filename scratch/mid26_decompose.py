"""Decompose the 11 hole-print residuals: is the MID wrong, or the INSTRUMENT?

For each residual print, price its OWN effective/maturity at its OWN
curve_timestamp through the same SessionBranchPricer the grid uses. If that
reproduces implied_mid at ~1e-13, the mid path has no convention fault and the
whole residual is that the grid's row for that ET date carries a different
spot date -- the curve's reference date rolls back over the weekend/night, so
the previous ET day's grid row is a different instrument.
"""
import os, sys, pathlib
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")
os.environ.setdefault("ARBS_RL_OMIT_UNUSED_FIXINGS", "1")
REPO = str(pathlib.Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)
import pandas as pd
from SDRUtils.dealer_direction import midprice, snapshot

FILES = ["D:/midgrid_cacheval_2026-04-01.parquet",
         "D:/midgrid_cacheval_2026-06-17.parquet",
         "D:/midgrid_cacheval_2025-04-07.parquet"]
df = pd.concat([pd.read_parquet(f) for f in FILES], ignore_index=True)
ex = df[df["exact_date"]]
nz = ex[ex["err_bp"].abs() > 1e-9].copy()

rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
pricer = rep.pricer
GRID_NOTIONAL = 10_000_000.0

out = []
with pricer.day_scope():
    for r in nz.to_dict("records"):
        curve = pricer.curve_for(r["rate_index"])
        t = pd.Timestamp(r["curve_timestamp"])
        mark = pricer.mark_curve(curve, t)
        h = mark.handle
        ref = pd.Timestamp(h.reference_date()).date()
        grid_spot = h.calendar_advance(h.reference_date(), "2b")
        # (a) the print's OWN dates, at the print's OWN instant
        lp = pricer.price_leg(curve, t, r["effective_date"],
                              r["expiration_date"], GRID_NOTIONAL)
        own = float(lp.mid_pct)
        # (b) what the grid would have published at that instant for this tenor
        gm = h.calendar_advance(grid_spot, r["tenor_label"])
        lg = pricer.price_leg(curve, t, grid_spot, gm, GRID_NOTIONAL)
        out.append({
            "idx": r["rate_index"], "tenor": r["tenor_label"],
            "curve_ts": t, "policy": mark.policy,
            "lag_s": mark.lag_seconds, "ref_date": ref,
            "print_eff": pd.Timestamp(r["effective_date"]).date(),
            "grid_spot": pd.Timestamp(grid_spot).date(),
            "own_err_bp": (own - float(r["implied_mid_pct"])) * 100.0,
            "grid_at_t_err_bp":
                (float(lg.mid_pct) - float(r["implied_mid_pct"])) * 100.0,
            "nearest_err_bp": r["err_bp"],
        })

o = pd.DataFrame(out)
pd.set_option("display.width", 240)
print(o.to_string(index=False))
e = o["own_err_bp"].abs()
print(f"\n(a) print's OWN dates at its OWN instant, through the SAME pricer:")
print(f"    n={len(e)}  median={e.median():.3e} bp  max={e.max():.3e} bp")
print(f"    reproduces implied_mid to <1e-9 bp on {int((e<1e-9).sum())}/{len(e)}")
g = o["grid_at_t_err_bp"].abs()
print(f"\n(b) the GRID's instrument at the same instant: median={g.median():.4f} "
      f"bp  max={g.max():.4f} bp  <- this is the instrument gap alone")
print(f"\n(c) what the chart's nearest-join showed: max={o['nearest_err_bp'].abs().max():.4f} bp")
print("\nspot date the grid used vs the print's own effective date:")
print(o[["curve_ts", "ref_date", "grid_spot", "print_eff"]]
      .drop_duplicates().to_string(index=False))
