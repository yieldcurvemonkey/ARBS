"""Deep dive on outlier FOMC trades — payment fields."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import nest_asyncio; nest_asyncio.apply()
import pandas as pd, numpy as np

df = pd.read_parquet(os.path.join(os.path.dirname(__file__), '_precomputed_trades.parquet'))
df['fixed_rate'] = pd.to_numeric(df['fixed_rate'], errors='coerce')
df['notional'] = pd.to_numeric(df['notional'], errors='coerce')
df['other_payment_amount'] = pd.to_numeric(df.get('other_payment_amount'), errors='coerce')

fomc = df[df['special_tenor_type'].astype(str) == 'FOMC'].copy()
D2D = {'BGCD', 'BILT'}

ff_mask = fomc['upi_underlier_name'].astype(str).str.upper().str.contains('FEDERAL FUNDS')
ff = fomc[ff_mask]
ff_d2d = ff[ff['platform_identifier'].isin(D2D)]

# 1) The exact 3.524 prints on BILT
print("=== EXACT 3.524 PRINTS (FF D2D) ===")
outliers = ff_d2d[ff_d2d['fixed_rate'].between(0.03520, 0.03530)]
print(f"Count: {len(outliers)}")

if outliers.empty:
    print("No FF D2D at 3.524. Checking ALL fomc at this level...")
    outliers = fomc[fomc['fixed_rate'].between(0.03520, 0.03530)]
    print(f"ALL FOMC at 3.52x: {len(outliers)}")

for i, (_, r) in enumerate(outliers.head(5).iterrows()):
    print(f"\n--- Trade {i+1} ---")
    for col in ['execution_timestamp', 'trade_id', 'notional', 'fixed_rate',
                'other_payment_type', 'other_payment_amount',
                'package_indicator', 'package_transaction_spread',
                'platform_identifier', 'block_trade_election_indicator',
                'upi_underlier_name', 'tenor_label', 'effective_date',
                'expiration_date', 'cleared', 'event_action']:
        val = r.get(col, 'N/A')
        if col == 'fixed_rate' and pd.notna(val):
            val = f"{val*100:.4f}pct"
        elif col == 'notional' and pd.notna(val):
            val = f"${val/1e6:.0f}M"
        elif col == 'other_payment_amount' and pd.notna(val):
            val = f"${val:,.2f}"
        print(f"  {col:>35}: {val}")

# 2) ALL FF D2D with upfront payment
print("\n\n=== ALL FF D2D WITH UPFRONT PAYMENT (UFRO) ===")
has_pmt = ff_d2d[
    (ff_d2d['other_payment_type'].astype(str).str.contains('UFRO', na=False)) |
    (ff_d2d['other_payment_amount'].notna() & (ff_d2d['other_payment_amount'] != 0))
]
print(f"Count: {len(has_pmt)}")
for _, r in has_pmt.iterrows():
    ts = str(r['execution_timestamp'])[:19]
    rate = f"{r['fixed_rate']*100:.3f}pct" if pd.notna(r['fixed_rate']) else 'N/A'
    not_s = f"${r['notional']/1e6:.0f}M"
    pmt_type = r.get('other_payment_type', '')
    pmt_amt = r.get('other_payment_amount', 0)
    pmt_s = f"${pmt_amt:,.2f}" if pd.notna(pmt_amt) and pmt_amt != 0 else "none"
    print(f"  {ts}  {rate}  {not_s}  pmt_type={pmt_type}  pmt_amt={pmt_s}  {r['platform_identifier']}")

# 3) All FF (not just D2D) with UFRO payment
print("\n\n=== ALL FF FOMC WITH UPFRONT PAYMENT ===")
has_pmt_all = ff[
    (ff['other_payment_type'].astype(str).str.contains('UFRO', na=False)) |
    (ff['other_payment_amount'].notna() & (ff['other_payment_amount'] != 0))
]
print(f"Count: {len(has_pmt_all)}")
for _, r in has_pmt_all.iterrows():
    ts = str(r['execution_timestamp'])[:19]
    rate = f"{r['fixed_rate']*100:.3f}pct" if pd.notna(r['fixed_rate']) else 'N/A'
    not_s = f"${r['notional']/1e6:.0f}M"
    pmt_type = r.get('other_payment_type', '')
    pmt_amt = r.get('other_payment_amount', 0)
    pmt_s = f"${pmt_amt:,.2f}" if pd.notna(pmt_amt) and pmt_amt != 0 else "none"
    d2d = "D2D" if r['platform_identifier'] in D2D else "D2C"
    print(f"  {ts}  {rate}  {not_s}  pmt={pmt_s} ({pmt_type})  {r['platform_identifier']}  {d2d}")

# 4) SOFR FOMC with the 3.524 rate — are THESE the ones on BILT?
print("\n\n=== ALL FOMC AT 3.524 ON BILT (any index) ===")
bilt_524 = fomc[(fomc['fixed_rate'].between(0.03520, 0.03530)) & (fomc['platform_identifier'] == 'BILT')]
print(f"Count: {len(bilt_524)}")
for _, r in bilt_524.iterrows():
    ts = str(r['execution_timestamp'])[:19]
    idx = 'FF' if 'FEDERAL' in str(r['upi_underlier_name']).upper() else 'SOFR'
    pmt_type = r.get('other_payment_type', '')
    pmt_amt = r.get('other_payment_amount', 0)
    pmt_s = f"${pmt_amt:,.2f}" if pd.notna(pmt_amt) and pmt_amt != 0 else "none"
    pkg_spread = r.get('package_transaction_spread', '')
    pkg_s = f"spread={pkg_spread}" if pd.notna(pkg_spread) else ""
    print(f"  {ts}  {r['fixed_rate']*100:.4f}pct  ${r['notional']/1e6:.0f}M  {idx}  pmt={pmt_s} ({pmt_type})  {pkg_s}")
