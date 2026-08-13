"""Validate that the intraday slice ZIP member mtime == DTCC dissemination time,
then measure publication lag for a sample of 2026-06-16 slices."""
import io, sys, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import pandas as pd, requests, pyzipper, ujson

sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
from SDRUtils.data.builder import DTCCFetcher

pd.set_option("display.width", 240); pd.set_option("display.max_rows", 100)
f = DTCCFetcher()
HDR = {"accept": "application/json, text/plain, */*",
       "referer": "https://pddata.dtcc.com/ppd/cftcdashboard",
       "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"}
NY = "America/New_York"


def get_slice(ds):
    u, h = f._get_dtcc_url_and_header("CFTC", "RATES", ds)
    try:
        r = requests.get(u, headers=h, timeout=90)
    except Exception as e:
        return ds, None, None
    if r.status_code != 200:
        return ds, None, None
    buf = io.BytesIO(r.content)
    with pyzipper.AESZipFile(buf) as z:
        infos = z.infolist()
        if not infos:
            return ds, None, None
        mt = infos[0].date_time
    mtime_local = pd.Timestamp(dt.datetime(*mt)).tz_localize(NY)
    buf.seek(0)
    dfs = f._extract_dataframes_from_zip(buf, convert_key_into_dt=False, use_pyarrow=True)
    df = next(iter(dfs.values())) if dfs else None
    return ds, mtime_local.tz_convert("UTC"), df


# ---------- 1. KNOWN-ANSWER: today's slices, zip mtime vs listing dissemDTM ----------
js = ujson.loads(requests.get("https://pddata.dtcc.com/ppd/api/slice/CFTC/IR",
                              headers=HDR, timeout=60).content.decode())
listing = pd.DataFrame(js)
listing["dissemDTM"] = pd.to_datetime(listing["dissemDTM"], utc=True)
listing["ds"] = listing["fileName"].str.split("_RATES_").str[1].str.replace(".zip", "", regex=False)
samp = listing.sample(10, random_state=0)
print("=== VALIDATION: zip member mtime (ET->UTC) vs listing dissemDTM ===")
with ThreadPoolExecutor(6) as ex:
    got = list(ex.map(get_slice, samp["ds"].tolist()))
rows = []
for ds, mt, df in got:
    if mt is None:
        print("  ", ds, "fetch failed"); continue
    dd = samp.loc[samp["ds"] == ds, "dissemDTM"].iloc[0]
    rows.append((ds, mt, dd, (mt - dd).total_seconds()))
v = pd.DataFrame(rows, columns=["ds", "zip_mtime_utc", "listing_dissemDTM", "delta_s"])
print(v.to_string(index=False))
print("  |delta| median:", v["delta_s"].abs().median(), "s   max:", v["delta_s"].abs().max(), "s")

# ---------- 2. 2026-06-16 sample ----------
print("\n=== 2026-06-16: publication lag from a 120-slice sample ===")
seqs = list(range(20, 1340, 11))[:120]
dss = [f"2026_06_16_{s}" for s in seqs]
with ThreadPoolExecutor(8) as ex:
    got = list(ex.map(get_slice, dss))
recs = []
ok = 0
for ds, mt, df in got:
    if mt is None or df is None or df.empty:
        continue
    ok += 1
    d = df.copy()
    d["_pub"] = mt
    recs.append(d[["Dissemination Identifier", "Original Dissemination Identifier",
                   "Action type", "Event type", "Event timestamp", "Execution Timestamp", "_pub"]])
print("slices fetched OK:", ok, "of", len(dss))
s = pd.concat(recs, ignore_index=True)
s["_ev"] = pd.to_datetime(s["Event timestamp"], utc=True, errors="coerce")
s["_ex"] = pd.to_datetime(s["Execution Timestamp"], utc=True, errors="coerce")
s["_pub"] = pd.to_datetime(s["_pub"], utc=True)
s["lag_ev_min"] = (s["_pub"] - s["_ev"]).dt.total_seconds() / 60
s["lag_ex_min"] = (s["_pub"] - s["_ex"]).dt.total_seconds() / 60
print("rows:", len(s))
print("\npublication lag vs EVENT timestamp (minutes), by Action type:")
g = s.groupby("Action type")["lag_ev_min"].describe(percentiles=[.5, .9, .95])
print(g[["count", "min", "50%", "90%", "95%", "max"]].round(2))
print("\npublication lag vs EXECUTION timestamp (minutes), by Action type:")
g2 = s.groupby("Action type")["lag_ex_min"].describe(percentiles=[.5, .9, .95])
print(g2[["count", "min", "50%", "90%", "95%", "max"]].round(2))
print("\nnegative lags (publication before event) :", int((s["lag_ev_min"] < 0).sum()))
s.to_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/slice_sample_0616.parquet", index=False)
print("wrote scratch/slice_sample_0616.parquet")
