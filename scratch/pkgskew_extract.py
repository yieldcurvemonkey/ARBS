"""Extract the excluded-vs-retained comparison frames, month by month, resumable.

The split is `universe.unit_frame`'s own -- not re-derived. Per-leg DV01 is
`universe.annotate_legs`' `_dv01_proxy` (sanity.expected_dv01, sentinels zeroed),
which is exactly what the coverage report totals.

Window is PINNED to the 610-day range `_rep_full.txt` was run over, so the four
reference numbers (1,437,838 units / 75.28% kept / 56.96% DV01 kept /
UNORIENTABLE_PKG 272,373 units, 768,706 legs, 39.97%) are reproducible.

Writes to scratch/pkgskew_cache/:
  legs_YYYY-MM.parquet    one row per leg, compact
  units_YYYY-MM.parquet   one row per unit (== one package; legs carry no NULL
                          package_id on v3, verified: 1,437,838 distinct ids)
  spread_YYYY-MM.parquet  (as_of_date, excl_class, exclusion_detail, bucket)
                          annuity-spread DV01 allocation, the robustness cut
"""
from __future__ import annotations

import gc
import hashlib
import json
import os
import pathlib
import sys
import time
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import numpy as np
import pandas as pd

ROOT = pathlib.Path(r"C:\Users\chris\clee\ARBS-dd")
# C: ran to 0 bytes free mid-session (another job on this box); the parquet
# cache lives on D: so a full C: cannot cost the whole extraction.
CACHE = pathlib.Path(os.environ.get("PKGSKEW_CACHE", r"D:\pkgskew_cache"))
CACHE.mkdir(parents=True, exist_ok=True)

START, END = "2024-03-01", "2026-08-07"

# --- tenor grid ------------------------------------------------------------
# Maturity point = forward_start_years + tenor_years. Standard swap pillars sit
# on the RIGHT edge of each band, so a 10Y spot swap lands in "7-10Y".
EDGES = np.array([0.0, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0, np.inf])
LABELS = ["0-1Y", "1-2Y", "2-3Y", "3-5Y", "5-7Y", "7-10Y",
          "10-15Y", "15-20Y", "20-30Y", "30Y+"]


def module_fingerprint() -> dict:
    from SDRUtils.dealer_direction import sanity, universe
    out = {}
    for m in (universe, sanity):
        p = pathlib.Path(m.__file__)
        out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def bucket_of(mat_years: np.ndarray) -> pd.Categorical:
    idx = np.digitize(np.nan_to_num(mat_years, nan=-1.0), EDGES[1:], right=True)
    idx = np.clip(idx, 0, len(LABELS) - 1)
    lab = np.asarray(LABELS, dtype=object)[idx]
    lab = np.where(np.isfinite(mat_years) & (mat_years > 0), lab, None)
    return pd.Categorical(lab, categories=LABELS, ordered=True)


def annuity_spread(notional, tenor, fwd, flat_yield: float):
    """Per-bucket share of the annuity DV01 for each leg. Rows sum to 1.

    ``expected_dv01`` is ``N * (A(f+t) - A(f)) * 1e-4``; the piece falling in a
    band ``[a, b]`` is ``N * (A(min(b, f+t)) - A(max(a, f))) * 1e-4`` when the
    band overlaps ``[f, f+t]``. Sums to the whole by construction.
    """
    from SDRUtils.dealer_direction.sanity import annuity

    f = np.nan_to_num(np.asarray(fwd, dtype=float), nan=0.0)
    f = np.where(f < 0, 0.0, f)
    t = np.asarray(tenor, dtype=float)
    m = f + t
    lo = EDGES[:-1][None, :]
    hi = np.where(np.isinf(EDGES[1:]), 1e6, EDGES[1:])[None, :]
    a = np.maximum(lo, f[:, None])
    b = np.minimum(hi, m[:, None])
    piece = np.where(b > a, annuity(b, flat_yield) - annuity(a, flat_yield), 0.0)
    tot = piece.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        share = np.where(tot > 0, piece / tot, 0.0)
    return share


EXTRA_LEG_COLS = (
    "execution_hour_et", "execution_session", "package_transaction_spread",
    "ptp_group_id", "opa_sign", "ust_cusip", "matched_ust_maturity",
    "is_asset_swap", "is_spreadover", "is_off_market", "risk",
)

PKG_COLS = ("package_id", "opa_sign_confidence", "package_structure",
            "ptp_group_size", "n_package_legs", "dealer_spread_est",
            "confidence_tone", "package_type")


def excl_class(exclusion, detail):
    out = np.full(len(exclusion), "OTHER_EXCL", dtype=object)
    out[pd.isna(exclusion)] = "KEPT"
    unor = (exclusion == "UNORIENTABLE_PKG").to_numpy()
    out[unor & (detail == "PKG-4+").to_numpy()] = "PKG4"
    out[unor & (detail != "PKG-4+").to_numpy()] = "ASSETSWAP"
    return out


