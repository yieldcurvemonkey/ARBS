"""Check outlier FOMC trades for other_payment fields."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import nest_asyncio; nest_asyncio.apply()
import pandas as pd, numpy as np
pd.set_option('display.width', 220)

df = pd.read_parquet(os.path.join(os.path.dirname(__file__), '_precomputed_trades.parquet'))
df['fixed_rate'] = pd.to_numeric(df['fixed_rate'], errors='coerce')
df['notional'] = pd.to_numeric(df['notional'], errors='coerce')
df['other_payment_amount'] = pd.to_numeric(df.get('other_payment_amount'), errors='coerce')

fomc = df[df['special_tenor_type'].astype(str) == 'FOMC'].copy()

def classify_index(upi):
    s = str(upi).upper()
    if 'FEDERAL FUNDS' in s:
        return 'FF'
    if 'SOFR' in s:
        return 'SOFR'
    return 'OTHER'
fomc['idx'] = fomc['upi_underlier_name'].apply(classify_index)

# Payment columns
payment_cols = [c for c in df.columns if any(k in c.lower() for k in ['payment', 'spread', 'package_t'])]
print("=== PAYMENT-RELATED COLUMNS ===")
for col in payment_cols:
    nonnull = fomc[col].dropna()
    nonnull = nonnull[nonnull.astype(str).str.strip() != '']
    if len(nonnull) > 0:
        print(f"  {col}: {len(nonnull)} non-null")
        print(f"    Values: {nonnull.unique()[:15]}")
    else:
        print(f"  {col}: all null/empty")
print()

# Find the 3.524% outliers
print("=== JUN26 OUTLIER TRADES (rate ~3.52%) ===")
outliers = fomc[fomc['fixed_rate'].between(0.0350, 0.0355)]
print(f"Found {len(outliers)} trades at ~3.52%")
print()

for i, (_, r) in enumerate(outliers.iterrows()):
    print(f"--- Outlier {i+1} ---")
    for col in ['execution_timestamp', 'trade_id', 'notional', 'fixed_rate',
                 'other_payment_type', 'other_payment_amount',
                 'package_indicator', 'package_transaction_spread',
                 'platform_identifier', 'block_trade_election_indicator',
                 'upi_underlier_name', 'tenor_label', 'effective_date',
                 'expiration_date', 'cleared', 'idx']:
        val = r.get(col, 'N/A')
        if col == 'fixed_rate' and pd.notna(val):
            val = f"{val*100:.4f}%"
        if col == 'notional' and pd.notna(val):
            val = f"${val/1e6:.0f}M"
        if col == 'other_payment_amount' and pd.notna(val) and val != 0:
            val = f"${val:,.2f}"
        print(f"  {col:>35}: {val}")
    print()

# Dec26 outliers at 3.210%
print("=== DEC26 OUTLIER TRADES (rate ~3.21%) ===")
dec_out = fomc[fomc['fixed_rate'].between(0.0320, 0.0322)]
print(f"Found {len(dec_out)} trades at ~3.21%")
print()

for i, (_, r) in enumerate(dec_out.head(2).iterrows()):
    print(f"--- Dec26 Outlier {i+1} ---")
    for col in ['execution_timestamp', 'trade_id', 'notional', 'fixed_rate',
                 'other_payment_type', 'other_payment_amount',
                 'package_indicator', 'package_transaction_spread',
                 'platform_identifier', 'block_trade_election_indicator',
                 'upi_underlier_name', 'cleared', 'idx']:
        val = r.get(col, 'N/A')
        if col == 'fixed_rate' and pd.notna(val):
            val = f"{val*100:.4f}%"
        if col == 'notional' and pd.notna(val):
            val = f"${val/1e6:.0f}M"
        if col == 'other_payment_amount' and pd.notna(val) and val != 0:
            val = f"${val:,.2f}"
        print(f"  {col:>35}: {val}")
    print()

# Compare normal vs outlier payment fields
print("=== NORMAL vs OUTLIER — OTHER PAYMENT COMPARISON ===")
# Normal: Jun26 FF D2D at market levels
D2D = {'BGCD', 'BILT'}
ff_d2d = fomc[(fomc['idx'] == 'FF') & fomc['platform_identifier'].isin(D2D)]

normal = ff_d2d[ff_d2d['fixed_rate'].between(0.0360, 0.0372)].head(5)
outlier = ff_d2d[ff_d2d['fixed_rate'].between(0.0350, 0.0355)]

print("\nNORMAL trades (rate 3.60-3.72%):")
for _, r in normal.iterrows():
    ts = str(r['execution_timestamp'])[:19]
    rate = f"{r['fixed_rate']*100:.3f}%" if pd.notna(r['fixed_rate']) else 'N/A'
    otp = r.get('other_payment_type', 'N/A')
    opa = r.get('other_payment_amount', 'N/A')
    if pd.notna(opa) and opa != 0:
        opa = f"${opa:,.2f}"
    pki = r.get('package_indicator', 'N/A')
    pts = r.get('package_transaction_spread', 'N/A')
    print(f"  {ts}  {rate}  ${r['notional']/1e6:.0f}M  pmt_type={otp}  pmt_amt={opa}  pkg_ind={pki}  pkg_spread={pts}")

print("\nOUTLIER trades (rate ~3.52%):")
for _, r in outlier.iterrows():
    ts = str(r['execution_timestamp'])[:19]
    rate = f"{r['fixed_rate']*100:.3f}%" if pd.notna(r['fixed_rate']) else 'N/A'
    otp = r.get('other_payment_type', 'N/A')
    opa = r.get('other_payment_amount', 'N/A')
    if pd.notna(opa) and opa != 0:
        opa = f"${opa:,.2f}"
    pki = r.get('package_indicator', 'N/A')
    pts = r.get('package_transaction_spread', 'N/A')
    print(f"  {ts}  {rate}  ${r['notional']/1e6:.0f}M  pmt_type={otp}  pmt_amt={opa}  pkg_ind={pki}  pkg_spread={pts}")
