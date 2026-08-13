"""Task 4: is there a real DISSEMINATION timestamp anywhere in the raw path?"""
import os, sys, json
from pathlib import Path
import pandas as pd, requests, ujson
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
from SDRUtils.data.builder import DTCCFetcher

pd.set_option("display.width", 240); pd.set_option("display.max_rows", 60)

# 1. cumulative daily CSV columns -> any dissemination-time column?
raw = pd.read_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_zip/2026_06_16_UNFILTERED.parquet")
cands = [c for c in raw.columns if any(k in c.lower() for k in
         ("dissem", "publi", "report", "receiv", "insert", "record", "time"))]
print("cumulative-file columns matching dissem/publish/report/receive/time:")
for c in cands:
    print("   ", c)

# 2. intraday slice listing: does it carry dissemDTM, and how far back?
f = DTCCFetcher()
url = "https://pddata.dtcc.com/ppd/api/slice/CFTC/IR"
hdr = {"accept": "application/json, text/plain, */*",
       "referer": "https://pddata.dtcc.com/ppd/cftcdashboard",
       "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"}
r = requests.get(url, headers=hdr, timeout=60)
print("\nslice listing HTTP", r.status_code, "bytes", len(r.content))
if r.ok:
    js = ujson.loads(r.content.decode("utf-8"))
    d = pd.DataFrame(js)
    print("columns:", list(d.columns), " n slices:", len(d))
    d["dissemDTM"] = pd.to_datetime(d["dissemDTM"], errors="coerce", utc=True)
    print("dissemDTM span:", d["dissemDTM"].min(), "..", d["dissemDTM"].max())
    print("distinct dates:", d["dissemDTM"].dt.date.nunique())
    print(d.sort_values("dissemDTM").head(4).to_string())
    print(d.sort_values("dissemDTM").tail(4).to_string())

# 3. is a 2026-06 intraday slice still downloadable? (retention test)
print("\n=== retention test: try an intraday slice URL for 2026_06_16 ===")
for hh in ["13_390", "14_400"]:
    ds = f"2026_06_16_{hh}"
    u, h = f._get_dtcc_url_and_header(agency="CFTC", asset_class="RATES", date_string=ds)
    try:
        rr = requests.get(u, headers=h, timeout=60, stream=True)
        print(f"  {ds}: HTTP {rr.status_code} len={rr.headers.get('content-length')}")
        rr.close()
    except Exception as e:
        print(f"  {ds}: ERROR {e}")

# 4. local intraday.csv cache
p = Path(r"C:/Users/chris/clee/ARBS/sdr_cache/intraday.csv")
print("\nintraday.csv exists:", p.exists(), p.stat().st_size if p.exists() else "")
if p.exists():
    head = pd.read_csv(p, nrows=5)
    print("  has report_slice:", "report_slice" in head.columns)
    print("  columns sample:", [c for c in head.columns if "slice" in c.lower() or "file" in c.lower()])
