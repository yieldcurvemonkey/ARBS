"""Every curve-free number in ``package_price.py``'s docstring, computed.

Run::

    set ARBS_SUPABASE_ENABLED=0
    C:/Users/chris/anaconda3/envs/stir/python.exe scratch/ppfix_measure.py extract
    C:/Users/chris/anaconda3/envs/stir/python.exe scratch/ppfix_measure.py report

``extract`` is resumable, one parquet per month, cached on ``D:`` because
``C:`` on this box runs to zero. ``report`` reads only the cache and prints
every table the module docstring quotes, so a number in the docstring that
does not appear in this output has nothing behind it.

WINDOW -- pinned, and it is the same one ``2026-08-11-package-exclusion-skew.md``
uses so the retention numbers are comparable: **2024-03-01 .. 2026-08-07**,
610 tape days, 1,437,838 units. Nothing is sampled; every unit in the window is
counted.

WHAT IS COMPUTED HERE AND WHAT IS NOT. Everything on this page is *reported*
tape -- fees, package prices, the notional x tenor DV01 proxy -- so it needs no
curve and runs over the whole window. The known-answer validation (does the
fee-derived orientation reproduce ``conventions.base_orientation`` on a CURVE
and a FLY?) needs a repriced mid and lives in ``scratch/ppfix_known_answer.py``.
"""
from __future__ import annotations

import os
import pathlib
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import numpy as np
import pandas as pd

CACHE = pathlib.Path(os.environ.get("PPFIX_CACHE", r"D:\ddfix3\ppfix_cache"))
START, END = "2024-03-01", "2026-08-07"


def months(start: str, end: str):
    p = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    for per in p:
        lo = max(per.start_time.date(), pd.Timestamp(start).date())
        hi = min(per.end_time.date(), pd.Timestamp(end).date())
        yield str(per), str(lo), str(hi)


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------

def extract_month(conn, lo: str, hi: str) -> tuple:
    """One row per unit for the whole month, plus one row per PKG-4+ package.

    The unit frame is ``universe.unit_frame``'s own -- nothing is re-derived --
    so the retention denominators here are the same object the coverage report
    totals.
    """
    from SDRUtils.dealer_direction import package_price as pp
    from SDRUtils.dealer_direction.universe import (annotate_legs, load_legs,
                                                    unit_frame)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = load_legs(conn, lo, hi)
    if raw.empty:
        return None, None
    u = unit_frame(raw)
    df = annotate_legs(raw)

    dv01 = pd.to_numeric(df["_dv01_proxy"], errors="coerce").abs()
    df = df.assign(_absdv01=dv01)
    per_unit = df.groupby("_unit_group", sort=False).agg(
        dv01=("_absdv01", "sum"),
        n_legs_chk=("_absdv01", "size"),
    )
    units = u.join(per_unit, how="left")
    units_out = units[["as_of_date", "n_legs", "kind", "exclusion",
                       "is_block", "is_lifecycle", "venue_class", "dv01"]].copy()
    units_out["unit_group"] = units_out.index

    pkg4 = units.index[units["n_legs"] >= 4]
    if len(pkg4) == 0:
        return units_out, None
    sub = df[df["_unit_group"].isin(set(pkg4))]
    gate = pp.tape_gate(sub[list(pp.GATE_COLUMNS)])

    opa = pd.to_numeric(sub["other_payment_amount"], errors="coerce").abs()
    ptp = pd.to_numeric(sub["package_transaction_price"], errors="coerce")
    agg = sub.assign(_opa=opa, _ptp=ptp).groupby("_unit_group", sort=False).agg(
        sum_abs_opa=("_opa", "sum"),
        n_opa_missing=("_opa", lambda s: int(s.isna().sum())),
        ptp=("_ptp", "first"),
    )
    pkg = gate.join(agg, how="left")
    pkg = pkg.join(units_out.drop(columns=["unit_group"]), how="left")
    pkg["unit_group"] = pkg.index
    pkg["package_id"] = units.loc[pkg.index, "package_id"].to_numpy()
    return units_out, pkg


def notation_month(conn, lo: str, hi: str) -> pd.DataFrame:
    """``ptp_price_notation`` lives on the packages table, not the legs."""
    from SDRUtils._swappulse_scripts._tape_tables import PACKAGES_TABLE

    sql = (f"SELECT package_id, as_of_date, ptp_price_notation, "
           f"package_transaction_price, legs_count "
           f"FROM {PACKAGES_TABLE} WHERE as_of_date BETWEEN %(lo)s AND %(hi)s")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params={"lo": lo, "hi": hi})


