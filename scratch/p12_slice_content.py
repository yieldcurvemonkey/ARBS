import io, sys, requests
import pandas as pd, pyzipper
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
from SDRUtils.data.builder import DTCCFetcher

f = DTCCFetcher()
pd.set_option("display.width", 240)

for ds in ["2026_06_16_100", "2026_06_16_500", "2026_06_16_900", "2026_06_16_1200"]:
    u, h = f._get_dtcc_url_and_header("CFTC", "RATES", ds)
    r = requests.get(u, headers=h, timeout=120)
    if r.status_code != 200:
        print(ds, "HTTP", r.status_code); continue
    buf = io.BytesIO(r.content)
    with pyzipper.AESZipFile(buf) as z:
        for info in z.infolist():
            print(f"{ds}: member={info.filename} zip_date_time={info.date_time} "
                  f"size={info.file_size}")
    buf.seek(0)
    dfs = f._extract_dataframes_from_zip(buf, convert_key_into_dt=False, use_pyarrow=True)
    for k, df in dfs.items():
        print(f"   rows={len(df)} cols={len(df.columns)}")
        extra = [c for c in df.columns if c not in
                 pd.read_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_zip/2026_06_16_UNFILTERED.parquet").columns]
        print("   columns not in cumulative file:", extra)
        ev = pd.to_datetime(df["Event timestamp"], utc=True, errors="coerce")
        print("   Event timestamp span:", ev.min(), "..", ev.max())
        print("   Action type:", dict(df["Action type"].value_counts()))
        break
    print()
