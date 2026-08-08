import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import pathlib
import pandas as pd
import numpy as np

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 100)
pd.set_option("display.max_rows", 400)

OUT = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "data" / "citivelo_rv"

par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
print("par grid shape", par.shape)
print("index name", par.index.name, "dtype", par.index.dtype)
print("cols", list(par.columns)[:60])
print("head")
print(par.head(3))
print("tail")
print(par.tail(3))

g = pd.read_parquet(OUT / "f7_gate.parquet")
print("\ngate cols", list(g.columns))
sub = g[g["book"] == "all"]
print(sub[["signature", "n_legs", "h", "n", "abs_move_med", "rt_cm2", "rt_costmodel",
           "gross_med", "hit"]].to_string(index=False))

dg = pd.read_parquet(OUT / "f7_gate_diag.parquet")
print("\ndiag")
print(dg.to_string(index=False))
