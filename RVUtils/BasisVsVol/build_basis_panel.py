"""Build a daily Treasury-futures basis panel for the V1 backtest.

One row per (date, contract root): the front contract's futures price, the CTD and its nearest
challenger with everything the delivery-option models need, and the term financing rate to
delivery taken from the swaps/OIS short end.

    <env>/python.exe -m RVUtils.BasisVsVol.build_basis_panel --root ZB --start 2015-01-01

Design notes that matter:

* **Financing is the swaps-curve term rate to the contract's own delivery date**, not an overnight
  fixing. The Sep-to-Dec term slope alone is worth ~1.8/32 on a Dec ZB contract.
* **The front contract rolls before first notice.** Holding a basis position into the notice period
  is a different trade (delivery risk, margin) and the design excludes it, so the panel rolls at
  ``roll_days_before_fnd`` and marks the roll explicitly -- a roll is never a return.
* **DV01 is computed analytically** from coupon/ytm/maturity rather than re-priced, because
  ``get_basis_report`` does not return it and a second full basket build per day would double an
  already hour-long job. Modified duration from the closed form is within ~1% of a full reprice,
  and the delivery-option value depends on the *gap* between two DV01s, where the error largely
  cancels.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

OUT_DIR = pathlib.Path(__file__).resolve().parents[2] / "notebooks" / "backtests" / "basis_vs_vol" / "_data"
MONTH_CODE = {3: "H", 6: "M", 9: "U", 12: "Z"}
ROOT_ALIAS = {"ZB": "ZB", "US": "ZB", "UB": "UB", "UL": "UB", "ZN": "ZN", "TY": "ZN", "TN": "TN"}


def front_symbol(root: str, on: dt.date, roll_days_before_fnd: int = 7) -> str:
    """Front quarterly contract, rolled ``roll_days_before_fnd`` before first notice.

    First notice is the last business day of the month *preceding* delivery, so rolling a week
    before that keeps every position clear of the delivery window.
    """
    # candidates must be walked CHRONOLOGICALLY: iterating months outer and years inner returns
    # next March before this June and silently picks a contract a year away.
    for yy in (on.year, on.year + 1, on.year + 2):
        for m in (3, 6, 9, 12):
            fnd = dt.date(yy, m, 1) - dt.timedelta(days=1)
            while fnd.weekday() >= 5:
                fnd -= dt.timedelta(days=1)
            if on <= fnd - dt.timedelta(days=roll_days_before_fnd):
                return f"{root}{MONTH_CODE[m]}{str(yy)[-2:]}"
    raise ValueError(f"no front contract for {on}")


_LBL = re.compile(r"T?\s*(\d+)?\s*(\d+)?/?(\d+)?\s*([A-Z][a-z]{2})\s*(\d{2})")


def _mod_duration(coupon: float, ytm: float, years: float, freq: int = 2) -> float:
    """Closed-form modified duration for a semiannual coupon bond, per 100 face."""
    if not np.isfinite(ytm) or not np.isfinite(years) or not np.isfinite(coupon) or years <= 0:
        return float("nan")
    y = ytm / 100.0 / freq
    n = max(int(round(years * freq)), 1)
    c = coupon / 100.0 / freq * 100.0
    t = np.arange(1, n + 1)
    cf = np.full(n, c)
    cf[-1] += 100.0
    df = (1.0 + y) ** (-t)
    pv = cf * df
    price = pv.sum()
    if price <= 0:
        return float("nan")
    mac = float((t * pv).sum() / price / freq)
    return mac / (1.0 + y)


_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def _coupon_years(label: str, as_of: dt.date, maturity=None) -> tuple:
    """Parse '(T) 4 5/8 Nov 44' into (coupon_pct, years_to_maturity).

    The basis report carries no maturity column, so the label is the only source. A two-digit year
    is resolved forward -- every deliverable matures after the trade date.
    """
    yrs = float("nan")
    if maturity is not None and pd.notna(maturity):
        yrs = (pd.Timestamp(maturity).date() - as_of).days / 365.25

    s = str(label).replace("WI-", "").strip()
    s = re.sub(r"^T\s*", "", s)
    m = re.match(r"(\d+)(?:\s+(\d+)/(\d+))?", s)
    cpn = float("nan")
    if m:
        cpn = float(m.group(1))
        if m.group(2):
            cpn += float(m.group(2)) / float(m.group(3))

    if not np.isfinite(yrs):
        mm = re.search(r"([A-Z][a-z]{2})\s*'?(\d{2})", s)
        if mm and mm.group(1) in _MONTHS:
            yy = 2000 + int(mm.group(2))
            if yy < as_of.year:
                yy += 100
            mat = dt.date(yy, _MONTHS[mm.group(1)], 15)
            yrs = (mat - as_of).days / 365.25
    return cpn, yrs


def _flush(rows, out: pathlib.Path) -> None:
    df = pd.DataFrame(rows)
    df["is_roll"] = df["symbol"].ne(df["symbol"].shift(1)) & df["symbol"].shift(1).notna()
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)


def build(root: str, start: dt.date, end: dt.date, out: pathlib.Path,
          roll_days_before_fnd: int = 7, progress_every: int = 100) -> pd.DataFrame:
    from MDP.CitiVelocityExcel.repo import store as R
    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP

    repo_df = R.load()
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    days = pd.bdate_range(start, end)
    rows, fails, first_err = [], 0, None
    if out.exists():  # resume: keep what is already built and only fetch what is missing
        prior = pd.read_parquet(out)
        have = set(pd.to_datetime(prior["date"]))
        rows = prior.drop(columns=[c for c in ("is_roll",) if c in prior], errors="ignore").to_dict("records")
        days = pd.DatetimeIndex([d for d in days if d not in have])
        print(f"{root}: resuming with {len(rows)} rows, {len(days)} days to fetch", flush=True)

    for i, ts in enumerate(days):
        d = ts.date()
        sym = front_symbol(root, d, roll_days_before_fnd)
        try:
            deliv = None
            fin = R.term_financing_rate(repo_df, d, 90)  # provisional; refined below
            rep = mdp.get_basis_report(symbol=sym, timestamp=d,
                                       repo_rate=float(fin) if np.isfinite(fin) else 4.0)
            if rep is None or not len(rep):
                fails += 1
                continue
            if "delivery_date" in rep.columns:
                deliv = pd.to_datetime(rep["delivery_date"].iloc[0]).date()
                h = max((deliv - d).days, 1)
                fin2 = R.term_financing_rate(repo_df, d, h)
                if np.isfinite(fin2) and abs(fin2 - fin) > 0.02:
                    rep = mdp.get_basis_report(symbol=sym, timestamp=d, repo_rate=float(fin2))
                    fin = fin2
            r = rep.sort_values("irr", ascending=False).reset_index(drop=True)
            ctd, alt = r.iloc[0], (r.iloc[1] if len(r) > 1 else r.iloc[0])
            rec = {"date": ts, "root": root, "symbol": sym,
                   "futures_price": float(ctd.get("futures_price", np.nan)),
                   "repo_pct": float(fin), "delivery_date": deliv,
                   "n_deliverable": int(len(r))}
            for tag, b in (("ctd", ctd), ("alt", alt)):
                cpn, yrs = _coupon_years(b.get("label"), d, b.get("maturity_date"))
                ytm = float(b.get("ytm", np.nan))
                px = float(b.get("clean_price", np.nan))
                md = _mod_duration(cpn, ytm, yrs)
                rec.update({
                    f"{tag}_label": b.get("label"), f"{tag}_cf": float(b.get("invoice_cf", np.nan)),
                    f"{tag}_price": px, f"{tag}_ytm": ytm,
                    f"{tag}_bnoc32": float(b.get("bnoc", np.nan)) * 32.0,
                    f"{tag}_gross32": float(b.get("gross_basis", np.nan)) * 32.0,
                    f"{tag}_irr": float(b.get("irr", np.nan)),
                    f"{tag}_dv01": (md * px * 1e-4) if np.isfinite(md) and np.isfinite(px) else np.nan,
                })
            rows.append(rec)
        except Exception as exc:  # a silent skip would look like a market holiday
            fails += 1
            if first_err is None:
                import traceback
                tb = "".join(traceback.format_tb(exc.__traceback__)[-2:])
                first_err = f"{d} {sym}: {type(exc).__name__}: {exc}\n{tb}"
        # checkpoint: a 10-hour job that only writes at the end yields nothing if it is
        # interrupted, and cannot be inspected while it runs.
        if rows and i and i % 50 == 0:
            _flush(rows, out)
        if progress_every and i and i % progress_every == 0:
            print(f"  {root} {d} rows={len(rows)} fails={fails}", flush=True)

    df = pd.DataFrame(rows)
    if not df.empty:
        df["is_roll"] = df["symbol"].ne(df["symbol"].shift(1)) & df["symbol"].shift(1).notna()
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out, index=False)
    if first_err:
        print(f"{root}: FIRST FAILURE -> {first_err}", flush=True)
    print(f"{root}: {len(df)} rows, {fails} failures -> {out}", flush=True)
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="ZB")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    root = ROOT_ALIAS.get(a.root.upper(), a.root.upper())
    out = pathlib.Path(a.out) if a.out else OUT_DIR / f"basis_panel_{root}.parquet"
    build(root, dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end), out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
