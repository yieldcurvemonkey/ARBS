"""Can a per-minute CURVE/FLY mid be built from arbs_dd_curve_mid_v1?

Method
------
per-print mid  = structure_price(traded leg rates) - deviation_bps
grid-built mid = structure_price(grid mid_pct at the print's curve_timestamp)

with structure_price = sum(q_i * R_i_pct) * 100, q = (-1,1) CURVE / (-1,2,-1) FLY,
legs sorted (expiration_date, effective_date, trade_id, leg_order).

The OUTRIGHT arm is the known-answer control: it MUST come out at ~1e-13 bp,
otherwise the join/units/ordering are wrong and the CURVE number is meaningless.
"""
import os, sys
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, '.')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2, pandas as pd, numpy as np, datetime, json

pd.set_option('display.width', 200)
pd.set_option('display.max_columns', 50)

DAYS = ["2024-08-02", "2024-09-18", "2024-11-07", "2025-01-29",
        "2025-04-09", "2025-06-18", "2025-08-01", "2025-10-15",
        "2025-12-11", "2026-01-20", "2026-03-19", "2026-04-15",
        "2026-05-20", "2026-06-17", "2026-06-18", "2026-07-29"]

Q = {"OUTRIGHT": (1.0,), "CURVE": (-1.0, 1.0), "FLY": (-1.0, 2.0, -1.0)}

conn = psycopg2.connect(resolve_pg_url())
with conn.cursor() as c:
    c.execute("SET statement_timeout = '600s'")

UNIT_SQL = """
SELECT u.package_id, u.as_of_date, u.kind, u.n_legs, u.rule,
       u.deviation_bps, u.curve_timestamp, u.rate_index, u.curve_name,
       u.snapshot_policy, u.snapshot_lag_seconds, u.exclusion_reason,
       u.dealer_direction, u.structure_dv01, u.special_tenor_type,
       u.execution_timestamp, u.venue_class
FROM arbs_dd_unit_v1 u
WHERE u.as_of_date = %(d)s AND u.rate_index = 'SOFR'
  AND u.rule = 'RATE_VS_MID' AND u.deviation_bps IS NOT NULL
  AND u.curve_timestamp IS NOT NULL AND u.kind = ANY(%(kinds)s)
"""

LEG_SQL = """
SELECT l.package_id, l.as_of_date, l.trade_id, l.leg_order,
       l.tenor_label, l.tenor_display, l.tenor_years, l.forward_start_years,
       l.fixed_rate, l.effective_date, l.expiration_date, l.is_off_market,
       l.special_tenor_type, l.tape_label, l.rate_index_clean
FROM arbs_usd_swap_tape_legs_v3 l
JOIN arbs_dd_unit_v1 u
  ON u.package_id = l.package_id AND u.as_of_date = l.as_of_date
WHERE l.as_of_date = %(d)s AND u.rate_index = 'SOFR'
  AND u.rule = 'RATE_VS_MID' AND u.deviation_bps IS NOT NULL
  AND u.curve_timestamp IS NOT NULL AND u.kind = ANY(%(kinds)s)
ORDER BY l.package_id, l.expiration_date, l.effective_date,
         l.trade_id, l.leg_order
"""

GRID_SQL = """
SELECT tenor_label, ts, mid_pct, effective_date, maturity_date, snapshot_policy
FROM arbs_dd_curve_mid_v1
WHERE rate_index = 'SOFR' AND grid_date BETWEEN %(a)s AND %(b)s
"""

KINDS = ["OUTRIGHT", "CURVE", "FLY"]


def load_day(d):
    dd = datetime.date.fromisoformat(d)
    units = pd.read_sql(UNIT_SQL, conn, params={"d": d, "kinds": KINDS})
    legs = pd.read_sql(LEG_SQL, conn, params={"d": d, "kinds": KINDS})
    grid = pd.read_sql(GRID_SQL, conn,
                       params={"a": dd - datetime.timedelta(days=2),
                               "b": dd + datetime.timedelta(days=2)})
    return units, legs, grid