def do_extract() -> int:
    import gc

    import psycopg2

    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    CACHE.mkdir(parents=True, exist_ok=True)
    conn = psycopg2.connect(resolve_pg_url())
    try:
        for tag, lo, hi in months(START, END):
            up = CACHE / f"units_{tag}.parquet"
            pp_ = CACHE / f"pkg4_{tag}.parquet"
            nt = CACHE / f"nota_{tag}.parquet"
            if up.exists() and pp_.exists() and nt.exists():
                print(f"{tag}: cached", flush=True)
                continue
            units, pkg = extract_month(conn, lo, hi)
            if units is None:
                print(f"{tag}: no rows", flush=True)
                continue
            units.to_parquet(up, index=False)
            if pkg is None:
                pd.DataFrame().to_parquet(pp_)
            else:
                pkg.to_parquet(pp_, index=False)
            notation_month(conn, lo, hi).to_parquet(nt, index=False)
            print(f"{tag}: {len(units)} units, "
                  f"{0 if pkg is None else len(pkg)} PKG-4+", flush=True)
            del units, pkg
            gc.collect()
    finally:
        conn.close()
    return 0


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def _load(prefix: str) -> pd.DataFrame:
    parts = []
    for f in sorted(CACHE.glob(f"{prefix}_*.parquet")):
        d = pd.read_parquet(f)
        if len(d):
            parts.append(d)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def pct(a, b) -> float:
    return 100.0 * float(a) / float(b) if b else float("nan")