def run_chunk(conn, lo, hi, tag):
    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE, PACKAGES_TABLE
    from SDRUtils.dealer_direction import sanity
    from SDRUtils.dealer_direction.universe import (
        LEG_COLUMNS, annotate_legs, unit_frame)

    cols = list(dict.fromkeys(list(LEG_COLUMNS) + list(EXTRA_LEG_COLS)))
    sql = (f"SELECT {', '.join(cols)} FROM {LEGS_TABLE} "
           "WHERE as_of_date BETWEEN %(start)s AND %(end)s "
           "ORDER BY package_id, expiration_date, effective_date, "
           "trade_id, leg_order")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = pd.read_sql(sql, conn, params={"start": lo, "end": hi})
        pkg = pd.read_sql(
            f"SELECT {', '.join(PKG_COLS)} FROM {PACKAGES_TABLE} "
            "WHERE as_of_date BETWEEN %(start)s AND %(end)s",
            conn, params={"start": lo, "end": hi})

    # --- the pipeline's own split, unmodified -----------------------------
    u = unit_frame(raw)                       # index == _unit_group
    df = annotate_legs(raw)                   # per-leg predicates + _dv01_proxy

    u["excl_class"] = excl_class(u["exclusion"], u["exclusion_detail"])

    # --- per-leg frame -----------------------------------------------------
    ten = pd.to_numeric(df["tenor_years"], errors="coerce").to_numpy(float)
    fwd = np.nan_to_num(
        pd.to_numeric(df["forward_start_years"], errors="coerce").to_numpy(float),
        nan=0.0)
    fwd = np.where(fwd < 0, 0.0, fwd)
    mat = fwd + ten

    legs = pd.DataFrame({
        "as_of_date": pd.to_datetime(df["as_of_date"]).dt.date,
        "unit": df["_unit_group"].to_numpy(),
        "excl_class": u["excl_class"].reindex(df["_unit_group"]).to_numpy(),
        "exclusion": u["exclusion"].reindex(df["_unit_group"]).to_numpy(),
        "exclusion_detail": u["exclusion_detail"].reindex(df["_unit_group"]).to_numpy(),
        "kind": u["kind"].reindex(df["_unit_group"]).to_numpy(),
        "n_legs": u["n_legs"].reindex(df["_unit_group"]).to_numpy().astype("int16"),
        "tenor_bucket": bucket_of(mat),
        "mat_years": mat.astype("float32"),
        "tenor_years": ten.astype("float32"),
        "fwd_years": fwd.astype("float32"),
        "hour_et": pd.to_numeric(df["execution_hour_et"], errors="coerce")
                     .fillna(-1).astype("int8"),
        "session": df["execution_session"].astype("string"),
        "venue_class": df["_venue"].to_numpy(),
        "dv01": df["_dv01_proxy"].to_numpy().astype("float64"),
        "notional": pd.to_numeric(df["notional"], errors="coerce").to_numpy(float),
        "is_block": df["is_block"].fillna(False).to_numpy(bool),
        "is_capped": df["is_capped"].fillna(False).to_numpy(bool),
        "trade_type": df["trade_type"].astype("string"),
        "rate_index": df["rate_index_clean"].astype("string"),
        "has_ptp": pd.to_numeric(df["package_transaction_price"],
                                 errors="coerce").notna().to_numpy(),
        "has_pts": pd.to_numeric(df["package_transaction_spread"],
                                 errors="coerce").notna().to_numpy(),
        "has_ptp_grp": df["ptp_group_id"].notna().to_numpy(),
        "has_ust_cusip": df["ust_cusip"].notna().to_numpy(),
        "opa_sign": pd.to_numeric(df["opa_sign"], errors="coerce")
                      .fillna(0).astype("int8"),
        "sentinel": df["_sentinel"].to_numpy(bool),
    })
    # notional sentinel: keep the flag, drop the 1e20 from the notional stats
    legs.loc[legs["sentinel"], "notional"] = np.nan
    legs["is_first_leg"] = ~legs["unit"].duplicated()

    # --- annuity-spread DV01 allocation (robustness) -----------------------
    share = annuity_spread(legs["notional"], ten, fwd, sanity.FLAT_YIELD)
    dv = legs["dv01"].to_numpy()
    alloc = share * dv[:, None]
    spanned = share.sum(axis=1) > 0
    # Where the leg spans a positive annuity the allocation must be exact.
    resid = np.abs(alloc[spanned].sum(axis=1) - dv[spanned])
    assert (resid <= 1e-9 * np.maximum(1.0, dv[spanned])).all(), \
        "annuity-spread allocation does not sum to the leg DV01"
    # Where it does not (tenor <= 0 or NaN) nothing is allocated. `abs()` in
    # `_dv01_proxy` can still make such a leg carry DV01, so this has to be a
    # measured, negligible remainder rather than an assumption.
    lost = float(dv[~spanned].sum())
    if lost > 1e-6 * max(1.0, float(dv.sum())):
        raise AssertionError(
            f"{(~spanned).sum()} unspanned legs carry {lost:,.0f} DV01 "
            f"({lost / dv.sum():.3%} of the chunk) -- not negligible")

    sp = pd.DataFrame(alloc, columns=LABELS)
    sp["as_of_date"] = legs["as_of_date"].to_numpy()
    sp["excl_class"] = legs["excl_class"].to_numpy()
    sp["exclusion_detail"] = legs["exclusion_detail"].astype("string").to_numpy()
    spread = (sp.groupby(["as_of_date", "excl_class", "exclusion_detail"],
                         dropna=False, observed=True)[LABELS].sum()
                .stack().rename("dv01").reset_index())
    spread.columns = ["as_of_date", "excl_class", "exclusion_detail",
                      "tenor_bucket", "dv01"]

    # --- per-unit frame ----------------------------------------------------
    g = legs.groupby("unit", sort=False, observed=True)
    units = pd.DataFrame({
        "n_tenor_buckets": g["tenor_bucket"].nunique(),
        "bucket_first": g["tenor_bucket"].first(),
        "mat_min": g["mat_years"].min(),
        "mat_max": g["mat_years"].max(),
        "notional_sum": g["notional"].sum(min_count=1),
        "notional_max": g["notional"].max(),
        "hour_et": g["hour_et"].first(),
        "session": g["session"].first(),
        "any_ptp": g["has_ptp"].any(),
        "any_pts": g["has_pts"].any(),
        "any_ptp_grp": g["has_ptp_grp"].any(),
        "any_ust_cusip": g["has_ust_cusip"].any(),
        "n_opa_nonzero": g["opa_sign"].apply(lambda s: int((s != 0).sum())),
        "trade_type_first": g["trade_type"].first(),
        "n_trade_types": g["trade_type"].nunique(),
        "fwd_max": g["fwd_years"].max(),
    })
    # bucket carrying the most DV01 in the unit
    top = (legs.groupby(["unit", "tenor_bucket"], observed=True)["dv01"].sum()
                .reset_index().sort_values("dv01", ascending=False)
                .drop_duplicates("unit").set_index("unit")["tenor_bucket"])
    units["bucket_top_dv01"] = top

    # unit-level facts the per-leg tables need (bucket-level recovery effect)
    legs["unit_any_ptp"] = units["any_ptp"].reindex(legs["unit"]).to_numpy()
    legs["unit_any_pts"] = units["any_pts"].reindex(legs["unit"]).to_numpy()
    legs["is_lifecycle"] = u["is_lifecycle"].reindex(legs["unit"]).to_numpy()

    units = u.join(units, how="left")
    units = units.merge(pkg, on="package_id", how="left")

    for c in ("kind", "rate_index", "venue_class", "exclusion",
              "exclusion_detail", "excl_class", "upfront_source", "session",
              "trade_type_first", "opa_sign_confidence", "confidence_tone",
              "package_type"):
        if c in units.columns:
            units[c] = units[c].astype("string")
    for c in ("excl_class", "exclusion", "exclusion_detail", "kind",
              "venue_class", "trade_type", "rate_index", "session"):
        legs[c] = legs[c].astype("string")
    legs["tenor_bucket"] = legs["tenor_bucket"].astype("string")

    legs.drop(columns=["unit"]).to_parquet(CACHE / f"legs_{tag}.parquet",
                                           index=False)
    units.to_parquet(CACHE / f"units_{tag}.parquet", index=False)
    spread.to_parquet(CACHE / f"spread_{tag}.parquet", index=False)
    return len(raw), len(u)


