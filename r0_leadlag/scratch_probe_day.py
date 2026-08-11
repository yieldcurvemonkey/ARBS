"""Probe: max sequence per day, day-boundary clock, mtime-vs-S3-LastModified offset,
and the wall cost of fetching ONE full day of slices with a thread pool."""
import io, sys, time, zipfile, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import requests
from email.utils import parsedate_to_datetime

BASE = "https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/slices"

def sess():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    a = requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=2)
    s.mount("https://", a)
    return s

S = sess()

def head(day, seq):
    u = f"{BASE}/CFTC_SLICE_RATES_{day}_{seq}.zip"
    r = S.head(u, timeout=20)
    return r.status_code, r.headers.get("Last-Modified")

DAY = "2026_08_06"

# --- binary search the max sequence ---
lo, hi = 1, 1
while True:
    sc, _ = head(DAY, hi)
    if sc != 200:
        break
    lo = hi
    hi *= 2
    if hi > 100000:
        break
while lo + 1 < hi:
    mid = (lo + hi) // 2
    sc, _ = head(DAY, mid)
    if sc == 200:
        lo = mid
    else:
        hi = mid
print(f"{DAY}: max seq = {lo}")

# --- day boundary: first + last slice Last-Modified ---
for seq in (1, 2, lo - 1, lo):
    sc, lm = head(DAY, seq)
    print(f"  seq={seq:5d} {sc} lastmod={lm}")
sc, lm = head("2026_08_05", 1)
print(f"  2026_08_05 seq=1 {sc} lastmod={lm}")

# --- full-day threaded fetch, measuring wall time + mtime/lastmod offsets ---
def get(seq):
    u = f"{BASE}/CFTC_SLICE_RATES_{DAY}_{seq}.zip"
    for _ in range(3):
        try:
            r = S.get(u, timeout=45)
            break
        except Exception:
            time.sleep(0.5)
    else:
        return seq, None
    if r.status_code != 200:
        return seq, ("HTTP", r.status_code)
    lm = parsedate_to_datetime(r.headers["Last-Modified"])
    z = zipfile.ZipFile(io.BytesIO(r.content))
    info = z.infolist()[0]
    mt = dt.datetime(*info.date_time)
    raw = z.read(info.filename).decode("utf-8", "replace")
    nrows = max(0, len(raw.splitlines()) - 1)
    return seq, (mt, lm, nrows, len(r.content))

t0 = time.time()
with ThreadPoolExecutor(max_workers=24) as ex:
    res = list(ex.map(get, range(1, lo + 1)))
wall = time.time() - t0
ok = [v for _, v in res if v and not (isinstance(v, tuple) and v[0] == "HTTP")]
print(f"\nfetched {len(ok)}/{lo} slices in {wall:.1f}s  ({wall/max(1,lo)*1000:.0f} ms/slice, 24 threads)")
print(f"total bytes = {sum(v[3] for v in ok)/1e6:.1f} MB, total CSV rows = {sum(v[2] for v in ok)}")

# offset: (lastmod_utc) - (mtime interpreted as naive)
offs = [(v[1].replace(tzinfo=None) - v[0]).total_seconds() for v in ok]
offs.sort()
import statistics
print(f"lastmod_UTC - member_mtime : min={offs[0]:.0f}s p50={offs[len(offs)//2]:.0f}s max={offs[-1]:.0f}s")
print(f"  -> constant 14400 (=4h) means mtime is naive America/New_York (EDT)")
resid = [o - 14400 for o in offs]
print(f"resid after 4h: min={min(resid):.0f}s p50={resid[len(resid)//2]:.0f}s p95={resid[int(.95*len(resid))]:.0f}s max={max(resid):.0f}s")
