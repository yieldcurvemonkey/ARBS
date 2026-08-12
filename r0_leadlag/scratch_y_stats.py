"""Summarise the per-(root, UTC day) stats JSONs written by build_y_mbo.py --stage cache."""
import glob, json, os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
rows = []
for f in sorted(glob.glob(os.path.join(HERE, "cache_y_mbo", "*", "*.stats.json"))):
    rows.append(json.load(open(f)))
df = pd.DataFrame(rows)
for c in ("combo_T_volume", "outright_T_volume", "side_N_volume", "side_A_volume",
          "side_B_volume", "unmapped_T_volume"):
    if c not in df:
        df[c] = 0
df = df.fillna(0)
g = df.groupby("root").agg(
    n_utc_days=("utc_day", "nunique"),
    first_day=("utc_day", "min"),
    last_day=("utc_day", "max"),
    n_records=("n_records", "sum"),
    T_volume=("T_volume", "sum"),
    F_volume=("F_volume", "sum"),
    outright_T=("outright_T_volume", "sum"),
    combo_T=("combo_T_volume", "sum"),
    sideN=("side_N_volume", "sum"),
    sideB=("side_B_volume", "sum"),
    sideA=("side_A_volume", "sum"),
    unmapped=("unmapped_T_volume", "sum"),
)
g["F/T"] = (g["F_volume"] / g["T_volume"]).round(4)
g["combo_share"] = (g["combo_T"] / g["T_volume"]).round(4)
g["sideN_share_of_outright"] = (g["sideN"] / g["outright_T"]).round(4)
g["net_B_minus_A"] = g["sideB"] - g["sideA"]
pd.set_option("display.width", 250)
print(g.to_string())
print()
print("TOTAL records scanned:", f"{int(df['n_records'].sum()):,}")
print("TOTAL T volume:", f"{int(df['T_volume'].sum()):,}")
g.to_csv(os.path.join(HERE, "data", "y_root_stats.csv"))
