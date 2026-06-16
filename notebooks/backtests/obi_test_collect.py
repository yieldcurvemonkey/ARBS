"""Quick test: collect snapshots from Kalshi, reconstruct, save."""
import sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from OBI.kalshi_lob.collector import KalshiLOBCollector
from OBI.kalshi_lob.storage import LOBStorage
from OBI.kalshi_lob.reconstructor import reconstruct_date

storage = LOBStorage()
c = KalshiLOBCollector(storage=storage)

print("Discovering markets...")
tickers = c.discover_active_markets()
print(f"Found {len(tickers)} markets")

print("\nFetching snapshots for first 30 markets...")
found = 0
for t in tickers[:30]:
    rows = c.fetch_snapshot(t)
    if rows:
        storage.buffer_snapshot(rows)
        found += 1
        print(f"  {t}: {len(rows)} levels")

print(f"\n{found}/30 markets with book depth")
today = datetime.date.today()
storage.flush(today)

print(f"\nData saved. Checking storage...")
snaps = storage.read_snapshots(today)
print(f"Snapshots: {len(snaps)} rows")
if not snaps.empty:
    print(f"Markets: {snaps['market_ticker'].nunique()}")
    print(f"Sample:")
    print(snaps.head(10).to_string(index=False))

    print("\nReconstructing LOB...")
    lob = reconstruct_date(storage, today, emit_every_delta=False)
    print(f"LOB: {len(lob)} rows")
    if not lob.empty:
        print(lob.head(10).to_string(index=False))

print("\nStorage status:")
for stream in ["deltas", "snapshots", "trades", "lob"]:
    dates = storage.list_dates(stream)
    print(f"  {stream}: {len(dates)} dates")

print("DONE")
