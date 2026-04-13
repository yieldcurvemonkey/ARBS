"""FOMC-Dated Swap Trading Activity Report — SOFR vs Fed Funds breakdown."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import nest_asyncio; nest_asyncio.apply()
import pandas as pd, numpy as np, datetime
import _sdr_common as sdr
from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES

pd.set_option('display.max_columns', 20)
pd.set_option('display.width', 200)

# ─── Load + classify ───
df = pd.read_parquet(os.path.join(os.path.dirname(__file__), '_precomputed_trades.parquet'))
df['execution_date'] = pd.to_datetime(df['execution_date']).dt.date
fomc = df[df['special_tenor_type'].astype(str) == 'FOMC'].copy()
fomc['fixed_rate'] = pd.to_numeric(fomc['fixed_rate'], errors='coerce')
fomc['notional'] = pd.to_numeric(fomc['notional'], errors='coerce')

# Classify SOFR vs Fed Funds from UPI underlier
def classify_index(upi):
    s = str(upi).upper()
    if 'FEDERAL FUNDS' in s or 'FED FUND' in s:
        return 'FED_FUNDS'
    if 'SOFR' in s:
        return 'SOFR'
    return 'OTHER'

fomc['rate_index'] = fomc['upi_underlier_name'].apply(classify_index)

# Assign meeting labels
sched = _CENTRAL_BANK_DATES.get('USD-SOFR-1D', {})
mat_to_label = {mat: label for label, (eff, mat) in sched.items()}
eff_to_label = {eff: label for label, (eff, mat) in sched.items()}

def assign_meeting(row):
    exp = pd.to_datetime(row.get('expiration_date'))
    eff = pd.to_datetime(row.get('effective_date'))
    if pd.notna(exp):
        d = exp.date() if hasattr(exp, 'date') else exp
        lbl = mat_to_label.get(d)
        if lbl:
            return lbl
    if pd.notna(eff):
        d = eff.date() if hasattr(eff, 'date') else eff
        lbl = eff_to_label.get(d)
        if lbl:
            return lbl
    return 'UNKNOWN'

fomc['meeting'] = fomc.apply(assign_meeting, axis=1)
known = fomc[fomc['meeting'] != 'UNKNOWN']
sofr_fomc = known[known['rate_index'] == 'SOFR']
ff_fomc = known[known['rate_index'] == 'FED_FUNDS']

# ─── Dynamic fixings + curves ───
CURRENT_SOFR = sdr.get_current_fixing('USD-SOFR-1D')
CURRENT_EFFR = sdr.get_current_fixing('USD-OIS')

curves = sdr.build_fomc_curves()
fomc_meetings = []
for label, (eff, mat) in sorted(sched.items(), key=lambda x: x[1][0]):
    fomc_meetings.append({'meeting_label': label, 'effective_date': eff, 'maturity_date': mat, 'period_days': (mat - eff).days})
fomc_df_sched = pd.DataFrame(fomc_meetings)
rates_df = sdr.price_fomc_meetings(fomc_df_sched, curves)

implied = fomc_df_sched.merge(rates_df, on='meeting_label', how='left')
implied = implied[implied['sofr_implied_rate'].notna() | implied['ois_implied_rate'].notna()].reset_index(drop=True)
implied['sofr_move'] = (implied['sofr_implied_rate'] - CURRENT_SOFR) * 10000
implied['ois_move'] = (implied['ois_implied_rate'] - CURRENT_EFFR) * 10000
implied['basis'] = (implied['sofr_implied_rate'] - implied['ois_implied_rate']) * 10000

D2D = {'BGCD', 'ICAU', 'TLAD', 'TRAD', 'DWUS', 'BILT', 'MARF'}


# ════════════════════════════════════════════════════════
# REPORT
# ════════════════════════════════════════════════════════
def vwap_rate(subset):
    v = subset[subset['fixed_rate'].notna() & (subset['dv01'] > 0)]
    return np.average(v['fixed_rate'], weights=v['dv01']) if len(v) > 0 else np.nan


print('=' * 90)
print('     FOMC-DATED SWAP TRADING ACTIVITY REPORT')
print('     Period: April 1-10, 2026 (8 trading days)')
print('     Source: CFTC SDR (DTCC) | Curves: BARCHART_STIRF-RL')
print('=' * 90)
print()

# ─── 1 ───
print('1. MARKET SNAPSHOT')
print('-' * 90)
print(f'   Current SOFR:  {CURRENT_SOFR*100:.4f}%')
print(f'   Current EFFR:  {CURRENT_EFFR*100:.4f}%')
print(f'   SOFR-EFFR:     {(CURRENT_SOFR - CURRENT_EFFR)*10000:+.1f}bp')
print()
print(f'   Total FOMC-dated trades:    {len(fomc):>6,}  ({len(fomc)/max(len(df),1)*100:.1f}% of all swaps)')
print(f'     SOFR-referenced:          {len(sofr_fomc):>6,}  ({len(sofr_fomc)/max(len(known),1)*100:.1f}% of identified)')
print(f'     Fed Funds-referenced:     {len(ff_fomc):>6,}  ({len(ff_fomc)/max(len(known),1)*100:.1f}% of identified)')
print(f'   Total DV01:                 ${fomc["dv01"].sum()/1e9:.0f}B')
print(f'     SOFR DV01:                ${sofr_fomc["dv01"].sum()/1e9:.0f}B  ({sofr_fomc["dv01"].sum()/max(known["dv01"].sum(),1)*100:.0f}%)')
print(f'     FF DV01:                  ${ff_fomc["dv01"].sum()/1e9:.0f}B  ({ff_fomc["dv01"].sum()/max(known["dv01"].sum(),1)*100:.0f}%)')
print(f'   Total Notional:             ${fomc["notional"].sum()/1e9:.0f}B')
print()

# ─── 2 ───
print('2. IMPLIED RATE TERM STRUCTURE (BARCHART_STIRF)')
print('-' * 90)
hdr = f'{"Meeting":>8}  {"SOFR":>9}  {"OIS(FF)":>9}  {"SOFR mv":>8}  {"OIS mv":>8}  {"Basis":>6}  {"CumSOFR":>8}  {"CumOIS":>8}'
print(hdr)
print(' ' + '-' * 88)
for _, r in implied.iterrows():
    sofr_r = f'{r["sofr_implied_rate"]*100:.3f}%' if pd.notna(r['sofr_implied_rate']) else '   N/A  '
    ois_r = f'{r["ois_implied_rate"]*100:.3f}%' if pd.notna(r['ois_implied_rate']) else '   N/A  '
    sofr_m = f'{r["sofr_move"]:+.1f}bp' if pd.notna(r['sofr_move']) else '   N/A'
    ois_m = f'{r["ois_move"]:+.1f}bp' if pd.notna(r['ois_move']) else '   N/A'
    basis_v = f'{r["basis"]:+.1f}' if pd.notna(r['basis']) else ' N/A'
    cum_s = (CURRENT_SOFR - r['sofr_implied_rate']) / 0.0025 if pd.notna(r['sofr_implied_rate']) else float('nan')
    cum_o = (CURRENT_EFFR - r['ois_implied_rate']) / 0.0025 if pd.notna(r['ois_implied_rate']) else float('nan')
    cum_s_str = f'{cum_s:+.1f}' if not np.isnan(cum_s) else '  N/A'
    cum_o_str = f'{cum_o:+.1f}' if not np.isnan(cum_o) else '  N/A'
    print(f'{r["meeting_label"]:>8}  {sofr_r:>9}  {ois_r:>9}  {sofr_m:>8}  {ois_m:>8}  {basis_v:>6}  {cum_s_str:>8}  {cum_o_str:>8}')
print()

# ─── 3 ───
print('3. CALENDAR SPREADS (bps)')
print('-' * 90)
print(f'{"Spread":>20}  {"SOFR":>8}  {"OIS(FF)":>8}  {"Diff":>7}')
print(' ' + '-' * 48)
for i in range(min(len(implied) - 1, 12)):
    c = implied.iloc[i]
    n = implied.iloc[i + 1]
    lbl = f'{c["meeting_label"]}/{n["meeting_label"]}'
    ss = (n['sofr_implied_rate'] - c['sofr_implied_rate']) * 10000 if pd.notna(c['sofr_implied_rate']) and pd.notna(n['sofr_implied_rate']) else np.nan
    os_ = (n['ois_implied_rate'] - c['ois_implied_rate']) * 10000 if pd.notna(c['ois_implied_rate']) and pd.notna(n['ois_implied_rate']) else np.nan
    diff = ss - os_ if not np.isnan(ss) and not np.isnan(os_) else np.nan
    ss_s = f'{ss:+.1f}' if not np.isnan(ss) else '  N/A'
    os_s = f'{os_:+.1f}' if not np.isnan(os_) else '  N/A'
    d_s = f'{diff:+.1f}' if not np.isnan(diff) else ' N/A'
    print(f'{lbl:>20}  {ss_s:>8}  {os_s:>8}  {d_s:>7}')
print()

# ─── 4 ───
def print_meeting_flow(label, subset):
    if subset.empty:
        print(f'   No {label} FOMC trades.')
        return
    for mtg in sorted(subset['meeting'].unique()):
        sub = subset[subset['meeting'] == mtg]
        rates = sub['fixed_rate'].dropna()
        notionals = sub['notional'].dropna() / 1e6
        vw = vwap_rate(sub)
        pkg = sub['package_type'].fillna('OUTRIGHT')
        n_curves = (pkg == 'CURVE').sum()
        n_out = (pkg == 'OUTRIGHT').sum()
        n_d2d = sub[sub['platform_identifier'].isin(D2D)].shape[0]
        n_d2c = len(sub) - n_d2d
        n_blk = int(sub['block_trade_election_indicator'].sum()) if 'block_trade_election_indicator' in sub.columns else 0
        vwap_s = f'{vw*100:.3f}%' if not np.isnan(vw) else 'N/A'
        disp_s = f'{rates.std()*10000:.1f}bp' if len(rates) > 2 else 'N/A'
        daily = sub.groupby('execution_date')['dv01'].agg(['size', 'sum']).sort_values('sum', ascending=False)
        busiest = daily.index[0]
        print(f'   {mtg:>7}  | {len(sub):>4} trds | DV01 ${sub["dv01"].sum()/1e9:.0f}B | Not ${notionals.sum():.0f}M | VWAP {vwap_s} | Disp {disp_s}')
        print(f'           | Out/Crv {n_out}/{n_curves} | D2C/D2D {n_d2c}/{n_d2d} | Blk {n_blk} | Avg ${notionals.mean():.0f}M | Peak {busiest}')


print('4. SOFR-REFERENCED FOMC FLOW BY MEETING')
print('-' * 90)
print_meeting_flow('SOFR-referenced', sofr_fomc)
print()

print('5. FED FUNDS-REFERENCED FOMC FLOW BY MEETING')
print('-' * 90)
print_meeting_flow('Fed Funds-referenced', ff_fomc)
print()

# ─── 6 ───
print('6. SOFR vs FED FUNDS SIDE-BY-SIDE')
print('-' * 90)
meetings = sorted(set(sofr_fomc['meeting'].unique()) | set(ff_fomc['meeting'].unique()))
print(f'{"Mtg":>8}  {"S Trds":>7}  {"FF Trds":>8}  {"S DV01($B)":>11}  {"FF DV01($B)":>12}  {"S VWAP":>9}  {"FF VWAP":>9}  {"Diff":>6}')
print(' ' + '-' * 85)
for mtg in meetings:
    ss = sofr_fomc[sofr_fomc['meeting'] == mtg]
    ff = ff_fomc[ff_fomc['meeting'] == mtg]
    s_vw = vwap_rate(ss)
    f_vw = vwap_rate(ff)
    s_vwap_s = f'{s_vw*100:.3f}%' if not np.isnan(s_vw) else '   N/A'
    f_vwap_s = f'{f_vw*100:.3f}%' if not np.isnan(f_vw) else '   N/A'
    diff = (s_vw - f_vw) * 10000 if not np.isnan(s_vw) and not np.isnan(f_vw) else np.nan
    diff_s = f'{diff:+.1f}' if not np.isnan(diff) else ' N/A'
    print(f'{mtg:>8}  {len(ss):>7}  {len(ff):>8}  {ss["dv01"].sum()/1e9:>11.0f}  {ff["dv01"].sum()/1e9:>12.0f}  {s_vwap_s:>9}  {f_vwap_s:>9}  {diff_s:>6}')
print()

# ─── 7 ───
print('7. VENUE BREAKDOWN BY INDEX')
print('-' * 90)
for idx_label, subset in [('SOFR', sofr_fomc), ('FED FUNDS', ff_fomc)]:
    if subset.empty:
        continue
    subset = subset.copy()
    subset['venue'] = subset['platform_identifier'].apply(lambda x: 'D2D' if str(x) in D2D else 'D2C')
    v = subset.groupby('venue').agg(n=('dv01', 'size'), dv01=('dv01', 'sum'), notional=('notional', 'sum'))
    print(f'   {idx_label}:')
    for venue, row in v.iterrows():
        pct_n = row['n'] / len(subset) * 100
        pct_d = row['dv01'] / subset['dv01'].sum() * 100
        avg_n = row['notional'] / row['n'] / 1e6
        print(f'     {venue}:  {int(row["n"]):>5} trades ({pct_n:.0f}%)  DV01 ${row["dv01"]/1e9:.0f}B ({pct_d:.0f}%)  Avg not ${avg_n:.0f}M')
    print()

# ─── 8 ───
print('8. LARGEST TRADES BY INDEX')
print('-' * 90)
for idx_label, subset in [('SOFR', sofr_fomc), ('FED FUNDS', ff_fomc)]:
    if subset.empty:
        continue
    print(f'   --- {idx_label} ---')
    top = subset.nlargest(8, 'notional')
    for _, r in top.iterrows():
        ts = str(r['execution_timestamp'])[:16]
        rate_s = f'{r["fixed_rate"]*100:.3f}%' if pd.notna(r['fixed_rate']) else '  N/A  '
        pkg = r['package_type'] if pd.notna(r['package_type']) else 'OUTRIGHT'
        blk = ' [BLK]' if r.get('block_trade_election_indicator') else ''
        d2d = ' D2D' if str(r['platform_identifier']) in D2D else ' D2C'
        print(f'   {ts}  {r["meeting"]:>7}  ${r["notional"]/1e6:.0f}M  {rate_s}  {r["platform_identifier"]}  {pkg}{blk}{d2d}')
    print()

# ─── 9 ───
print('9. EXECUTION TIMING (UTC)')
print('-' * 90)
for idx_label, subset in [('SOFR', sofr_fomc.copy()), ('FED FUNDS', ff_fomc.copy())]:
    if subset.empty:
        continue
    subset['hour'] = pd.to_datetime(subset['execution_timestamp']).dt.hour
    hourly = subset.groupby('hour').size()
    mx = max(hourly.max(), 1)
    print(f'   {idx_label}:')
    for h in range(6, 22):
        n = hourly.get(h, 0)
        bar = '#' * int(n / mx * 35)
        if n > 0:
            print(f'     {h:02d}:00  {n:>4}  {bar}')
    print()

# ─── 10 ───
print('10. PACKAGE COMPOSITION BY INDEX')
print('-' * 90)
for idx_label, subset in [('SOFR', sofr_fomc), ('FED FUNDS', ff_fomc)]:
    if subset.empty:
        continue
    pkg = subset['package_type'].fillna('OUTRIGHT').value_counts()
    total = len(subset)
    parts = ', '.join([f'{k}: {v} ({v/total*100:.0f}%)' for k, v in pkg.items()])
    print(f'   {idx_label}: {parts}')
print()

print('=' * 90)
