"""R0 -- build Y: signed aggressor volume in contracts, 1-minute bins, per futures bucket.

Source: Databento GLBX.MDP3 schema ``mbo``, DBN/zstd, one member per UTC day inside
per-root zips at ``D:/{root}_mbo/*.zip``.  Members are streamed out of the zip; nothing
is extracted to disk.

WHAT COUNTS AS A TRADE
----------------------
Only ``action == 'T'`` records, and only on OUTRIGHT instruments.

  * ``T`` is the aggressing order's record; ``F`` records are the resting orders that
    were filled.  Within one match event ``size(T) == sum(size(F))``, so counting both
    double-counts volume by ~1.9x (measured, see the report).
  * ``T.side`` is the AGGRESSOR side.  Validated three ways -- see ``scratch_y_probe2.py``
    (book reconstruction: every T at the standing best offer carries side='B', every T at
    the standing best bid carries side='A', 26,237/26,241 classifiable, zero
    counterexamples) and ``scratch_y_probe3.py`` (corr(signed volume, contemporaneous
    1-min price change) = +0.42 / +0.38).
  * ``side == 'N'`` (no aggressor reported by CME) contributes 0 to ``signed_volume`` but
    is still counted in ``gross_volume`` and ``n_trades``.

Combo instruments (calendar spreads, packs/bundles ``SR3:AB``, butterflies ``SR3:BF``,
condors, inter-commodity) are EXCLUDED.  Their aggressor side is defined on the combo,
not on a leg, so signing them per-outright would need a leg-decomposition convention the
pre-registration does not fix.  Implied matches that fill resting OUTRIGHT orders do print
in the outright book and ARE included.

CLOCK
-----
``ts_event`` (CME matching-engine transact time), floored to the UTC minute.

SESSIONS
--------
CME Globex session for trade date D runs D-1 17:00 CT -> D 16:00 CT.  A session therefore
straddles two Databento UTC-day files.  Session date is derived from America/Chicago local
time: local >= 17:00 -> next calendar day, else same day.

Usage
-----
    python build_y_mbo.py --stage cache      # per-root/per-UTC-day parquet cache (resumable)
    python build_y_mbo.py --stage assemble   # buckets -> data/y_signed_volume.parquet
    python build_y_mbo.py --stage all
    python build_y_mbo.py --selftest         # reproduce a known-answer day
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

import databento as db

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache_y_mbo")
DATA = os.path.join(HERE, "data")
CHICAGO = ZoneInfo("America/Chicago")

ROOTS = ["sr3", "zq", "zt", "zf", "zn", "tn", "zb", "ub"]

#: bucket -> roots.  WN (ub) is NOT part of the pre-registered decision rule; it is
#: extracted for reference only.
BUCKETS: Dict[str, List[str]] = {
    "SFR_FF": ["sr3", "zq"],
    "TU": ["zt"],
    "FV": ["zf"],
    "TY_UXY": ["zn", "tn"],
    "US": ["zb"],
    "WN": ["ub"],          # reference only -- prereg map stops at US
}
DECISION_BUCKETS = ["SFR_FF", "TU", "FV", "TY_UXY", "US"]

#: SR3 is aggregated over the 12 nearest QUARTERLY outrights, resolved per day from the
#: day's own symbology.  Serial SR3 months (J/K/N/Q/V/X/F/G) are excluded -- measured at
#: 259 of 1,432,498 outright contracts (0.018%) on 2026-07-07.
SR3_N_QUARTERLIES = 12

MONTH_CODE = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
              "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
QUARTERLY_MONTHS = {3, 6, 9, 12}
_OUTRIGHT_RE = re.compile(r"^([A-Z0-9]{2,3})([FGHJKMNQUVXZ])(\d)$")


# --------------------------------------------------------------------------------------
# symbology
# --------------------------------------------------------------------------------------
def resolve_year(digit: int, ref_year: int) -> int:
    """Single-digit CME year code -> nearest year >= ref_year ending in that digit.

    CME lists SR3 quarterlies 10 years out, so within a 10-year listing horizon the map
    is unique.  Verified against the observed 2026 universe: digits 6..5 map to
    2026..2035 with no collision (SR3Z5 = Dec-2035, the 10y tail).
    """
    base = ref_year - (ref_year % 10) + digit
    if base < ref_year:
        base += 10
    return base


def parse_outright(sym: str, ref_year: int) -> Optional[Tuple[str, int, int]]:
    """(root, year, month) for an outright symbol, else None (combos return None)."""
    m = _OUTRIGHT_RE.match(sym)
    if not m:
        return None
    root, mc, yd = m.group(1), m.group(2), int(m.group(3))
    return root, resolve_year(yd, ref_year), MONTH_CODE[mc]


def is_combo(sym: str) -> bool:
    return (":" in sym) or ("-" in sym)


# --------------------------------------------------------------------------------------
# zip / member plumbing
# --------------------------------------------------------------------------------------
_MEMBER_RE = re.compile(r"glbx-mdp3-(\d{8})\.mbo\.dbn\.zst$")


def list_members(root: str) -> List[Tuple[str, str, date]]:
    out = []
    for zp in sorted(glob.glob(f"D:/{root}_mbo/*.zip")):
        with zipfile.ZipFile(zp) as z:
            for name in z.namelist():
                m = _MEMBER_RE.search(name)
                if m:
                    out.append((zp, name, datetime.strptime(m.group(1), "%Y%m%d").date()))
    out.sort(key=lambda t: t[2])
    return out


def session_date_from_ns(ts_ns: np.ndarray) -> np.ndarray:
    """Map UTC epoch-ns to CME trade date (local >= 17:00 CT rolls to the next day)."""
    idx = pd.to_datetime(ts_ns, utc=True).tz_convert(CHICAGO)
    d = idx.normalize().tz_localize(None).values.astype("datetime64[D]")
    roll = (idx.hour >= 17).astype("int64")
    return d + roll.astype("timedelta64[D]")


# --------------------------------------------------------------------------------------
# stage 1 -- per (root, UTC day) minute aggregate cache
# --------------------------------------------------------------------------------------
def process_day(root: str, zip_path: str, member: str, utc_day: date) -> Tuple[pd.DataFrame, dict]:
    t0 = time.time()
    with zipfile.ZipFile(zip_path) as z:
        raw = z.read(member)
    t_read = time.time() - t0

    store = db.DBNStore.from_bytes(raw)
    id2sym: Dict[int, str] = {}
    for sym, ents in store.metadata.mappings.items():
        for e in ents:
            id2sym[int(e["symbol"])] = sym

    t0 = time.time()
    n_rec = 0
    t_vol = f_vol = 0
    iids, tss, szs, sds = [], [], [], []
    for arr in store.to_ndarray(count=4_000_000):
        n_rec += len(arr)
        act = arr["action"]
        mT = act == b"T"
        t_vol += int(arr["size"][mT].sum())
        f_vol += int(arr["size"][act == b"F"].sum())
        if mT.any():
            a = arr[mT]
            iids.append(a["instrument_id"].astype("int64"))
            tss.append(a["ts_event"].astype("int64"))
            szs.append(a["size"].astype("int64"))
            sds.append(a["side"].copy())
    t_dec = time.time() - t0
    del raw, store

    stats = {"root": root, "utc_day": str(utc_day), "n_records": n_rec,
             "T_volume": t_vol, "F_volume": f_vol,
             "read_s": round(t_read, 1), "decode_s": round(t_dec, 1)}

    if not iids:
        return (pd.DataFrame(columns=["sym", "session_date", "minute_utc", "signed_volume",
                                      "gross_volume", "n_trades", "unsigned_volume"]), stats)

    iid = np.concatenate(iids)
    ts = np.concatenate(tss)
    sz = np.concatenate(szs)
    sd = np.concatenate(sds)

    syms = np.array([id2sym.get(int(i), "?") for i in iid], dtype=object)
    combo = np.array([is_combo(s) for s in syms])
    stats["combo_T_volume"] = int(sz[combo].sum())
    stats["outright_T_volume"] = int(sz[~combo].sum())
    stats["unmapped_T_volume"] = int(sz[syms == "?"].sum())

    keep = ~combo & (syms != "?")
    iid, ts, sz, sd, syms = iid[keep], ts[keep], sz[keep], sd[keep], syms[keep]
    if len(ts) == 0:
        return (pd.DataFrame(columns=["sym", "session_date", "minute_utc", "signed_volume",
                                      "gross_volume", "n_trades", "unsigned_volume"]), stats)

    sign = np.where(sd == b"B", 1, np.where(sd == b"A", -1, 0)).astype("int64")
    stats["side_N_volume"] = int(sz[sign == 0].sum())
    stats["side_B_volume"] = int(sz[sign == 1].sum())
    stats["side_A_volume"] = int(sz[sign == -1].sum())
    stats["first_trade_ts"] = int(ts.min())
    stats["last_trade_ts"] = int(ts.max())

    minute = (ts // 60_000_000_000) * 60_000_000_000
    df = pd.DataFrame({
        "sym": pd.Categorical(syms),
        "session_date": session_date_from_ns(ts),
        "minute_utc": minute,
        "signed": sign * sz,
        "gross": sz,
        "unsigned": np.where(sign == 0, sz, 0),
        "one": 1,
    })
    g = (df.groupby(["sym", "session_date", "minute_utc"], observed=True, sort=False)
           .agg(signed_volume=("signed", "sum"),
                gross_volume=("gross", "sum"),
                n_trades=("one", "sum"),
                unsigned_volume=("unsigned", "sum"))
           .reset_index())
    g["sym"] = g["sym"].astype(str)
    return g, stats


def stage_cache(roots: List[str], force: bool = False) -> None:
    os.makedirs(CACHE, exist_ok=True)
    for root in roots:
        outdir = os.path.join(CACHE, root)
        os.makedirs(outdir, exist_ok=True)
        members = list_members(root)
        print(f"\n=== {root}: {len(members)} UTC-day members", flush=True)
        for i, (zp, name, d) in enumerate(members, 1):
            op = os.path.join(outdir, f"{d:%Y%m%d}.parquet")
            sp = os.path.join(outdir, f"{d:%Y%m%d}.stats.json")
            if os.path.exists(op) and os.path.exists(sp) and not force:
                print(f"  [{i}/{len(members)}] {d} cached", flush=True)
                continue
            t0 = time.time()
            g, stats = process_day(root, zp, name, d)
            g.to_parquet(op, index=False)
            with open(sp, "w") as f:
                json.dump(stats, f)
            print(f"  [{i}/{len(members)}] {d} rows={len(g):,} recs={stats['n_records']:,} "
                  f"Tvol={stats['T_volume']:,} outright={stats.get('outright_T_volume',0):,} "
                  f"({time.time()-t0:.0f}s)", flush=True)


# --------------------------------------------------------------------------------------
# stage 2 -- assemble buckets
# --------------------------------------------------------------------------------------
_UTC_DAYS_CACHE: Dict[str, set] = {}


def utc_days_available(root: str) -> set:
    if root not in _UTC_DAYS_CACHE:
        _UTC_DAYS_CACHE[root] = {
            datetime.strptime(os.path.basename(p)[:8], "%Y%m%d").date()
            for p in glob.glob(os.path.join(CACHE, root, "*.parquet"))
        }
    return _UTC_DAYS_CACHE[root]


def session_complete(root: str, session: date) -> bool:
    """A CME session spans UTC days D-1 (evening) and D.  Complete iff both files exist
    (D-1 is skipped when it is a Saturday, which never carries a session opening)."""
    days = utc_days_available(root)
    prev_ok = (session - timedelta(days=1)).weekday() == 5 or (session - timedelta(days=1)) in days
    return prev_ok and (session in days)


def load_root_cache(root: str) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(CACHE, root, "*.parquet")))
    if not files:
        raise FileNotFoundError(f"no cache for {root}; run --stage cache")
    parts = [pd.read_parquet(f) for f in files]
    df = pd.concat(parts, ignore_index=True)
    df["root"] = root
    return df


_YEAR_TO_CODE = {v: k for k, v in MONTH_CODE.items()}


def third_wednesday(year: int, month: int) -> date:
    d = date(year, month, 1)
    # weekday(): Mon=0 .. Wed=2
    first_wed = d + timedelta(days=(2 - d.weekday()) % 7)
    return first_wed + timedelta(days=14)


def sr3_last_trading_day(year: int, month: int) -> date:
    """CME 3M SOFR: the business day immediately preceding the third Wednesday of the
    third month following the contract month.

    Verified empirically: SR3H6 (contract month Mar-2026) -> 3rd Wed of Jun-2026 is
    2026-06-17 -> LTD 2026-06-16, and SR3H6's last trade in this sample is exactly
    2026-06-16 (probe 7).
    """
    y, m = year, month + 3
    while m > 12:
        y, m = y + 1, m - 12
    w = third_wednesday(y, m)
    d = w - timedelta(days=1)
    while d.weekday() >= 5:          # never triggers for a Wed-1, kept for safety
        d -= timedelta(days=1)
    return d


def sr3_quarterly_set(session: date, n: int = SR3_N_QUARTERLIES) -> List[str]:
    """The n nearest SR3 quarterly outrights listed on `session`, by expiry order.

    Calendar-determined, so a contract that simply did not print on a given session
    cannot shift the set (which a traded-universe rule would do).
    """
    cands = []
    for y in range(session.year - 1, session.year + 12):
        for m in sorted(QUARTERLY_MONTHS):
            ltd = sr3_last_trading_day(y, m)
            if ltd >= session:
                cands.append((y, m))
    cands.sort()
    return [f"SR3{_YEAR_TO_CODE[m]}{y % 10}" for y, m in cands[:n]]


def sr3_first_n_quarterlies(df: pd.DataFrame, n: int = SR3_N_QUARTERLIES,
                            verbose: bool = True) -> pd.DataFrame:
    """Keep, per session date, the n nearest SR3 quarterly outrights."""
    sessions = pd.to_datetime(pd.Series(df["session_date"].unique())).dt.date
    sel = pd.DataFrame(
        [(pd.Timestamp(s).to_datetime64(), sym)
         for s in sessions for sym in sr3_quarterly_set(s, n)],
        columns=["session_date", "sym"])
    df = df.copy()
    df["session_date"] = pd.to_datetime(df["session_date"]).values
    out = df.merge(sel, on=["session_date", "sym"], how="inner")

    if verbose:
        # cross-check against the traded-universe rule; they must agree on full sessions
        meta = {s: parse_outright(s, 2026) for s in df["sym"].unique()}
        q = {s: p for s, p in meta.items() if p and p[2] in QUARTERLY_MONTHS}
        tr = df[df["sym"].isin(q)].copy()
        tr["ord"] = tr["sym"].map(lambda s: q[s][1] * 12 + q[s][2])
        first = (tr.groupby(["session_date", "sym"], observed=True)["ord"].first()
                   .reset_index().sort_values(["session_date", "ord"]))
        first["k"] = first.groupby("session_date").cumcount()
        alt = set(map(tuple, first.loc[first["k"] < n, ["session_date", "sym"]].values))
        cal = set(map(tuple, sel.values))
        only_cal = {d for d, s in cal - alt}
        only_alt = {d for d, s in alt - cal}
        disagree = sorted(only_cal | only_alt)
        print(f"SR3 first-{n}: calendar rule vs traded-universe rule disagree on "
              f"{len(disagree)} of {len(sessions)} sessions"
              + (f": {[str(pd.Timestamp(d).date()) for d in disagree]}" if disagree else ""))
    return out


def stage_assemble(out_path: str) -> None:
    os.makedirs(DATA, exist_ok=True)
    per_root = {}
    for root in ROOTS:
        try:
            per_root[root] = load_root_cache(root)
        except FileNotFoundError as e:
            print("SKIP", e)
    # ------- SR3 first-12 quarterly restriction -------
    if "sr3" in per_root:
        before = per_root["sr3"]["gross_volume"].sum()
        per_root["sr3"] = sr3_first_n_quarterlies(per_root["sr3"])
        after = per_root["sr3"]["gross_volume"].sum()
        print(f"SR3 first-{SR3_N_QUARTERLIES}-quarterly restriction keeps "
              f"{after:,} of {before:,} outright contracts ({after/before:.2%})")

    coverage_rows = []
    out_frames = []
    for bucket, roots in BUCKETS.items():
        avail = [r for r in roots if r in per_root]
        if not avail:
            print(f"bucket {bucket}: NO DATA")
            continue
        parts = [per_root[r] for r in avail]
        cat = pd.concat(parts, ignore_index=True)

        # composition constancy.  Two conditions, both about the bucket's constituent
        # set being the SAME thing on every session it is emitted for:
        #   (i)  every root of the bucket has data on that session date;
        #   (ii) every root of the bucket has the SAME session completeness.  A CME
        #        session spans two Databento UTC-day files (D-1 22:00 -> D 21:00 UTC),
        #        so a root whose file for D-1 or D is missing covers only part of it.
        #        sr3's coverage ends with the 2026-08-06 file, which holds only the
        #        evening open of session 2026-08-07 -- pooling that with a full zq day
        #        would make SFR_FF zq-only for 21 of that session's 23 hours.
        sess_sets = [set(per_root[r]["session_date"].unique()) for r in avail]
        common = set.intersection(*sess_sets) if len(sess_sets) > 1 else sess_sets[0]
        if len(avail) > 1:
            same_completeness = {
                s for s in common
                if len({session_complete(r, pd.Timestamp(s).date()) for r in avail}) == 1
            }
            common = same_completeness
        dropped = sorted(set(cat["session_date"].unique()) - common)
        cat = cat[cat["session_date"].isin(common)]

        g = (cat.groupby(["session_date", "minute_utc"], observed=True)
               .agg(signed_volume=("signed_volume", "sum"),
                    gross_volume=("gross_volume", "sum"),
                    n_trades=("n_trades", "sum"),
                    unsigned_volume=("unsigned_volume", "sum"))
               .reset_index())

        # dense minute grid, per session, from first to last traded minute of that session
        dense = []
        for sess, sub in g.groupby("session_date", sort=True):
            lo, hi = sub["minute_utc"].min(), sub["minute_utc"].max()
            full = pd.DataFrame({"minute_utc": np.arange(lo, hi + 60_000_000_000, 60_000_000_000)})
            full["session_date"] = sess
            dense.append(full)
        dense = pd.concat(dense, ignore_index=True)
        res = dense.merge(g, on=["session_date", "minute_utc"], how="left")
        for c in ("signed_volume", "gross_volume", "n_trades", "unsigned_volume"):
            res[c] = res[c].fillna(0).astype("int64")
        res["bucket"] = bucket
        out_frames.append(res)

        coverage_rows.append({
            "bucket": bucket,
            "roots": "+".join(avail),
            "in_decision_rule": bucket in DECISION_BUCKETS,
            "n_days": res["session_date"].nunique(),
            "n_bins": len(res),
            "n_bins_with_trade": int((res["n_trades"] > 0).sum()),
            "first_session": str(pd.Timestamp(res["session_date"].min()).date()),
            "last_session": str(pd.Timestamp(res["session_date"].max()).date()),
            "gross_volume": int(res["gross_volume"].sum()),
            "signed_volume": int(res["signed_volume"].sum()),
            "unsigned_volume": int(res["unsigned_volume"].sum()),
            "sessions_dropped_for_composition": len(dropped),
            "dropped_sessions": ";".join(str(pd.Timestamp(d).date()) for d in dropped),
        })

    allb = pd.concat(out_frames, ignore_index=True)
    allb["minute_utc"] = pd.to_datetime(allb["minute_utc"], utc=True)
    final = allb[["bucket", "minute_utc", "signed_volume", "gross_volume", "n_trades"]].copy()
    final = final.sort_values(["bucket", "minute_utc"]).reset_index(drop=True)
    final.to_parquet(out_path, index=False)
    final.to_csv(out_path.replace(".parquet", ".csv"), index=False)

    side = allb[["bucket", "minute_utc", "session_date", "unsigned_volume"]].copy()
    side.to_parquet(os.path.join(DATA, "y_signed_volume_unsigned_side.parquet"), index=False)

    cov = pd.DataFrame(coverage_rows)
    cov.to_csv(os.path.join(DATA, "y_coverage.csv"), index=False)

    # per-session bin counts, so partial sessions at the sample edges are visible
    per_sess = (allb.groupby(["bucket", "session_date"])
                    .agg(n_bins=("minute_utc", "size"),
                         n_bins_with_trade=("n_trades", lambda s: int((s > 0).sum())),
                         gross_volume=("gross_volume", "sum"),
                         signed_volume=("signed_volume", "sum"),
                         first_minute=("minute_utc", "min"),
                         last_minute=("minute_utc", "max"))
                    .reset_index())
    per_sess["session_complete"] = [
        all(session_complete(r, pd.Timestamp(s).date()) for r in BUCKETS[b])
        for b, s in zip(per_sess["bucket"], per_sess["session_date"])
    ]
    per_sess.to_csv(os.path.join(DATA, "y_sessions.csv"), index=False)
    thin = per_sess[per_sess["n_bins"] < 600]
    print(f"\npartial sessions (<600 bins): {len(thin)} of {len(per_sess)} bucket-sessions")
    if len(thin):
        print(thin.to_string(index=False))
    print("\n===== COVERAGE =====")
    print(cov.drop(columns=["dropped_sessions"]).to_string(index=False))
    print(f"\nwrote {out_path}  rows={len(final):,}")
    print(f"N_days (union) = {allb['session_date'].nunique()}   N_bins (total) = {len(final):,}")


# --------------------------------------------------------------------------------------
# self test -- reproduce a known answer before trusting the pipeline
# --------------------------------------------------------------------------------------
def selftest() -> int:
    """Recompute UBU6 / ZNU6 minute series for the 2026-06-02 UTC day directly from the
    raw stream and compare to what the cached pipeline output holds."""
    fails = 0
    for root, sym, expect_signed, expect_gross in [
        ("ub", "UBU6", -186, 288375),
        ("zn", "ZNU6", -25510, 1406113),
    ]:
        p = os.path.join(CACHE, root, "20260602.parquet")
        if not os.path.exists(p):
            print(f"SELFTEST SKIP {root}: {p} missing")
            continue
        df = pd.read_parquet(p)
        s = df[df["sym"] == sym]
        got_signed = int(s["signed_volume"].sum())
        got_gross = int(s["gross_volume"].sum())
        ok = (got_signed == expect_signed) and (got_gross == expect_gross)
        print(f"SELFTEST {root}/{sym} UTC-day 2026-06-02: signed {got_signed:,} "
              f"(expect {expect_signed:,})  gross {got_gross:,} (expect {expect_gross:,})  "
              f"{'PASS' if ok else 'FAIL'}")
        fails += 0 if ok else 1
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["cache", "assemble", "all"], default="all")
    ap.add_argument("--roots", default=",".join(ROOTS))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", default=os.path.join(DATA, "y_signed_volume.parquet"))
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    roots = [r.strip() for r in a.roots.split(",") if r.strip()]
    if a.stage in ("cache", "all"):
        stage_cache(roots, force=a.force)
    if a.stage in ("assemble", "all"):
        stage_assemble(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
