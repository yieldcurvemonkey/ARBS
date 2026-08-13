"""Larger slice sample for the publication-lag distribution, esp. TERM/ETRM."""
import io, sys, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import pandas as pd, requests, pyzipper
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
from SDRUtils.data.builder import DTCCFetcher

pd.set_option("display.width", 240)
f = DTCCFetcher()
NY = "America/New_York"
sess = requests.Session()


def get_slice(ds):
    u, h = f._get_dtcc_url_and_header("CFTC", "RATES", ds)
    try:
        r = sess.get(u, headers=h, timeout=90)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    buf = io.BytesIO(r.content)
    try:
        with pyzipper.AESZipFile(buf) as z:
            infos = z.infolist()
            if not infos:
                return None
            mt = infos[0].date_time
        pub = pd.Timestamp(dt.datetime(*mt)).tz_localize(NY).tz_convert("UTC")
        buf.seek(0)
        dfs = f._extract_dataframes_from_zip(buf, convert_key_into_dt=False, use_pyarrow=True)
    except Exception:
        return None
    if not dfs:
        return None
    d = next(iter(dfs.values()))
    if d is None or d.empty:
        return None
    d = d[["Dissemination Identifier", "Original Dissemination Identifier", "Action type",
           "Event type", "Event timestamp", "Execution Timestamp", "UPI FISN",
           "Notional currency-Leg 1"]].copy()
    d["_pub"] = pub
    return d


dss = [f"2026_06_16_{s}" for s in range(1, 1400, 2)]
with ThreadPoolExecutor(12) as ex:
    got = [x for x in ex.map(get_slice, dss) if x is not None]
print("slices with rows:", len(got), "of", len(dss), "requested")
s = pd.concat(got, ignore_index=True)
s["_ev"] = pd.to_datetime(s["Event timestamp"], utc=True, errors="coerce")
s["_pub"] = pd.to_datetime(s["_pub"], utc=True)
s["lag"] = (s["_pub"] - s["_ev"]).dt.total_seconds() / 60
print("rows:", len(s))
print("\npublication lag (min) = zip mtime - Event timestamp, by Action type:")
print(s.groupby("Action type")["lag"].describe(percentiles=[.5, .75, .9, .95, .99])
      [["count", "min", "50%", "75%", "90%", "95%", "99%", "max"]].round(2))
print("\nTERM only, by Event type:")
t = s[s["Action type"] == "TERM"]
print(t.groupby("Event type")["lag"].describe(percentiles=[.5, .9, .95])
      [["count", "min", "50%", "90%", "95%", "max"]].round(2))
print("\nETRM / USD / swap FISN:")
e = t[(t["Event type"] == "ETRM") & (t["Notional currency-Leg 1"] == "USD") &
      (t["UPI FISN"].isin(["NA/Swap OIS USD", "NA/Swap Fxd Flt USD", "NA/Swap Flt Flt OIS USD"]))]
print("n =", len(e))
if len(e):
    print(e["lag"].describe(percentiles=[.25, .5, .75, .9, .95]).round(2).to_string())
print("\nNEWT / USD OIS (baseline):")
n = s[(s["Action type"] == "NEWT") & (s["UPI FISN"] == "NA/Swap OIS USD")]
print("n =", len(n)); print(n["lag"].describe(percentiles=[.5, .9, .95, .99]).round(2).to_string())
print("\nnegative lags:", int((s['lag'] < 0).sum()), "of", len(s))
s.to_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/slice_sample_0616_big.parquet", index=False)