def do_report() -> int:
    from SDRUtils.dealer_direction import package_price as pp
    from SDRUtils.dealer_direction import types as T

    units = _load("units")
    pkg = _load("pkg4")
    nota = _load("nota")
    print(f"WINDOW {START} .. {END}   days={units['as_of_date'].nunique()}   "
          f"units={len(units):,}   PKG-4+={len(pkg):,}")
    print()

    tot_dv01 = units["dv01"].sum()
    kept = units["exclusion"].isna()
    print("=== 1. retention, DV01 proxy ===")
    print(f"total DV01                 {tot_dv01:,.0f}")
    print(f"kept DV01                  {units.loc[kept,'dv01'].sum():,.0f}"
          f"   ({pct(units.loc[kept,'dv01'].sum(), tot_dv01):.2f}%)")
    p4 = units["n_legs"] >= 4
    print(f"PKG-4+ DV01                {units.loc[p4,'dv01'].sum():,.0f}"
          f"   ({pct(units.loc[p4,'dv01'].sum(), tot_dv01):.2f}%)")
    print(f"kept, excluding ALL PKG-4+ "
          f"{units.loc[kept & ~p4,'dv01'].sum():,.0f}"
          f"   ({pct(units.loc[kept & ~p4,'dv01'].sum(), tot_dv01):.2f}%)")
    print()

    # --- the split the review asks for --------------------------------------
    ident = pkg["stratum"].isna()
    amb = pkg["stratum"] == pp.EXCL_SIGNS_AMBIGUOUS
    tie = pkg["stratum"] == pp.EXCL_TIEOUT_FAIL
    netzero = tie & pkg["tieout_bps"].notna() & (pkg["tieout_bps"]
                                                 <= pp.TIEOUT_MAX_BPS)
    base = units.loc[kept & ~p4, "dv01"].sum()
    print("=== 2. what the package-price rule recovers, split by whether the "
          "orientation is IDENTIFIED ===")
    rows = [
        ("kept without any PKG-4+ recovery", base),
        ("+ recovered AND identified", pkg.loc[ident, "dv01"].sum()),
        ("+ recovered but AMBIGUOUS (>1 sign class in the gate)",
         pkg.loc[amb, "dv01"].sum()),
        ("  (of which the old gate also let through on net==0)",
         pkg.loc[netzero, "dv01"].sum()),
    ]
    run = base
    for name, v in rows:
        if name.startswith("+"):
            run += v
            print(f"{name:<56s} {v:>18,.0f}   running {pct(run, tot_dv01):6.2f}%")
        elif name.startswith("  "):
            print(f"{name:<56s} {v:>18,.0f}")
        else:
            print(f"{name:<56s} {v:>18,.0f}   {pct(v, tot_dv01):6.2f}%")
    print()
    print(f"HEADLINE  retained DV01, identified only : "
          f"{pct(base + pkg.loc[ident,'dv01'].sum(), tot_dv01):.2f}%")
    print(f"          retained DV01 if ambiguity ignored: "
          f"{pct(base + pkg.loc[ident | amb | netzero, 'dv01'].sum(), tot_dv01):.2f}%")
    print()

    print("=== 3. PKG-4+ by stratum ===")
    s = pkg["stratum"].fillna("(recovered, identified)")
    tab = pkg.assign(s=s).groupby("s").agg(
        units=("dv01", "size"), dv01=("dv01", "sum"))
    tab["units_pct"] = 100.0 * tab["units"] / len(pkg)
    tab["dv01_pct"] = 100.0 * tab["dv01"] / pkg["dv01"].sum()
    print(tab.sort_values("dv01", ascending=False).to_string(
        float_format=lambda x: f"{x:,.2f}"))
    print()

    print("=== 4. the identification statistic on ACCEPTED-BY-TIEOUT units ===")
    scored = pkg[pkg["margin_bps"].notna() & pkg["tieout_bps"].notna()
                 & (pkg["tieout_bps"] <= pp.TIEOUT_MAX_BPS)]
    m = scored["margin_bps"].to_numpy(dtype=float)
    finite = m[np.isfinite(m)]
    if len(finite):
        for q in (5, 10, 25, 50, 75, 90):
            print(f"  margin_bps p{q:<3d} {np.percentile(finite, q):10.4f}")
        for thr in (0.01, 0.05, 0.1, 0.25, 0.5, 1.0):
            print(f"  share with margin < {thr:<5} "
                  f"{pct((finite < thr).sum(), len(finite)):6.2f}%")
        print(f"  EXACT TIES (margin == 0, decided by the solver's lowest-mask "
              f"tie-break): {pct((finite == 0).sum(), len(finite)):.2f}% of "
              f"units, {pct(scored.loc[scored['margin_bps'] == 0, 'dv01'].sum(), scored['dv01'].sum()):.2f}% of their DV01")
    nomargin = pkg["margin_bps"].isna() & pkg["tieout_bps"].notna()
    print(f"  not enumerable (n_legs > {pp.MARGIN_MAX_LEGS}): "
          f"{int(nomargin.sum()):,} units, "
          f"{pct(pkg.loc[nomargin,'dv01'].sum(), pkg['dv01'].sum()):.2f}% of "
          f"PKG-4+ DV01")
    print()

    print("=== 5. margin by leg count -- does identification transfer from "
          "CURVE/FLY to PKG-4+? ===")
    sc = scored.assign(grp=np.where(scored["n_legs"] >= 8, "8+",
                                    scored["n_legs"].astype(int).astype(str)))
    g = sc.groupby("grp").agg(
        n=("margin_bps", "size"),
        tieout_p50=("tieout_bps", "median"),
        margin_p50=("margin_bps", "median"),
        share_ambiguous=("stratum", lambda s: 100.0 * float(
            (s == pp.EXCL_SIGNS_AMBIGUOUS).mean())),
    )
    print(g.to_string(float_format=lambda x: f"{x:,.4f}"))
    print()

    print("=== 6. the tie-out residual distribution and the retention ladder ===")
    t = pkg["tieout_bps"].to_numpy(dtype=float)
    t = t[np.isfinite(t)]
    print("  residual bp percentiles: " + "  ".join(
        f"p{q}={np.percentile(t, q):.3f}" for q in (50, 75, 90, 95, 99)))
    # ELIGIBLE = the population the tie-out gate can even be applied to: a
    # usable package price and a fee on every leg. It is the denominator the
    # docstring's ladder is quoted against, and quoting it against all PKG-4+
    # instead silently mixes in the 26% of DV01 that never reached the gate.
    have = pkg[pkg["tieout_bps"].notna()]
    denom = have["dv01"].sum()
    print(f"  eligible (has a price, has every fee): {len(have):,} units, "
          f"{denom:,.0f} DV01 = {pct(denom, pkg['dv01'].sum()):.1f}% of PKG-4+")
    print("  eligible DV01 kept as the tie-out gate moves (tie-out only, "
          "identification NOT applied):")
    for thr in (0.05, 0.25, 0.5, 1.0, 2.0, 5.0):
        k = have[have["tieout_bps"] <= thr]
        print(f"    {thr:>4} bp -> {pct(k['dv01'].sum(), denom):5.1f}%"
              f"   (of ALL PKG-4+: {pct(k['dv01'].sum(), pkg['dv01'].sum()):5.1f}%)")
    print("  and with the identification gate applied at the same threshold:")
    for thr in (0.05, 0.25, 0.5, 1.0, 2.0, 5.0):
        k = have[(have["tieout_bps"] <= thr)
                 & (have["tieout_bps"] + have["margin_bps"].fillna(-1.0) > thr)]
        print(f"    {thr:>4} bp -> {pct(k['dv01'].sum(), denom):5.1f}%"
              f"   (of ALL PKG-4+: {pct(k['dv01'].sum(), pkg['dv01'].sum()):5.1f}%)")
    print()

    unreachable = have["ptp"].abs() > have["sum_abs_opa"]
    print(f"=== 7. |PTP| > sum|OPA| (no signed sum of the fees can reach the "
          f"price): {pct(unreachable.sum(), len(have)):.1f}% of ELIGIBLE "
          f"PKG-4+ units, {pct((pkg['ptp'].abs() > pkg['sum_abs_opa']).sum(), len(pkg)):.1f}% "
          f"of all PKG-4+ (the second number is inflated: a missing fee is "
          f"dropped from the sum rather than making it unknown)")
    print()

    print("=== 8. the package price by notation (PKG-4+ only) ===")
    n4 = nota[nota["legs_count"] >= 4].copy()
    n4["p"] = pd.to_numeric(n4["package_transaction_price"],
                            errors="coerce").abs()
    key = n4["ptp_price_notation"].astype("object").where(
        n4["ptp_price_notation"].notna(), "(null)")
    tab = n4.assign(k=key).groupby("k").agg(
        n=("p", "size"),
        median_abs_ptp=("p", "median"),
        share_eq_10=("p", lambda s: 100.0 * float((s.round(6) == 10.0).mean())),
        share_at_or_below_floor=("p", lambda s: 100.0 * float(
            (s <= pp.PTP_USD_FLOOR).mean())),
    )
    print(tab.to_string(float_format=lambda x: f"{x:,.2f}"))
    print()
    print(f"(cross-check: packages table says {len(n4):,} PKG-4+ packages, "
          f"the unit frame says {len(pkg):,})")
    print()
    # What each notation actually CONTRIBUTES, which is the claim the floor
    # rests on -- a notation can be 5% of the packages and 0% of the answer.
    j = pkg.merge(nota[["package_id", "ptp_price_notation"]],
                  on="package_id", how="left")
    den = j["dv01"].sum()
    print("  contribution to the recovery, points of PKG-4+ DV01:")
    print(f"  {'notation':>10}  {'n':>7}  {'share':>8}  {'identified':>11}  "
          f"{'ambiguous':>10}  {'refused':>9}")
    for k, g in j.groupby(j["ptp_price_notation"].fillna(-1)):
        gi = g["stratum"].isna()
        ga = g["stratum"] == pp.EXCL_SIGNS_AMBIGUOUS
        lab = "(null)" if k == -1 else f"{int(k)}"
        print(f"  {lab:>10}  {len(g):>7,}  {pct(g['dv01'].sum(), den):7.3f}%  "
              f"{pct(g.loc[gi, 'dv01'].sum(), den):10.3f}p  "
              f"{pct(g.loc[ga, 'dv01'].sum(), den):9.3f}p  "
              f"{pct(g.loc[~(gi | ga), 'dv01'].sum(), den):8.3f}p")
    print(f"  TOTAL identified {pct(j.loc[j['stratum'].isna(), 'dv01'].sum(), den):.3f}%"
          f"  ambiguous "
          f"{pct(j.loc[j['stratum'] == pp.EXCL_SIGNS_AMBIGUOUS, 'dv01'].sum(), den):.3f}%")
    print()

    print("=== 9. who the recovered population is ===")
    for name, mask in (("recovered & identified", ident),
                       ("ambiguous", amb),
                       ("all PKG-4+", pd.Series(True, index=pkg.index))):
        w = pkg[mask]
        if not len(w):
            continue
        d2c = w["venue_class"].astype(str).str.contains("D2C")
        print(f"  {name:<24s} n={len(w):>7,}  "
              f"D2C {pct(w.loc[d2c,'dv01'].sum(), w['dv01'].sum()):5.1f}% of DV01"
              f"  block {pct(w.loc[w['is_block'].fillna(False),'dv01'].sum(), w['dv01'].sum()):5.1f}%"
              f"  lifecycle {pct(w.loc[w['is_lifecycle'].fillna(False),'dv01'].sum(), w['dv01'].sum()):5.1f}%")
    print()
    print("EXCL_UNORIENTABLE constant in use:", T.EXCL_UNORIENTABLE)
    return 0


