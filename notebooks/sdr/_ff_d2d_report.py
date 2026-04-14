"""Fed Funds FOMC — Interdealer (D2D) Trade-by-Trade Analysis."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import nest_asyncio; nest_asyncio.apply()
import pandas as pd, numpy as np, datetime

pd.set_option('display.width', 200)

df = pd.read_parquet(os.path.join(os.path.dirname(__file__), '_precomputed_trades.parquet'))
df['execution_date'] = pd.to_datetime(df['execution_date']).dt.date
fomc = df[df['special_tenor_type'].astype(str) == 'FOMC'].copy()
fomc['fixed_rate'] = pd.to_numeric(fomc['fixed_rate'], errors='coerce')
fomc['notional'] = pd.to_numeric(fomc['notional'], errors='coerce')

def classify_index(upi):
    s = str(upi).upper()
    if 'FEDERAL FUNDS' in s or 'FED FUND' in s:
        return 'FF'
    if 'SOFR' in s:
        return 'SOFR'
    return 'OTHER'
fomc['idx'] = fomc['upi_underlier_name'].apply(classify_index)

from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES
sched = _CENTRAL_BANK_DATES.get('USD-SOFR-1D', {})
mat_to_label = {mat: label for label, (eff, mat) in sched.items()}
eff_to_label = {eff: label for label, (eff, mat) in sched.items()}

def assign_meeting(row):
    for col in ['expiration_date', 'effective_date']:
        v = pd.to_datetime(row.get(col))
        if pd.notna(v):
            d = v.date()
            lbl = mat_to_label.get(d) or eff_to_label.get(d)
            if lbl:
                return lbl
    return 'UNK'
fomc['mtg'] = fomc.apply(assign_meeting, axis=1)

D2D = {'BGCD', 'ICAU', 'TLAD', 'TRAD', 'DWUS', 'BILT', 'MARF'}
ff = fomc[(fomc['idx'] == 'FF') & (fomc['mtg'] != 'UNK')].copy()
ff['is_d2d'] = ff['platform_identifier'].isin(D2D)
ff_d2d = ff[ff['is_d2d']].copy()

ff_d2d['ts'] = pd.to_datetime(ff_d2d['execution_timestamp'])
# Convert to ET
try:
    ff_d2d['time_et'] = ff_d2d['ts'].dt.tz_convert('America/New_York')
except TypeError:
    ff_d2d['time_et'] = ff_d2d['ts'] - pd.Timedelta(hours=4)
ff_d2d['hour_et'] = ff_d2d['time_et'].dt.hour
ff_d2d['hhmm'] = ff_d2d['time_et'].dt.strftime('%H:%M')

print('=' * 105)
print('  FED FUNDS FOMC — INTERDEALER (D2D) TRADE-BY-TRADE ANALYSIS')
print(f'  {len(ff_d2d)} trades across {ff_d2d["execution_date"].nunique()} sessions')
plat_counts = ff_d2d["platform_identifier"].value_counts().to_dict()
print(f'  Platforms: {plat_counts}')
print('=' * 105)
print()

# ── Every trade ──
print('FULL TRADE LOG (D2D Fed Funds FOMC, Eastern Time)')
print('-' * 105)
hdr = f'{"Date":>12} {"Time":>7} {"Mtg":>7} {"Notional":>10} {"Rate":>8} {"DV01($M)":>9} {"SEF":>6} {"Pkg":>10}'
print(hdr)
print('-' * 105)

for _, r in ff_d2d.sort_values('ts').iterrows():
    rate_s = f'{r["fixed_rate"]*100:.3f}%' if pd.notna(r['fixed_rate']) else '  N/A  '
    not_s = f'${r["notional"]/1e6:.0f}M'
    dv01_s = f'${r["dv01"]/1e6:.0f}M'
    pkg = r['package_type'] if pd.notna(r['package_type']) else 'OUT'
    blk = ' [BLK]' if r.get('block_trade_election_indicator') else ''
    print(f'{str(r["execution_date"]):>12} {r["hhmm"]:>7} {r["mtg"]:>7} {not_s:>10} {rate_s:>8} {dv01_s:>9} {r["platform_identifier"]:>6} {pkg}{blk}')

print()

# ── Intraday timing ──
print('INTRADAY DISTRIBUTION (ET)')
print('-' * 105)
hourly = ff_d2d.groupby('hour_et').agg(
    n=('dv01', 'size'),
    dv01=('dv01', 'sum'),
    notional=('notional', 'sum'),
)
mx = max(hourly['n'].max(), 1)
for h in range(4, 22):
    if h not in hourly.index:
        continue
    row = hourly.loc[h]
    n = int(row['n'])
    bar = '#' * int(n / mx * 40)
    avg_not = row['notional'] / n / 1e6
    print(f'  {h:02d}:00  {n:>3} trds  ${row["notional"]/1e9:.0f}B not  ${row["dv01"]/1e9:.0f}B DV01  avg ${avg_not:.0f}M  {bar}')

print()

# ── By session ──
print('SESSION SUMMARY')
print('-' * 105)
for date in sorted(ff_d2d['execution_date'].unique()):
    day = ff_d2d[ff_d2d['execution_date'] == date].sort_values('ts')
    first = day['hhmm'].iloc[0]
    last = day['hhmm'].iloc[-1]
    meetings = ', '.join(sorted(day['mtg'].unique()))
    rates = day['fixed_rate'].dropna()
    if len(rates) > 1:
        rate_range = f'{rates.min()*100:.3f}-{rates.max()*100:.3f}%'
    elif len(rates) == 1:
        rate_range = f'{rates.iloc[0]*100:.3f}%'
    else:
        rate_range = 'N/A'
    total_not = day['notional'].sum() / 1e6
    print(f'  {date}  {len(day):>2} trds  {first}-{last} ET  ${total_not:.0f}M  {rate_range}  [{meetings}]')

print()

# ── Meeting concentration ──
print('BY MEETING')
print('-' * 105)
for mtg in sorted(ff_d2d['mtg'].unique()):
    sub = ff_d2d[ff_d2d['mtg'] == mtg].sort_values('ts')
    rates = sub['fixed_rate'].dropna()
    plats = ', '.join(sorted(sub['platform_identifier'].unique()))
    lo = f'{rates.min()*100:.3f}' if len(rates) > 0 else 'N/A'
    hi = f'{rates.max()*100:.3f}' if len(rates) > 0 else 'N/A'
    first = sub['hhmm'].iloc[0]
    last = sub['hhmm'].iloc[-1]
    vwap_sub = sub[sub['fixed_rate'].notna() & (sub['dv01'] > 0)]
    vwap = np.average(vwap_sub['fixed_rate'], weights=vwap_sub['dv01']) if len(vwap_sub) > 0 else np.nan
    vwap_s = f'{vwap*100:.3f}%' if not np.isnan(vwap) else 'N/A'
    print(f'  {mtg:>7}  {len(sub):>2} trds  ${sub["dv01"].sum()/1e9:.0f}B DV01  ${sub["notional"].sum()/1e6:.0f}M  VWAP {vwap_s}  {lo}-{hi}%  {first}-{last} ET  [{plats}]')

print()

# ── Trade clusters ──
print('TRADE CLUSTERS (trades within 120s of each other)')
print('-' * 105)
ff_sorted = ff_d2d.sort_values('ts').reset_index(drop=True)
ff_sorted['gap_s'] = ff_sorted['ts'].diff().dt.total_seconds().fillna(9999)
ff_sorted['cluster'] = (ff_sorted['gap_s'] > 120).cumsum()

for cid, cluster in ff_sorted.groupby('cluster'):
    if len(cluster) < 2:
        continue
    time_range = f'{cluster["hhmm"].iloc[0]}-{cluster["hhmm"].iloc[-1]}'
    meetings = sorted(cluster['mtg'].unique())
    rates = cluster['fixed_rate'].dropna()
    platforms = sorted(cluster['platform_identifier'].unique())
    date = cluster['execution_date'].iloc[0]

    mtg_str = '/'.join(meetings)
    if len(rates) <= 5:
        rate_str = ', '.join([f'{r*100:.3f}%' for r in rates])
    else:
        rate_str = f'{rates.min()*100:.3f}-{rates.max()*100:.3f}%'

    multi = '  ** CALENDAR **' if len(meetings) > 1 else ''
    print(f'  {date} {time_range} ET  {len(cluster)} legs  [{mtg_str}]  ${cluster["notional"].sum()/1e6:.0f}M  [{", ".join(platforms)}]{multi}')
    print(f'    Rates: {rate_str}')
    # Show each leg
    for _, leg in cluster.iterrows():
        r_s = f'{leg["fixed_rate"]*100:.3f}%' if pd.notna(leg['fixed_rate']) else 'N/A'
        print(f'      {leg["hhmm"]}  {leg["mtg"]:>7}  ${leg["notional"]/1e6:.0f}M  {r_s}  {leg["platform_identifier"]}')
    print()

# ── Rate evolution through the day ──
print('RATE EVOLUTION BY MEETING (chronological D2D prints)')
print('-' * 105)
for mtg in sorted(ff_d2d['mtg'].unique()):
    sub = ff_d2d[ff_d2d['mtg'] == mtg].sort_values('ts')
    rates_with_time = sub[sub['fixed_rate'].notna()][['execution_date', 'hhmm', 'fixed_rate', 'notional', 'platform_identifier']]
    if rates_with_time.empty:
        continue
    print(f'  {mtg}:')
    for _, r in rates_with_time.iterrows():
        print(f'    {r["execution_date"]} {r["hhmm"]} ET  {r["fixed_rate"]*100:.3f}%  ${r["notional"]/1e6:.0f}M  {r["platform_identifier"]}')
    print()

print('=' * 105)
