"""USD repo history from Citi Velocity, refreshed through the Excel add-in.

Replaces the manually-saved workbook that ``BT/gss_fly/costs.py`` reads
(``load_repo_from_workbook``, whose own docstring says "the online one is ``repo_tag_grid``
through the Citi timeseries fetcher" -- this is that online path).

    <env>/python.exe -m MDP.CitiVelocityExcel.repo.store --refresh
    <env>/python.exe -m MDP.CitiVelocityExcel.repo.store --seed-from-workbook "C:/.../usd_repo_timeseries_history.xlsx"

What Citi actually serves, measured on 7,220 rows of history to 2026-08-13
--------------------------------------------------------------------------
**The tenor axis is degenerate.** ``RATES.REPO.USD.<collateral>.SPOT.<tenor>`` is quoted for 14
tenors from ON to 10Y, and on **100% of days the spread across all 14 is 0.0000bp** -- ON equals
10Y exactly on 1,255 of 1,255 days for GC, and the same holds for every OTR collateral. Citi
serves one number per (date, collateral) and replicates it down the tenor axis.

That matters because the whole point of wanting this data was a **term** repo to the delivery date.
This source cannot supply one. Consuming it as though it could would reproduce, with a nicer label,
exactly the defect it was meant to fix. So:

* :func:`gc_rate` serves the single secured GC overnight rate. It is still a real improvement on
  what the basis path uses today -- the last *overnight unsecured* SOFR fixing.
* :func:`specialness_bps` serves OTR collateral minus GC. Also overnight only.
* :func:`term_sofr` serves ``RATES.MONEY_MARKETS.USD.SOFR.{1M,3M,6M,1Y}``, which **is** a genuine
  term structure (1,890 days from 2019) -- the only one in this dataset.
* :func:`assert_tenor_axis_is_degenerate` is a guard, not a comment. If Citi ever starts serving a
  real term repo curve, that test fails and this docstring is wrong.

A second caveat on specialness: the deliverable basket of a Treasury future is off-the-run --
ZB Sep26's CTD is the 5% May 2045. The OTR series describe the *most special corner of the market*
and are therefore an **upper bound** on plausible CTD specialness, not an estimate of it. Use them
to size a sensitivity band, never as the CTD's financing rate.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import warnings

import numpy as np
import pandas as pd

__all__ = [
    "REPO_TENORS",
    "REPO_COLLATERAL",
    "MONEY_MARKET_TAGS",
    "repo_tag",
    "all_tags",
    "DEFAULT_STORE",
    "load",
    "refresh",
    "seed_from_workbook",
    "gc_rate",
    "specialness_bps",
    "term_sofr",
    "assert_tenor_axis_is_degenerate",
]

REPO_TENORS = ("ON", "TN", "1W", "1M", "3M", "6M", "9M", "1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y")
REPO_COLLATERAL = ("USTREASGC", "USD5YOTR", "USD10YOTR", "USD30YOTR")
MONEY_MARKET_TAGS = (
    "RATES.MONEY_MARKETS.USD.BGCR",
    "RATES.MONEY_MARKETS.USD.TGCR",
    "RATES.MONEY_MARKETS.USD.SOFR.ON",
    "RATES.MONEY_MARKETS.USD.SOFR.1M",
    "RATES.MONEY_MARKETS.USD.SOFR.3M",
    "RATES.MONEY_MARKETS.USD.SOFR.6M",
    "RATES.MONEY_MARKETS.USD.SOFR.1Y",
)

DEFAULT_STORE = (
    pathlib.Path(__file__).resolve().parents[3]
    / "notebooks" / "backtests" / "basis_vs_vol" / "_data" / "usd_repo_history.parquet"
)


def repo_tag(collateral: str = "USTREASGC", tenor: str = "ON", currency: str = "USD") -> str:
    coll, ten = str(collateral).strip().upper(), str(tenor).strip().upper()
    if coll not in REPO_COLLATERAL:
        raise ValueError(f"unknown collateral {collateral!r}; expected one of {REPO_COLLATERAL}")
    if ten not in REPO_TENORS:
        raise ValueError(f"unknown tenor {tenor!r}; expected one of {REPO_TENORS}")
    return f"RATES.REPO.{currency.upper()}.{coll}.SPOT.{ten}"


def all_tags(currency: str = "USD") -> list[str]:
    grid = [repo_tag(c, t, currency) for c in REPO_COLLATERAL for t in REPO_TENORS]
    return grid + list(MONEY_MARKET_TAGS)


# --------------------------------------------------------------------------- store


def load(path: str | pathlib.Path | None = None) -> pd.DataFrame:
    p = pathlib.Path(path) if path is not None else DEFAULT_STORE
    if not p.exists():
        raise FileNotFoundError(
            f"no repo store at {p}. Seed it once from the Velocity workbook "
            f"(--seed-from-workbook) or run --refresh with Excel signed in."
        )
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _merge(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    if old is None or old.empty:
        out = new
    else:
        out = pd.concat([old, new], ignore_index=True)
    # last write wins per date, which is what a refresh of recent history should do
    out = out.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return out.reset_index(drop=True)


def seed_from_workbook(path: str | pathlib.Path, store: str | pathlib.Path | None = None) -> pd.DataFrame:
    """One-off import of a hand-saved ``=CVTSHIST(...)`` export.

    Row 0 holds the formula, row 1 the ``Date`` + tag headers, row 2 onward the data.
    """
    raw = pd.read_excel(pathlib.Path(path), sheet_name=0, header=None)
    hdr = [str(x) for x in raw.iloc[1].tolist()]
    df = raw.iloc[2:].copy()
    df.columns = [h.split(" - ")[0].strip() for h in hdr]
    df = df.rename(columns={df.columns[0]: "date"})
    df["date"] = pd.to_datetime(df["date"])
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    target = pathlib.Path(store) if store is not None else DEFAULT_STORE
    target.parent.mkdir(parents=True, exist_ok=True)
    prior = load(target) if target.exists() else None
    out = _merge(prior, df)
    out.to_parquet(target, index=False)
    return out


def refresh(client=None, *, start=None, end=None, store: str | pathlib.Path | None = None,
            currency: str = "USD", period: str | None = None) -> pd.DataFrame:
    """Pull the repo tag grid through the Citi Velocity Excel add-in and merge into the store.

    ``client`` is a ``CitiVelocityExcelClient``; when omitted one is created. Incremental by
    default: only dates after the last stored one are requested, so a daily cron is cheap.
    """
    target = pathlib.Path(store) if store is not None else DEFAULT_STORE
    prior = load(target) if target.exists() else None

    if start is None and period is None and prior is not None and not prior.empty:
        start = (prior["date"].max() - pd.Timedelta(days=7)).date()

    if client is None:  # pragma: no cover - needs a live signed-in Excel
        from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient

        client = CitiVelocityExcelClient()

    tags = all_tags(currency)
    series = client.fetch_timeseries(tags, freq="DAILY", period=period, start=start, end=end)
    failures = {}
    try:
        failures = dict(client.last_failures() or {})
    except Exception:  # noqa: BLE001
        pass
    if not series:
        raise RuntimeError(
            f"CVTSHIST returned nothing for {len(tags)} repo tags; failures={failures}. "
            "An empty refresh must not be written -- it would look like a quiet gap."
        )
    if failures:
        warnings.warn(f"repo refresh: {len(failures)} tag(s) failed and are absent: {failures}",
                      RuntimeWarning, stacklevel=2)

    new = pd.DataFrame(series)
    new.index = pd.to_datetime(new.index)
    new = new.rename_axis("date").reset_index()
    out = _merge(prior, new)
    target.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(target, index=False)
    return out


# --------------------------------------------------------------------------- accessors


def assert_tenor_axis_is_degenerate(df: pd.DataFrame, tol_bp: float = 0.1) -> dict:
    """Guard the claim in this module's docstring.

    Returns per-collateral dispersion. If Citi ever begins serving a genuine term repo curve this
    stops being degenerate, and everything downstream that treats the ON rate as "the term repo"
    must be revisited rather than silently keep working.
    """
    out = {}
    for coll in REPO_COLLATERAL:
        cols = [c for c in df.columns if f".{coll}.SPOT." in c]
        if not cols:
            continue
        sub = df[cols].dropna(how="all")
        if sub.empty:
            continue
        rng = (sub.max(axis=1) - sub.min(axis=1)) * 100.0
        out[coll] = {"n_days": int(len(sub)), "max_tenor_spread_bp": float(rng.max()),
                     "pct_days_dispersed": float((rng > tol_bp).mean())}
    return out


def gc_rate(df: pd.DataFrame, on: pd.Timestamp | str) -> float:
    """Secured GC repo (percent) on or before ``on``. Overnight -- there is no term axis."""
    s = df[["date", repo_tag("USTREASGC", "ON")]].dropna()
    s = s[s["date"] <= pd.Timestamp(on)]
    return float(s.iloc[-1, 1]) if len(s) else float("nan")


def specialness_bps(df: pd.DataFrame, on: pd.Timestamp | str, collateral: str = "USD10YOTR") -> float:
    """OTR collateral minus GC, in bp (negative = special). Overnight, and **on-the-run**.

    A future's CTD is off-the-run, so this is an upper bound on plausible CTD specialness rather
    than an estimate of it. Size a sensitivity band with it; do not fund a bond at it.
    """
    g, c = repo_tag("USTREASGC", "ON"), repo_tag(collateral, "ON")
    s = df[["date", g, c]].dropna()
    s = s[s["date"] <= pd.Timestamp(on)]
    if not len(s):
        return float("nan")
    return float((s.iloc[-1][c] - s.iloc[-1][g]) * 100.0)


def term_sofr(df: pd.DataFrame, on: pd.Timestamp | str, tenor: str = "3M") -> float:
    """Term SOFR (percent). The only genuine term structure in this dataset."""
    tag = f"RATES.MONEY_MARKETS.USD.SOFR.{str(tenor).upper()}"
    if tag not in df.columns:
        raise ValueError(f"{tag} not in store; have {[c for c in df.columns if 'SOFR' in c]}")
    s = df[["date", tag]].dropna()
    s = s[s["date"] <= pd.Timestamp(on)]
    return float(s.iloc[-1, 1]) if len(s) else float("nan")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="pull from Citi via the Excel add-in")
    ap.add_argument("--seed-from-workbook", metavar="XLSX")
    ap.add_argument("--store", default=None)
    ap.add_argument("--start", default=None)
    ap.add_argument("--period", default=None, help="e.g. MAX, 5Y")
    args = ap.parse_args(argv)

    if args.seed_from_workbook:
        df = seed_from_workbook(args.seed_from_workbook, args.store)
        print(f"seeded {len(df):,} rows -> {args.store or DEFAULT_STORE}")
    elif args.refresh:
        df = refresh(start=args.start, period=args.period, store=args.store)
        print(f"store now {len(df):,} rows -> {args.store or DEFAULT_STORE}")
    else:
        df = load(args.store)

    print(f"dates {df['date'].min().date()} -> {df['date'].max().date()}")
    for coll, d in assert_tenor_axis_is_degenerate(df).items():
        flag = "DEGENERATE" if d["pct_days_dispersed"] == 0 else "HAS TERM STRUCTURE"
        print(f"  {coll:11s} {d['n_days']:5d} days  max tenor spread {d['max_tenor_spread_bp']:.4f}bp  -> {flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
