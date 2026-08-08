r"""Settle what Citi's bond numbers actually MEAN, by measuring them.

``MDP/CitiVelocityExcel/bonds/values.py`` maps Citi's eight published bond values
onto ``FixedRateBondValue``. Four of those mappings are the obvious reading and
have never been checked, and each is a way to be confidently wrong:

===============  =========================================  ==================
Citi value       the question                               cost of guessing
===============  =========================================  ==================
``PRICE``        clean or dirty?                            up to 3.18 price
                                                            points on this set
``YIELD``        which compounding basis?                   2.93 bp on a BTP
``DURATION``     modified or Macaulay?                      ~2% (a factor of
                                                            ``1 + y/f``)
``DV01``         per 100 face or per million? which sign?   a factor of 10,000
``ASW_4_USD``    par-par, market-value or yield-yield?      several bp off par
===============  =========================================  ==================

None of these can be settled by repricing Citi's number with our own model and
observing that it agrees — that is a tautology. They are settled by taking
**two** numbers Citi published for the same bond at the same instant and asking
which local interpretation reproduces the *other* one. Citi's ``PRICE`` and
``YIELD`` are jointly determined; only one reading of ``PRICE`` maps to Citi's
``YIELD`` under a given compounding basis, and the accrued interest is what
separates the readings.

That is why the bond set matters. It spans accrued from **0.0163 to 3.1844**
price points (chosen by maturity day: a bond maturing 15 Aug has ~174/181 days
accrued on 8 Aug, one maturing 31 Jan has ~8). On the low-accrued bonds clean and
dirty are nearly the same number and tell you nothing; on the high-accrued ones
they are three points apart and the answer is unambiguous.

Usage
-----
::

    python scripts/citivelo_bond_calibration.py fetch        # touches Excel
    python scripts/citivelo_bond_calibration.py build        # pure CPU
    python scripts/citivelo_bond_calibration.py fetch build   # both

``fetch`` and ``build`` are separate on purpose. The add-in's memory only ever
grows and only a human restart clears it, so a long session can be lost; splitting
them means a lost session costs time and never data. ``fetch`` refuses to start
above :data:`MEMORY_CEILING_MB` and samples again on the way out.

Status as of this writing
-------------------------
**Not yet run.** Excel was at 7,639 MB when this was written — above the 3,800 MB
ceiling and above the 5,249 MB that wedged it on 2026-08-07 — so the calibration
was written and left unrun rather than guessed at. Until someone runs it, every
affected mapping in ``values.py`` carries ``verified=False`` and the source
records the interpretation it used in each pricer's provenance, so a wrong
reading is traceable rather than invisible.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd

#: Stop here. The add-in wedged at 5,249 MB on 2026-08-07 — unresponsive to a
#: 15s ping, no modal dialog, and it did not recover when the COM client was
#: released. Only a human restart clears it.
MEMORY_CEILING_MB = 3800.0

#: Where ``fetch`` writes and ``build`` reads.
RAW_PATH = pathlib.Path(REPO_ROOT) / "MDP" / "CitiVelocityExcel" / "catalog" / "bond_calibration_raw.json"
OUT_PATH = pathlib.Path(REPO_ROOT) / "MDP" / "CitiVelocityExcel" / "catalog" / "bond_calibration.json"

#: Every value we want a number for, whether or not the pricer uses it.
WANTED = ("PRICE", "YIELD", "DURATION", "DV01", "SPREAD_TSY", "OAS",
          "ASW_4_USD", "ASW_4_JPY", "ASW_4_AUD")


# ──────────────────────────────────────────────────────────────────────
# bond selection
# ──────────────────────────────────────────────────────────────────────

def select_bonds(as_of: datetime.date, *, n_high: int = 4, n_low: int = 3):
    """US Treasuries spanning maturity AND accrued fraction.

    Accrued is the discriminator, so the set is chosen for it explicitly rather
    than taken as whatever the liquid names happen to give. UST coupon dates come
    off the maturity day on a semi-annual schedule, so the maturity day alone
    determines where in the coupon period ``as_of`` falls.
    """
    from MDP.CitiVelocityExcel.bonds import BondUniverse

    uni = BondUniverse.from_catalog(country="USA", asset_type="GOVT")
    rows = []
    for d in uni:
        if not d.priceable:
            continue
        m = d.maturity
        cands = []
        for yr in (as_of.year - 1, as_of.year, as_of.year + 1):
            for mo in (m.month, m.month + 6 if m.month <= 6 else m.month - 6):
                for day in (m.day, 30, 28):
                    try:
                        cands.append(datetime.date(yr, mo, day))
                        break
                    except ValueError:
                        continue
        prev = max([c for c in cands if c <= as_of], default=None)
        nxt = min([c for c in cands if c > as_of], default=None)
        if prev is None or nxt is None or nxt == prev:
            continue
        frac = (as_of - prev).days / (nxt - prev).days
        ttm = (m - as_of).days / 365.25
        if ttm <= 0.3:
            continue
        vals = uni.available_values(d.isin)
        if len(vals) < 6:
            continue
        rows.append(dict(isin=d.isin, desc=d.description, cpn=d.coupon,
                         maturity=m.isoformat(), ttm=round(ttm, 2),
                         accrued_fraction=round(frac, 4),
                         accrued=round(d.coupon / 2.0 * frac, 4),
                         values=list(vals)))

    hi = sorted([r for r in rows if r["accrued_fraction"] > 0.85], key=lambda r: r["ttm"])
    lo = sorted([r for r in rows if r["accrued_fraction"] < 0.15], key=lambda r: r["ttm"])
    chosen, seen = [], set()
    for bucket, want in ((hi, n_high), (lo, n_low)):
        if not bucket:
            continue
        step = max(1, len(bucket) // want)
        for r in bucket[::step][:want]:
            if r["isin"] not in seen:
                seen.add(r["isin"])
                chosen.append(r)
    return chosen


# ──────────────────────────────────────────────────────────────────────
# fetch (Excel)
# ──────────────────────────────────────────────────────────────────────

def do_fetch(as_of: datetime.date, *, lookback_days: int = 30) -> dict:
    """One Excel trip: every wanted value for the calibration bonds."""
    from MDP.CitiVelocityExcel import tags
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    bonds = select_bonds(as_of)
    if not bonds:
        raise SystemExit("No calibration bonds selected — is the catalog present?")

    tag_list, tag_owner = [], {}
    for b in bonds:
        for v in b["values"]:
            if v not in WANTED:
                continue
            t = tags.bond(b["isin"], v)
            tag_list.append(t)
            tag_owner[t] = (b["isin"], v)

    quotes = CitiVeloQuotes()
    client = quotes.client()
    mem0 = client.excel_memory_mb()
    print(f"Excel memory BEFORE: {mem0:.0f} MB (ceiling {MEMORY_CEILING_MB:.0f})")
    if mem0 < 0:
        raise SystemExit("Could not read Excel's memory; refusing to run blind.")
    if mem0 > MEMORY_CEILING_MB:
        raise SystemExit(
            f"ABORT: Excel is at {mem0:.0f} MB, above the {MEMORY_CEILING_MB:.0f} MB ceiling. "
            "The add-in's memory only ever grows and only a human restart clears it; it "
            "wedged at 5,249 MB on 2026-08-07. Restart Excel, sign in, and re-run."
        )

    print(f"{len(bonds)} bonds, {len(tag_list)} tags")
    frame = quotes.frame(tag_list, "DAILY",
                         start=as_of - datetime.timedelta(days=lookback_days), end=as_of)
    mem1 = client.excel_memory_mb()
    print(f"Excel memory AFTER: {mem1:.0f} MB ({mem1 - mem0:+.0f})")

    served = {}
    for t in frame.columns:
        s = frame[t].dropna()
        if s.empty:
            continue
        served[t] = {"index": [str(i) for i in s.index], "values": [float(v) for v in s.values]}

    raw = {
        "fetched_at": datetime.datetime.now().isoformat(),
        "as_of": as_of.isoformat(),
        "bonds": bonds,
        "tag_owner": {k: list(v) for k, v in tag_owner.items()},
        "served": served,
        "unserved": [t for t in tag_list if t not in served],
        "mem_before": mem0,
        "mem_after": mem1,
    }
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(json.dumps(raw, indent=1))
    print(f"wrote {RAW_PATH}  ({len(served)}/{len(tag_list)} tags served)")
    quotes.close()
    return raw


# ──────────────────────────────────────────────────────────────────────
# build (pure CPU)
# ──────────────────────────────────────────────────────────────────────

def _local_metrics(descriptor, *, as_of, clean_price=None, ytm=None):
    """Both backends' analytics for one bond at one price, keys documented in bonds/."""
    from MDP.CitiVelocityExcel.bonds import (
        build_ql_bond, build_rl_bond, conventions_for, ql_bond_metrics,
        rl_bond_metrics, rl_settlement_date,
    )

    conv = conventions_for(descriptor.country)
    out = {}
    try:
        qb = build_ql_bond(descriptor=descriptor, evaluation_date=as_of, conventions=conv)
        out["ql"] = ql_bond_metrics(bond=qb, evaluation_date=as_of, conventions=conv,
                                    clean_price=clean_price, ytm=ytm)
    except Exception as e:                                   # noqa: BLE001
        out["ql_error"] = f"{type(e).__name__}: {e}"
    try:
        rb = build_rl_bond(descriptor=descriptor, conventions=conv)
        settle = rl_settlement_date(descriptor=descriptor, as_of=as_of, conventions=conv)
        out["rl"] = rl_bond_metrics(bond=rb, settlement=settle, price=clean_price, ytm=ytm)
    except Exception as e:                                   # noqa: BLE001
        out["rl_error"] = f"{type(e).__name__}: {e}"
    return out


