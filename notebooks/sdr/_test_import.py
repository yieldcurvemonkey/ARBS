import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import _usd_swaps_common as sdr
print('sdr loaded OK')
import datetime
START = datetime.datetime(2025, 4, 10, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2025, 4, 15, 23, 59, 59, tzinfo=datetime.timezone.utc)
df = sdr.load_usd_swaps(START, END)
print(f'Loaded {len(df)} trades from {df["execution_date"].nunique()} trading days')
print(f'Total DV01: {sdr.format_dv01(df["dv01"].sum())}')
print(f'Date range: {df["execution_date"].min()} to {df["execution_date"].max()}')