def do_bigleg() -> int:
    """Is refusing every unit above ``MARGIN_MAX_LEGS`` a measurement or a
    guess?

    The cap exists because the runner-up sign class costs ``2**(n-1)`` to find
    and 31% of ``PKG-4+`` DV01 sits above it. Those units are forced ambiguous,
    so the honest question is what fraction of them WOULD have been identified.
    Enumerated exactly here on a sample of days, out to 24 legs (8.4M classes),
    which is too slow for the gate but fine for one measurement.
    """
    import itertools

    import psycopg2

    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
    from SDRUtils.dealer_direction import package_price as pp
    from SDRUtils.dealer_direction.universe import (annotate_legs, load_legs,
                                                    unit_frame)

    days = ["2024-05-15", "2024-09-18", "2025-01-29", "2025-03-12",
            "2025-06-18", "2025-09-17", "2026-01-28", "2026-06-10"]
    conn = psycopg2.connect(resolve_pg_url())
    rows = []
    try:
        for d in days:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw = load_legs(conn, d, d)
            if raw.empty:
                continue
            u = unit_frame(raw)
            df = annotate_legs(raw)
            big = u.index[(u["n_legs"] > pp.MARGIN_MAX_LEGS)
                          & (u["n_legs"] <= 24)]
            sub = df[df["_unit_group"].isin(set(big))]
            for g, s in sub.groupby("_unit_group", sort=False):
                opa = pd.to_numeric(s["other_payment_amount"],
                                    errors="coerce").abs().to_numpy(float)
                pv = pd.to_numeric(s["package_transaction_price"],
                                   errors="coerce").dropna()
                dv = pd.to_numeric(s["_dv01_proxy"],
                                   errors="coerce").abs().to_numpy(float)
                dv01 = float(np.nansum(dv)) / 2.0
                if (not len(pv) or not np.isfinite(opa).all() or dv01 <= 0
                        or not np.isfinite(dv01)):
                    continue
                ptp = float(pv.iloc[0])
                if abs(ptp) <= pp.PTP_USD_FLOOR:
                    continue
                n = len(opa)
                nets = np.array([opa[0]], dtype=float)
                for v in opa[1:]:
                    nets = np.concatenate([nets - v, nets + v])
                resid = np.abs(np.abs(nets) - abs(ptp)) / dv01
                two = np.partition(resid, 1)[:2]
                best, second = float(two.min()), float(two.max())
                rows.append((d, n, best, second - best,
                             best <= pp.TIEOUT_MAX_BPS,
                             second > pp.TIEOUT_MAX_BPS))
                del nets, resid
    finally:
        conn.close()
    r = pd.DataFrame(rows, columns=["day", "n_legs", "best", "margin",
                                    "tie_ok", "identified"])
    print(f"=== units with {pp.MARGIN_MAX_LEGS} < n_legs <= 24, enumerated "
          f"exactly, {len(days)} sampled days ===")
    print(f"  units {len(r):,}, of which pass the tie-out "
          f"{int(r['tie_ok'].sum()):,}")
    ok = r[r["tie_ok"]]
    if len(ok):
        print(f"  of those, IDENTIFIED (runner-up outside "
              f"{pp.TIEOUT_MAX_BPS} bp): {int(ok['identified'].sum())} "
              f"({pct(ok['identified'].sum(), len(ok)):.2f}%)")
        print(f"  margin bp: p50 {ok['margin'].median():.5f}  "
              f"p90 {ok['margin'].quantile(0.9):.5f}  "
              f"max {ok['margin'].max():.5f}")
    print("  -> the cap costs at most this share of the >20-leg population; "
          "everything else there was unidentifiable anyway.")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    fn = {"extract": do_extract, "report": do_report, "bigleg": do_bigleg}[cmd]
    raise SystemExit(fn())