def do_build() -> dict:
    """Decide each open question from the fetched numbers, and report the margin."""
    from MDP.CitiVelocityExcel.bonds import BondUniverse

    if not RAW_PATH.exists():
        raise SystemExit(f"{RAW_PATH} not found — run `fetch` first (it needs Excel).")
    raw = json.loads(RAW_PATH.read_text())
    as_of = datetime.date.fromisoformat(raw["as_of"])
    uni = BondUniverse.from_catalog(country="USA", asset_type="GOVT")

    # last served value per (isin, value)
    latest = {}
    for tag, blob in raw["served"].items():
        isin, value = raw["tag_owner"][tag]
        latest[(isin, value)] = (blob["index"][-1], blob["values"][-1])

    rows = []
    for b in raw["bonds"]:
        isin = b["isin"]
        d = uni.lookup(isin)
        if d is None:
            continue
        citi_price = latest.get((isin, "PRICE"), (None, None))[1]
        citi_yield = latest.get((isin, "YIELD"), (None, None))[1]
        citi_dur = latest.get((isin, "DURATION"), (None, None))[1]
        citi_dv01 = latest.get((isin, "DV01"), (None, None))[1]
        if citi_price is None:
            continue

        as_clean = _local_metrics(d, as_of=as_of, clean_price=citi_price)
        m = as_clean.get("ql") or {}
        accrued = m.get("accrued")
        # the same number read as DIRTY: back out the clean it implies
        as_dirty = (
            _local_metrics(d, as_of=as_of, clean_price=citi_price - accrued)
            if accrued is not None else {}
        )
        md = as_dirty.get("ql") or {}

        row = {
            "isin": isin, "desc": b["desc"], "ttm": b["ttm"],
            "accrued_expected": b["accrued"], "accrued_local": accrued,
            "citi_price": citi_price, "citi_yield": citi_yield,
            "citi_duration": citi_dur, "citi_dv01": citi_dv01,
            "ytm_if_price_is_clean": m.get("ytm"),
            "ytm_if_price_is_dirty": md.get("ytm"),
            "local_mod_duration": m.get("mod_duration"),
            "local_macaulay": m.get("macaulay"),
            "local_dv01": m.get("dv01"),
            "local_bps": m.get("bps"),
            "rl_ytm": (as_clean.get("rl") or {}).get("ytm"),
        }
        if citi_yield is not None:
            for k in ("ytm_if_price_is_clean", "ytm_if_price_is_dirty"):
                v = row[k]
                row[k.replace("ytm_if", "yield_err_bp_if")] = (
                    None if v is None else round((v - citi_yield) * 100.0, 4)
                )
        if citi_dur is not None:
            row["dur_err_modified"] = _sub(citi_dur, m.get("mod_duration"))
            row["dur_err_macaulay"] = _sub(citi_dur, m.get("macaulay"))
        if citi_dv01 is not None and m.get("dv01"):
            row["dv01_ratio_citi_over_local"] = round(citi_dv01 / m["dv01"], 6)
        rows.append(row)

    df = pd.DataFrame(rows)
    verdicts = _verdicts(df)
    out = {"as_of": raw["as_of"], "built_at": datetime.datetime.now().isoformat(),
           "n_bonds": len(rows), "rows": rows, "verdicts": verdicts}
    OUT_PATH.write_text(json.dumps(out, indent=1, default=str))

    _report(df, verdicts)
    print(f"\nwrote {OUT_PATH}")
    return out


