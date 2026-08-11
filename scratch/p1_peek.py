import pandas as pd, pyarrow.parquet as pq
fp = r"C:/Users/chris/clee/ARBS/sdr_cache/CFTC/RATES/2026/06/2026-06-15.parquet"
pf = pq.ParquetFile(fp)
print("rows:", pf.metadata.num_rows, "cols:", pf.metadata.num_columns)
cols = [f.name for f in pf.schema_arrow]
for i,c in enumerate(cols):
    print(i, repr(c))
