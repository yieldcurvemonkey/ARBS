"""Probe: DTCC intraday slice URL shape, size, member mtime, and per-slice cost."""
import io, sys, time, zipfile
import requests

BASE = "https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/slices"
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0"})

def try_url(u, method="head"):
    t0 = time.time()
    try:
        r = S.head(u, timeout=20) if method == "head" else S.get(u, timeout=60)
    except Exception as e:
        return None, f"ERR {e}", time.time() - t0
    return r, r.status_code, time.time() - t0

# 1) shape probe -- a handful of candidate sequence encodings for one day
cands = [
    f"{BASE}/CFTC_SLICE_RATES_2026_08_06_1.zip",
    f"{BASE}/CFTC_SLICE_RATES_2026_08_06_100.zip",
    f"{BASE}/CFTC_SLICE_RATES_2026_08_06_500.zip",
    f"{BASE}/CFTC_SLICE_RATES_2026_08_06_10_420.zip",
    f"{BASE}/CFTC_SLICE_RATES_2026_08_06_0.zip",
]
print("=== URL shape probe (HEAD) ===")
for u in cands:
    r, sc, dt = try_url(u)
    ln = r.headers.get("Content-Length") if r is not None else None
    lm = r.headers.get("Last-Modified") if r is not None else None
    print(f"  {sc:>4}  {dt:5.2f}s  len={ln}  lastmod={lm}  {u.split('/')[-1]}")

# 2) full GET of one working slice: inspect members + mtimes + CSV header
print("\n=== GET one slice ===")
for seq in (500, 100, 1):
    u = f"{BASE}/CFTC_SLICE_RATES_2026_08_06_{seq}.zip"
    t0 = time.time()
    try:
        r = S.get(u, timeout=60)
    except Exception as e:
        print("  ERR", e); continue
    dt = time.time() - t0
    print(f"  seq={seq} status={r.status_code} bytes={len(r.content)} t={dt:.2f}s")
    if r.status_code != 200:
        continue
    z = zipfile.ZipFile(io.BytesIO(r.content))
    for info in z.infolist():
        print(f"    member={info.filename} size={info.file_size} mtime={info.date_time}")
    name = z.namelist()[0]
    raw = z.read(name).decode("utf-8", "replace")
    lines = raw.splitlines()
    print(f"    n_lines={len(lines)}")
    print("    HEADER:", lines[0][:2000])
    if len(lines) > 1:
        print("    ROW1  :", lines[1][:2000])
    break
