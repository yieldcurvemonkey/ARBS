"""Where does a day's slice sequence actually end? The '~1,333/day' figure came
from the 24 h listing API, and the probe above got HTTP 200 at seq 1,500."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")

import requests

from SDRUtils.data.builder import DTCCFetcher

f = DTCCFetcher()
sess = requests.Session()


def alive(seq, day="2026_06_16"):
    url, hdr = f._get_dtcc_url_and_header("CFTC", "RATES", f"{day}_{seq}")
    r = sess.get(url, headers=hdr, timeout=60, stream=True)
    ok = r.status_code == 200
    r.close()
    return ok


print("coarse scan:")
for seq in (1500, 2000, 3000, 5000, 8000, 8640, 10000, 20000):
    print(f"  {seq:>6}: {'200' if alive(seq) else '404'}", flush=True)

lo, hi = 1, 20000
if alive(hi):
    print("still alive at 20000 - not bisecting")
else:
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if alive(mid):
            lo = mid
        else:
            hi = mid
    print(f"\nlast live sequence for 2026_06_16: {lo}")

for day in ("2026_06_15", "2026_08_10"):
    lo2, hi2 = 1, 20000
    while lo2 + 1 < hi2:
        mid = (lo2 + hi2) // 2
        if alive(mid, day):
            lo2 = mid
        else:
            hi2 = mid
    print(f"last live sequence for {day}: {lo2}")
