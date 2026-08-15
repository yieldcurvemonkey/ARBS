import os, sys
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
import pandas as pd, numpy as np
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 60)

df = pd.read_parquet("scratch/wfstr_structmid.parquet")
df["exact_dates"] = df["exact_dates"].map(
    lambda v: bool(v) if isinstance(v, (bool, np.bool_)) else False)
for c in ("resid_bp", "dev_bps", "print_mid_bp", "grid_mid_bp", "fwd_max",
          "max_abs_eff_off", "max_abs_mat_off", "traded_bp"):
    df[c] = pd.to_numeric(df[c], errors="coerce")

df["spot"] = df["fwd_max"].fillna(0.0) <= 1e-9
df["classified"] = df["dealer_direction"].notna()
df["offmkt"] = df["off_market"].fillna(False).astype(bool)

print("=== rows:", len(df), " days:", df['day'].nunique())
print("\n=== status x kind ===")
print(pd.crosstab(df["kind"], df["status"], margins=True).to_string())

print("\n=== sign sanity: traded structure level, spot-start standard pairs ===")
for lab in ("10Y/30Y", "5Y/10Y", "2Y/10Y", "2Y/5Y", "5Y/30Y"):
    s = df[(df["kind"] == "CURVE") & (df["labels"] == lab) & df["spot"] &
           (df["status"] == "OK")]
    if len(s):
        print(f"  {lab:8s} n={len(s):4d} traded_bp med={s['traded_bp'].median():8.2f} "
              f"grid_mid med={s['grid_mid_bp'].median():8.2f} "
              f"print_mid med={s['print_mid_bp'].median():8.2f}")

ok = df[df["status"] == "OK"].copy()


def stat(g, name):
    a = g["resid_bp"].abs()
    if len(g) == 0:
        return dict(pop=name, n=0)
    return dict(pop=name, n=len(g), median=f"{a.median():.3g}",
                p95=round(a.quantile(0.95), 4), p99=round(a.quantile(0.99), 4),
                max=round(a.max(), 4), signed_mean=round(g["resid_bp"].mean(), 4))


print("\n=== residual |grid - per-print| bp, by population ===")
res = []
for k in ("OUTRIGHT", "CURVE", "FLY"):
    kk = ok[ok["kind"] == k]
    res.append(stat(kk, f"{k}: all with a grid mid"))
    res.append(stat(kk[kk["exact_dates"]], f"{k}: exact-date CONTROL"))
    res.append(stat(kk[kk["spot"]], f"{k}: spot-start"))
    res.append(stat(kk[~kk["spot"]], f"{k}: forward-start"))
    res.append(stat(kk[kk["spot"] & ~kk["offmkt"]], f"{k}: spot & on-market"))
    res.append(stat(kk[kk["spot"] & ~kk["offmkt"] & ~kk["exact_dates"]],
                    f"{k}: spot & on-mkt & other-date"))
    res.append(stat(kk[~kk["spot"] | kk["offmkt"]], f"{k}: fwd OR off-market"))
print(pd.DataFrame(res).to_string(index=False))

print("\n=== DRAWABLE population = CURVE/FLY, spot-start, on-market, both legs on grid ===")
draw = ok[ok["kind"].isin(["CURVE", "FLY"]) & ok["spot"] & ~ok["offmkt"]]
a = draw["resid_bp"].abs()
print(dict(n=len(draw), median=float(f"{a.median():.6g}"),
           p95=round(a.quantile(.95), 4), p99=round(a.quantile(.99), 4),
           max=round(a.max(), 4)))
print(" of which exact-date:", int(draw["exact_dates"].sum()),
      f"({draw['exact_dates'].mean():.1%})")

drawc = draw[draw["kind"] == "CURVE"]
a = drawc["resid_bp"].abs()
print("\n CURVE only:", dict(n=len(drawc), median=float(f"{a.median():.6g}"),
                             p95=round(a.quantile(.95), 4),
                             p99=round(a.quantile(.99), 4), max=round(a.max(), 4)))
drawf = draw[draw["kind"] == "FLY"]
a = drawf["resid_bp"].abs()
print(" FLY only:  ", dict(n=len(drawf), median=float(f"{a.median():.6g}"),
                           p95=round(a.quantile(.95), 4),
                           p99=round(a.quantile(.99), 4), max=round(a.max(), 4)))

print("\n=== busiest CURVE pairs, DRAWABLE population ===")
g = drawc.groupby("labels").apply(lambda x: pd.Series({
    "n": len(x), "n_exact": int(x["exact_dates"].sum()),
    "med": x["resid_bp"].abs().median(), "p95": x["resid_bp"].abs().quantile(0.95),
    "p99": x["resid_bp"].abs().quantile(0.99),
    "max": x["resid_bp"].abs().max(), "signed_mean": x["resid_bp"].mean()}),
    include_groups=False)
print(g[g["n"] >= 8].sort_values("n", ascending=False).round(4).to_string())

print("\n=== DRAWABLE CURVE: residual vs how far leg dates are off the grid ===")
d = drawc.copy()
d["bucket"] = np.select(
    [d["exact_dates"],
     (d["max_abs_eff_off"] <= 1) & (d["max_abs_mat_off"] <= 1),
     (d["max_abs_mat_off"] <= 5),
     (d["max_abs_mat_off"] <= 20)],
    ["0 exact", "1 <=1d", "2 <=5d", "3 <=20d"], default="4 >20d")
print(d.groupby("bucket").apply(lambda x: pd.Series({
    "n": len(x), "med": x["resid_bp"].abs().median(),
    "p95": x["resid_bp"].abs().quantile(0.95),
    "max": x["resid_bp"].abs().max()}), include_groups=False).round(4).to_string())

print("\n=== worst 15 DRAWABLE CURVE ===")
w = drawc.reindex(drawc["resid_bp"].abs().sort_values(ascending=False).index).head(15)
print(w[["day", "labels", "tenor_display", "tenor_years", "fwd", "exact_dates",
         "eff_off", "mat_off", "dev_bps", "print_mid_bp", "grid_mid_bp",
         "resid_bp", "special"]].round(4).to_string(index=False))

print("\n=== population shares of ALL CURVE prints (what a chart would face) ===")
allc = df[df["kind"] == "CURVE"]
print("total CURVE units          :", len(allc))
print("  tenor not on grid        :", int((allc['status'] == 'TENOR_NOT_IN_GRID').sum()))
print("  no grid minute at ts     :", int((allc['status'] == 'NO_GRID_MINUTE').sum()))
print("  forward-start            :", int((allc['status'] == 'OK') & 0 + (~allc['spot']).sum()))
print("  off-market               :", int(allc['offmkt'].sum()))
print("  DRAWABLE (spot,on-mkt,ok):", len(drawc), f"({len(drawc)/len(allc):.1%})")

print("\n=== is the residual a bias or noise? DRAWABLE CURVE signed ===")
print(drawc["resid_bp"].describe(percentiles=[.01, .05, .25, .5, .75, .95, .99]).round(5).to_string())

print("\n=== NO_GRID_MINUTE: when do they happen (hour of curve_timestamp UTC) ===")
ng = df[df["status"] == "NO_GRID_MINUTE"].copy()
ng["hr"] = pd.to_datetime(ng["ts"], utc=True).dt.hour
print(ng["hr"].value_counts().sort_index().to_string())