def _sub(a, b):
    return None if (a is None or b is None) else round(a - b, 6)


def _verdicts(df: pd.DataFrame) -> dict:
    """Decide each question, and say by what margin — a verdict without a margin
    is an opinion."""
    v = {}
    if {"yield_err_bp_if_price_is_clean", "yield_err_bp_if_price_is_dirty"} <= set(df.columns):
        c = df["yield_err_bp_if_price_is_clean"].abs()
        d = df["yield_err_bp_if_price_is_dirty"].abs()
        if c.notna().any() and d.notna().any():
            v["PRICE"] = {
                "verdict": "clean" if c.median() < d.median() else "dirty",
                "median_abs_yield_error_bp_if_clean": round(float(c.median()), 4),
                "median_abs_yield_error_bp_if_dirty": round(float(d.median()), 4),
                "max_abs_yield_error_bp_chosen": round(float(min(c.max(), d.max())), 4),
                "n": int(c.notna().sum()),
            }
    if {"dur_err_modified", "dur_err_macaulay"} <= set(df.columns):
        m = df["dur_err_modified"].abs()
        k = df["dur_err_macaulay"].abs()
        if m.notna().any():
            v["DURATION"] = {
                "verdict": "modified" if m.median() < k.median() else "macaulay",
                "median_abs_error_years_modified": round(float(m.median()), 6),
                "median_abs_error_years_macaulay": round(float(k.median()), 6),
                "n": int(m.notna().sum()),
            }
    if "dv01_ratio_citi_over_local" in df.columns:
        r = df["dv01_ratio_citi_over_local"].dropna()
        if len(r):
            med = float(r.median())
            v["DV01"] = {
                "median_ratio_citi_over_local": round(med, 6),
                "ratio_spread": round(float(r.max() - r.min()), 6),
                "reading": _dv01_reading(med),
                "n": int(len(r)),
            }
    return v


