"""Run the STIR RV Screener — Astor Ridge framework on SOFR futures."""
import datetime
import sys
sys.path.insert(0, r"C:\Users\chris\clee\ARBS")

from RVUtils.STIRRVScreener.screener import build_snapshot, STIRRVScreenerConfig

config = STIRRVScreenerConfig(
    zscore_window=65,
    vol_window=20,
    lookback_days=252,
    min_abs_zscore=1.0,
    min_abs_risk_adj_roll=0.2,
)

as_of = datetime.date(2026, 6, 18)
print(f"Building STIR RV snapshot for {as_of}...")
snap = build_snapshot(as_of, config, show_tqdm=True)

print(f"\n{'='*80}")
print(f"STIR RV SCREENER | {snap.as_of} | FOMC in {snap.days_to_fomc}d | IMM roll in {snap.days_to_imm_roll}d")
print(f"{'='*80}")
print(f"Fwd curve: {snap.fwd_curve_slope} | Kinks: {snap.fwd_curve_kinks or 'none'}")
print(f"FOMC blackout: {snap.fomc_blackout_active} | Roll blackout: {snap.roll_blackout_active}")
print(f"Actionable: {snap.n_actionable}")

print(f"\n--- STRIP RATES ---")
for k, v in snap.strip_rates.items():
    print(f"  {k}: {v:.3f}%")

print(f"\n--- TOP TRADES (by composite score) ---")
top = snap.top_trades(15)
print(top.to_string(index=False))

print(f"\n--- BUTTERFLIES (3M gap) ---")
bf3m = snap.by_type("3M Fly")
if not bf3m.empty:
    print(bf3m.to_string(index=False))

print(f"\n--- CALENDAR SPREADS (3M gap) ---")
spd3m = snap.by_type("3M Spd")
if not spd3m.empty:
    print(spd3m.to_string(index=False))

print(f"\n--- ACTIONABLE TRADES ---")
df = snap.to_dataframe()
actionable = df[df["Actionable"]]
if not actionable.empty:
    print(actionable.to_string(index=False))
else:
    print("  No actionable trades (blackout or filters)")