rows = []
for d in DAYS:
    t0 = datetime.datetime.now()
    units, legs, grid = load_day(d)
    print(f"[{d}] units={len(units)} legs={len(legs)} grid={len(grid)} "
          f"({(datetime.datetime.now()-t0).total_seconds():.1f}s)", flush=True)
    if units.empty:
        continue

    grid["ts"] = pd.to_datetime(grid["ts"], utc=True)
    gmid = grid.set_index(["tenor_label", "ts"])["mid_pct"]
    geff = grid.set_index(["tenor_label", "ts"])["effective_date"]
    gmat = grid.set_index(["tenor_label", "ts"])["maturity_date"]
    tenors_have = set(grid["tenor_label"].unique())

    units["curve_timestamp"] = pd.to_datetime(units["curve_timestamp"], utc=True)
    ukey = units.set_index(["package_id", "as_of_date"])

    for (pid, aod), lg in legs.groupby(["package_id", "as_of_date"], sort=False):
        try:
            u = ukey.loc[(pid, aod)]
        except KeyError:
            continue
        if isinstance(u, pd.DataFrame):
            u = u.iloc[0]
        kind = u["kind"]
        q = Q.get(kind)
        if q is None or len(lg) != len(q):
            rows.append(dict(day=d, package_id=pid, kind=kind, status="NLEG_MISMATCH",
                             n_legs_seen=len(lg)))
            continue
        ts = u["curve_timestamp"]

        r_pct = [float(x) * 100.0 for x in lg["fixed_rate"].tolist()]
        if any(pd.isna(x) for x in r_pct):
            rows.append(dict(day=d, package_id=pid, kind=kind, status="NO_RATE"))
            continue
        traded_bp = sum(w * r for w, r in zip(q, r_pct)) * 100.0
        print_mid_bp = traded_bp - float(u["deviation_bps"])

        labels = [str(x) for x in lg["tenor_label"].tolist()]
        fwd = [float(x or 0.0) for x in lg["forward_start_years"].fillna(0.0)]
        base = dict(day=d, package_id=pid, kind=kind, ts=ts,
                    labels="/".join(labels),
                    tenor_years="/".join(f"{float(x):.4g}" for x in lg["tenor_years"]),
                    fwd_max=max(fwd) if fwd else 0.0,
                    fwd="/".join(f"{x:.4g}" for x in fwd),
                    dealer_direction=u["dealer_direction"],
                    off_market=bool(lg["is_off_market"].any()),
                    tape_label="/".join(str(x) for x in lg["tape_label"].fillna("-")),
                    tenor_display="/".join(str(x) for x in lg["tenor_display"].fillna("-")),
                    special="/".join(str(x) for x in lg["special_tenor_type"].fillna("-")),
                    excl=u["exclusion_reason"], policy=u["snapshot_policy"],
                    dev_bps=float(u["deviation_bps"]),
                    traded_bp=traded_bp, print_mid_bp=print_mid_bp)

        if not set(labels) <= tenors_have:
            rows.append({**base, "status": "TENOR_NOT_IN_GRID"})
            continue
        try:
            g = [float(gmid.loc[(t, ts)]) for t in labels]
            ge = [geff.loc[(t, ts)] for t in labels]
            gm = [gmat.loc[(t, ts)] for t in labels]
        except KeyError:
            rows.append({**base, "status": "NO_GRID_MINUTE"})
            continue
        grid_mid_bp = sum(w * r for w, r in zip(q, g)) * 100.0

        exact = all(pd.Timestamp(a).date() == pd.Timestamp(b).date()
                    for a, b in zip(lg["effective_date"], ge)) and \
                all(pd.Timestamp(a).date() == pd.Timestamp(b).date()
                    for a, b in zip(lg["expiration_date"], gm))
        eff_off = [int((pd.Timestamp(a) - pd.Timestamp(b)).days)
                   for a, b in zip(lg["effective_date"], ge)]
        mat_off = [int((pd.Timestamp(a) - pd.Timestamp(b)).days)
                   for a, b in zip(lg["expiration_date"], gm)]
        rows.append({**base, "status": "OK", "grid_mid_bp": grid_mid_bp,
                     "resid_bp": grid_mid_bp - print_mid_bp,
                     "exact_dates": exact,
                     "eff_off": "/".join(map(str, eff_off)),
                     "mat_off": "/".join(map(str, mat_off)),
                     "max_abs_eff_off": max(abs(x) for x in eff_off),
                     "max_abs_mat_off": max(abs(x) for x in mat_off)})

df = pd.DataFrame(rows)
out = "scratch/wfstr_structmid.parquet"
df.to_parquet(out)
print("\nwrote", out, len(df))
sys.exit(0)

print("\n=== status x kind ===")
print(pd.crosstab(df["kind"], df["status"]).to_string())

ok = df[df["status"] == "OK"].copy()


def stat(g, name):
    a = g["resid_bp"].abs()
    return dict(pop=name, n=len(g), median=a.median(), p95=a.quantile(0.95),
                p99=a.quantile(0.99), max=a.max(), mean_signed=g["resid_bp"].mean())


print("\n=== residual |grid - per-print| in bp ===")
res = []
for k in ("OUTRIGHT", "CURVE", "FLY"):
    kk = ok[ok["kind"] == k]
    if kk.empty:
        continue
    res.append(stat(kk, f"{k} all"))
    res.append(stat(kk[kk["exact_dates"]], f"{k} exact-date"))
    res.append(stat(kk[~kk["exact_dates"]], f"{k} other-date"))
print(pd.DataFrame(res).to_string())

print("\n=== CURVE by tenor pair (all) ===")
cv = ok[ok["kind"] == "CURVE"]
agg = cv.groupby("labels").apply(
    lambda g: pd.Series({"n": len(g), "n_exact": int(g["exact_dates"].sum()),
                         "med": g["resid_bp"].abs().median(),
                         "p95": g["resid_bp"].abs().quantile(0.95),
                         "max": g["resid_bp"].abs().max(),
                         "signed_mean": g["resid_bp"].mean()}),
    include_groups=False).sort_values("n", ascending=False).head(20)
print(agg.to_string())

print("\n=== CURVE exact-date, spot-start only, by pair ===")
cve = cv[cv["exact_dates"]]
agg2 = cve.groupby("labels").apply(
    lambda g: pd.Series({"n": len(g), "med": g["resid_bp"].abs().median(),
                         "max": g["resid_bp"].abs().max()}),
    include_groups=False).sort_values("n", ascending=False).head(20)
print(agg2.to_string())

print("\n=== worst 15 CURVE ===")
print(cv.reindex(cv["resid_bp"].abs().sort_values(ascending=False).index)
        .head(15)[["day", "labels", "tenor_years", "fwd_max", "exact_dates",
                   "eff_off", "mat_off", "dev_bps", "print_mid_bp",
                   "grid_mid_bp", "resid_bp", "special", "off_market"]].to_string())

conn.close()
