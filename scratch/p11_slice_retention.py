import sys, requests, ujson
import pandas as pd
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
from SDRUtils.data.builder import DTCCFetcher

f = DTCCFetcher()
hdr = {"accept": "application/json, text/plain, */*",
       "referer": "https://pddata.dtcc.com/ppd/cftcdashboard",
       "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"}
js = ujson.loads(requests.get("https://pddata.dtcc.com/ppd/api/slice/CFTC/IR",
                              headers=hdr, timeout=60).content.decode())
d = pd.DataFrame(js)
sample = d.iloc[len(d) // 2]
ds_live = str(sample["fileName"]).split("_RATES_")[1].split(".")[0]
print("live slice date_string from listing:", ds_live, "->", len(ds_live.split("_")), "parts")
u, h = f._get_dtcc_url_and_header("CFTC", "RATES", ds_live)
print("  builder url:", u)
r = requests.get(u, headers=h, timeout=60, stream=True); print("  HTTP", r.status_code); r.close()
print("  s3 fullFilePath:", sample["fullFilePath"])
r = requests.get(sample["fullFilePath"], timeout=60, stream=True); print("  s3 HTTP", r.status_code); r.close()

print("\nretention: same URL shapes for 2026-06-16 (seq 100/500/900)")
for seq in ["100", "500", "900", "0500"]:
    ds = f"2026_06_16_{seq}"
    u, h = f._get_dtcc_url_and_header("CFTC", "RATES", ds)
    r = requests.get(u, headers=h, timeout=60, stream=True)
    print(f"  ppd  {ds}: HTTP {r.status_code}"); r.close()
    s3 = f"https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/slices/CFTC_SLICE_RATES_{ds}.zip"
    r = requests.get(s3, timeout=60, stream=True)
    print(f"  s3   {ds}: HTTP {r.status_code}"); r.close()

print("\nretention: yesterday 2026-08-10 seq 100 (in listing window)")
for seq in ["0100", "100"]:
    ds = f"2026_08_10_{seq}"
    s3 = f"https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/slices/CFTC_SLICE_RATES_{ds}.zip"
    r = requests.get(s3, timeout=60, stream=True)
    print(f"  s3   {ds}: HTTP {r.status_code}"); r.close()
