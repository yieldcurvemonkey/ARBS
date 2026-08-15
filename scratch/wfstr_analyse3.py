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
df["offmkt"] = df["off_market"].fillna(False).astype(bool)
# tenor_display carries '~' for a BROKEN-date swap that tenor_label rounds to a
# standard bucket. That tilde is the whole difference between an instrument the
# grid represents and one it does not.
df["broken"] = df["tenor_display"].fillna("").str.contains("~")
df["std_spot"] = df["spot"] & ~df["broken"] & ~df["offmkt"]

ok = df[df["status"] == "OK"].copy()


def line(g, name):
    a = g["resid_bp"].abs()
    if len(g) == 0:
        return dict(pop=name, n=0)
    return dict(pop=name, n=len(g), median=f"{a.median():.3g}",
                p95=f"{a.quantile(0.95):.4g}", p99=f"{a.quantile(0.99):.4g}",
                max=f"{a.max():.4g}", signed_mean=f"{g['resid_bp'].mean():.3g}")


print("=== rows", len(df), "days", df["day"].nunique(),
      "| CURVE", int((df.kind == 'CURVE').sum()), "FLY", int((df.kind == 'FLY').sum()))

print("\n=== THE STRATIFICATION THAT MATTERS ===")
res = []
for k in ("OUTRIGHT", "CURVE", "FLY"):
    kk = ok[ok["kind"] == k]
    res.append(line(kk, f"{k}  all with a grid mid"))
    res.append(line(kk[kk["exact_dates"]], f"{k}  exact-date (CONTROL)"))
    res.append(line(kk[kk["std_spot"]], f"{k}  STANDARD spot-start on-mkt"))
    res.append(line(kk[kk["std_spot"] & ~kk["exact_dates"]],
                    f"{k}  ...of those, dates != grid"))
    res.append(line(kk[kk["broken"] & kk["spot"]], f"{k}  BROKEN-date (~nY)"))
    res.append(line(kk[~kk["spot"]], f"{k}  forward-start"))
    res.append(line(kk[kk["offmkt"]], f"{k}  off-market"))
print(pd.DataFrame(res).to_string(index=False))

print("\n=== HEADLINE: CURVE+FLY, STANDARD spot-start on-market ===")
d = ok[ok["kind"].isin(["CURVE", "FLY"]) & ok["std_spot"]]
a = d["resid_bp"].abs()
print(dict(n=len(d), median=f"{a.median():.4g}", p95=f"{a.quantile(.95):.4g}",
           p99=f"{a.quantile(.99):.4g}", max=f"{a.max():.4g}",
           exact_share=f"{d['exact_dates'].mean():.1%}"))
dc = d[d["kind"] == "CURVE"]; a = dc["resid_bp"].abs()
print(" CURVE:", dict(n=len(dc), median=f"{a.median():.4g}", p95=f"{a.quantile(.95):.4g}",
                      p99=f"{a.quantile(.99):.4g}", max=f"{a.max():.4g}"))
dfl = d[d["kind"] == "FLY"]; a = dfl["resid_bp"].abs()
print(" FLY:  ", dict(n=len(dfl), median=f"{a.median():.4g}", p95=f"{a.quantile(.95):.4g}",
                      p99=f"{a.quantile(.99):.4g}", max=f"{a.max():.4g}"))

print("\n=== busiest CURVE pairs, STANDARD spot-start on-market ===")
g = dc.groupby("labels").apply(lambda x: pd.Series({
    "n": len(x), "n_exact": int(x["exact_dates"].sum()),
    "med": x["resid_bp"].abs().median(), "p95": x["resid_bp"].abs().quantile(0.95),
    "p99": x["resid_bp"].abs().quantile(0.99),
    "max": x["resid_bp"].abs().max(), "signed_mean": x["resid_bp"].mean()}),
    include_groups=False)
print(g[g["n"] >= 10].sort_values("n", ascending=False).round(5).to_string())

print("\n=== per-day, the three named structures ===")
for lab in ("10Y/30Y", "5Y/10Y", "2Y/10Y"):
    s = dc[dc["labels"] == lab]
    if s.empty:
        continue
    t = s.groupby("day").apply(lambda x: pd.Series({
        "n": len(x), "med": x["resid_bp"].abs().median(),
        "max": x["resid_bp"].abs().max(),
        "mid_lo": x["grid_mid_bp"].min(), "mid_hi": x["grid_mid_bp"].max()}),
        include_groups=False)
    print(f"\n-- {lab} --"); print(t.round(4).to_string())

print("\n=== worst 12 STANDARD spot-start CURVE ===")
w = dc.reindex(dc["resid_bp"].abs().sort_values(ascending=False).index).head(12)
print(w[["day", "labels", "tenor_display", "tenor_years", "eff_off", "mat_off",
         "dev_bps", "print_mid_bp", "grid_mid_bp", "resid_bp", "special"]]
      .round(4).to_string(index=False))

print("\n=== coverage of ALL CURVE prints ===")
allc = df[df["kind"] == "CURVE"]
n = len(allc)


def pc(m, label):
    print(f"  {label:34s} {int(m.sum()):5d}  {m.mean():6.1%}")


print("total CURVE units:", n)
pc(allc["status"] == "TENOR_NOT_IN_GRID", "tenor not on the 21-tenor grid")
pc(allc["status"] == "NO_GRID_MINUTE", "no grid row at curve_timestamp")
pc(~allc["spot"], "forward-start (label is ambiguous)")
pc(allc["broken"], "broken-date (~nY)")
pc(allc["offmkt"], "off-market leg")
pc((allc["status"] == "OK") & allc["std_spot"], "-> GRID-REPRESENTABLE")

print("\n=== same for FLY ===")
allf = df[df["kind"] == "FLY"]
n = len(allf)
print("total FLY units:", n)
for m, lab in [(allf["status"] == "TENOR_NOT_IN_GRID", "tenor not on grid"),
               (allf["status"] == "NO_GRID_MINUTE", "no grid row at ts"),
               (~allf["spot"], "forward-start"), (allf["broken"], "broken-date"),
               (allf["offmkt"], "off-market"),
               ((allf["status"] == "OK") & allf["std_spot"], "-> GRID-REPRESENTABLE")]:
    print(f"  {lab:34s} {int(m.sum()):5d}  {m.mean():6.1%}")

print("\n=== NO_GRID_MINUTE by UTC hour (all kinds) ===")
ng = df[df["status"] == "NO_GRID_MINUTE"].copy()
ng["hr"] = pd.to_datetime(ng["ts"], utc=True).dt.hour
print(ng["hr"].value_counts().sort_index().to_string())

print("\n=== signed residual distribution, STANDARD spot-start CURVE ===")
print(dc["resid_bp"].describe(percentiles=[.01, .05, .25, .5, .75, .95, .99]).round(6).to_string())