def _dv01_reading(ratio: float) -> str:
    """Name the scale the ratio implies, rather than leaving a bare number."""
    sign = "same sign as this package (positive for a long)" if ratio > 0 else \
        "OPPOSITE sign to this package — Citi reports a long as negative"
    a = abs(ratio)
    for want, label in ((1.0, "per 100 face, same as local"),
                        (10_000.0, "per 1mm face (10,000x local)"),
                        (100.0, "per 10,000 face (100x local)"),
                        (0.01, "per 1 face (local/100)")):
        if abs(a - want) / want < 0.02:
            return f"{label}; {sign}"
    return f"unrecognised scale {a:.6g}x local; {sign}"


def _report(df: pd.DataFrame, verdicts: dict) -> None:
    pd.set_option("display.width", 220, "display.max_columns", 50)
    print("\n" + "=" * 78)
    print("CITI BOND VALUE CALIBRATION")
    print("=" * 78)
    cols = [c for c in ("isin", "desc", "ttm", "accrued_local", "citi_price",
                        "citi_yield", "yield_err_bp_if_price_is_clean",
                        "yield_err_bp_if_price_is_dirty", "citi_duration",
                        "dur_err_modified", "dur_err_macaulay",
                        "dv01_ratio_citi_over_local") if c in df.columns]
    print(df[cols].to_string(index=False))
    print("\nVERDICTS")
    for k, val in verdicts.items():
        print(f"  {k}: {json.dumps(val)}")
    if not verdicts:
        print("  none — nothing served, or too few paired values to decide.")
    print(
        "\nNext: copy each verdict into MDP/CitiVelocityExcel/bonds/values.py, set that\n"
        "ValueSpec's verified=True, and replace its note with the measured margin above."
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("stage", nargs="+", choices=["fetch", "build"],
                   help="fetch touches Excel; build is pure CPU over the fetched JSON")
    p.add_argument("--date", type=datetime.date.fromisoformat,
                   default=datetime.date.today(), help="as-of date (YYYY-MM-DD)")
    p.add_argument("--lookback", type=int, default=30, help="days of history to pull")
    args = p.parse_args()

    if "fetch" in args.stage:
        do_fetch(args.date, lookback_days=args.lookback)
    if "build" in args.stage:
        do_build()


if __name__ == "__main__":
    main()