def main() -> int:
    import psycopg2
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    fp = module_fingerprint()
    meta_p = CACHE / "meta.json"
    if meta_p.exists():
        old = json.loads(meta_p.read_text())
        if old.get("modules") != fp:
            print("MODULE DRIFT since the cache was started -- refusing to mix "
                  "two vintages. Delete scratch/pkgskew_cache and rerun.")
            print(" old:", old.get("modules"))
            print(" new:", fp)
            return 2
    else:
        meta_p.write_text(json.dumps(
            {"modules": fp, "start": START, "end": END}, indent=2))

    lo, hi = pd.Timestamp(START), pd.Timestamp(END)
    chunks = sorted(set(
        [lo] + list(pd.date_range(lo, hi, freq="MS", inclusive="both"))))
    conn = None
    n_legs = n_units = 0
    for c_lo in chunks:
        c_hi = min(c_lo + pd.offsets.MonthEnd(0), hi)
        if c_hi < c_lo:
            continue
        tag = f"{c_lo:%Y-%m}"
        if (CACHE / f"spread_{tag}.parquet").exists():
            print(f"  {tag}  cached", flush=True)
            continue
        if conn is None:
            conn = psycopg2.connect(resolve_pg_url())
        t0 = time.time()
        nl, nu = run_chunk(conn, c_lo.date(), c_hi.date(), tag)
        n_legs += nl
        n_units += nu
        print(f"  {tag}  {nl:>8,} legs -> {nu:>7,} units  "
              f"[{time.time() - t0:.0f}s]", flush=True)
        gc.collect()
    if conn is not None:
        conn.close()
    print(f"done. this run: {n_legs:,} legs, {n_units:,} units")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
