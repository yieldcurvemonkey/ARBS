r"""The per-currency matrix and the +/-1bp tie-out, for all 20 curves in all 3 modes.

Run offline against the banked tag cache (this is the normal way)::

    <env>/python.exe MDP/IRSwaps/CITIVELO_EXCEL/verify_matrix.py --offline

or live, against a signed-in Excel, to refresh the cache first::

    <env>/python.exe MDP/IRSwaps/CITIVELO_EXCEL/verify_matrix.py

What it reports, and what each number is worth
-----------------------------------------------
* **The mode matrix.** For every curve x mode: how many tenors served, the
  snapshot instant, how stale it is, and - when it fails - which exception and
  why. A currency that cannot serve a mode is a finding, not a reason to drop it.
* **The tie-out.** Every check in :mod:`MDP.IRSwaps.CITIVELO_EXCEL.tie_out`, run
  through ``IRSwapsMDP -> IRSwapQuery -> IRSwapStructure``. The headline is the
  ``forward`` check, because it is the only one where the comparison number came
  from Citi and not from us.

The ``forward`` check runs in **EOD mode only**, deliberately. Citi publishes
``RATES.OIS.<idx>.FWD.*`` on the daily series; comparing a 10:50 intraday curve
against a daily forward would be measuring the time of day, and reporting that as
a curve error would be dishonest in the direction that flatters the result.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import pathlib
import sys
import warnings
from typing import Any, Dict, List, Optional, Sequence

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402

from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes  # noqa: E402
from MDP.IRSwaps.CITIVELO_EXCEL import register, supported_curve_names  # noqa: E402
from MDP.IRSwaps.CITIVELO_EXCEL.tie_out import tie_out_curve, tie_out_frame  # noqa: E402

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

NY = ZoneInfo("America/New_York")
OUT_DIR = _REPO_ROOT / "MDP" / "IRSwaps" / "CITIVELO_EXCEL" / "verification"


def _rule(title: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def mode_matrix(
    *,
    eod_date: datetime.date,
    intraday_at: datetime.datetime,
    offline: bool,
    curves: Sequence[str],
) -> pd.DataFrame:
    """Fetch every curve in every mode and record exactly what happened."""
    from MDP.IRSwaps.CITIVELO_EXCEL import CitiVeloExcelCurveFetcher

    fetcher = CitiVeloExcelCurveFetcher(offline=offline)
    rows: List[Dict[str, Any]] = []
    modes = (("eod", eod_date), ("intraday", intraday_at), ("live", "live"))
    for name in curves:
        for mode, when in modes:
            row: Dict[str, Any] = {"curve_name": name, "mode": mode}
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    snap = fetcher.snapshot(name, when)
                row.update(
                    ok=True,
                    n_tenors=len(snap.par_rates),
                    snapshot_at=snap.snapshot_at.isoformat(),
                    lag_min=round(snap.lag.total_seconds() / 60.0, 1),
                    spread_s=round(snap.constituent_spread.total_seconds(), 1),
                    tenors_missing=",".join(snap.tenors_missing),
                    warnings="; ".join(str(w.message)[:80] for w in caught) or None,
                    rate_10y=snap.par_rates.get("10Y"),
                )
            except Exception as exc:  # noqa: BLE001 - the failure IS the finding
                row.update(ok=False, error=f"{type(exc).__name__}", reason=str(exc)[:220])
            rows.append(row)
    fetcher.close()
    return pd.DataFrame(rows)


def run_tie_out(
    *,
    eod_date: datetime.date,
    intraday_at: datetime.datetime,
    offline: bool,
    curves: Sequence[str],
) -> pd.DataFrame:
    quotes = CitiVeloQuotes(offline=offline)
    rows = []
    plans = (
        ("eod", eod_date, ("par", "forward", "interpolation", "backends")),
        ("intraday", intraday_at, ("par", "backends")),
        ("live", "live", ("par", "backends")),
    )
    for name in curves:
        for mode, when, checks in plans:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    rows.extend(
                        tie_out_curve(
                            curve_name=name,
                            mode=mode,
                            timestamp=when,
                            quotes=quotes,
                            checks=checks,
                            mdp_kwargs={"offline": offline},
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"  {name:<20} {mode:<9} RAISED {type(exc).__name__}: {str(exc)[:120]}")
    quotes.close()
    return tie_out_frame(rows)


def forward_stability(
    *, curves: Sequence[str], start: datetime.date, end: datetime.date
) -> pd.DataFrame:
    """Is a forward residual a persistent BIAS or day-to-day NOISE?

    A single day's tie-out cannot tell those apart, and they mean opposite things.
    A bias whose mean dwarfs its standard deviation is a convention or
    curve-construction difference and will not average away; noise around zero is
    a timing artefact between Citi's PAR row and its FWD row for the same day.

    Measured over 39 business days to 2026-08-06, the split was unambiguous:
    ``USD 10Yx10Y`` mean -0.004 bp / sd 0.008 bp (the comparison itself is exact),
    ``USD 1Yx1Y`` mean -0.257 / sd 1.132 (noise), ``THB 10Yx10Y`` mean +4.257 /
    sd 0.366 (bias).

    Builds curves directly rather than through the MDP - it needs one curve per
    day per currency and the source layer adds nothing the question depends on.
    """
    from MDP.CitiVelocityExcel.curves.rl_builder import build_rl_ois_curve, forward_rate
    from MDP.IRSwaps.CITIVELO_EXCEL import CitiVeloExcelCurveFetcher, citi_index_for_curve_name
    from MDP.IRSwaps.CITIVELO_EXCEL.tie_out import FORWARD_POINTS

    fetcher = CitiVeloExcelCurveFetcher(offline=True)
    quotes = CitiVeloQuotes(offline=True)
    dates = [d.date() for d in pd.bdate_range(start, end)]
    rows: List[Dict[str, Any]] = []
    for name in curves:
        citi_index = citi_index_for_curve_name(name)
        tags = {f"RATES.OIS.{citi_index}.FWD.{e}.{t}": (e, t) for e, t in FORWARD_POINTS}
        published = quotes.frame(
            list(tags), "DAILY", start=start - datetime.timedelta(days=10), end=end
        )
        if published.empty:
            continue
        errors: Dict[str, List[float]] = {f"{e}x{t}": [] for e, t in FORWARD_POINTS}
        for day in dates:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    snap = fetcher.snapshot(name, day)
                if snap.reference_date != day:
                    continue  # a holiday rolled back; not a like-for-like comparison
                curve = build_rl_ois_curve(
                    par_rates=snap.par_rates, ref_date=day, citi_index=citi_index
                )
            except Exception:  # noqa: BLE001 - a missing day is not a finding here
                continue
            for tag, (expiry, tenor) in tags.items():
                if tag not in published.columns:
                    continue
                series = published[tag].dropna()
                series = series[series.index <= pd.Timestamp(day)]
                if series.empty or series.index[-1].date() != day:
                    continue
                try:
                    model = forward_rate(curve, forward=expiry, tenor=tenor)
                except Exception:  # noqa: BLE001
                    continue
                errors[f"{expiry}x{tenor}"].append((model - float(series.iloc[-1])) * 100.0)
        for point, values in errors.items():
            if not values:
                continue
            series = pd.Series(values, dtype=float)
            rows.append(
                {
                    "curve_name": name,
                    "point": point,
                    "n_days": int(series.size),
                    "mean_bp": float(series.mean()),
                    "sd_bp": float(series.std()),
                    "min_bp": float(series.min()),
                    "max_bp": float(series.max()),
                    # >2 means the residual survives averaging: a convention, not timing.
                    "bias_to_noise": float(abs(series.mean()) / series.std())
                    if series.std() > 0
                    else float("inf"),
                }
            )
    fetcher.close()
    quotes.close()
    return pd.DataFrame(rows)


def _summarise(frame: pd.DataFrame) -> pd.DataFrame:
    """Worst absolute error per curve x mode x check, plus how many rows errored."""
    if frame.empty:
        return frame
    grouped = frame.groupby(["curve_name", "mode", "check", "backend"], dropna=False)
    return grouped.agg(
        n=("point", "size"),
        n_err=("error", lambda s: int(s.notna().sum())),
        worst_abs_bp=("abs_err_bp", "max"),
        median_abs_bp=("abs_err_bp", "median"),
    ).reset_index()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--offline", action="store_true", help="serve only from the tag cache")
    parser.add_argument("--eod-date", default="2026-08-06")
    parser.add_argument("--intraday-at", default="2026-08-06T10:30")
    parser.add_argument("--only", default="", help="comma-separated curve names")
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--tolerance-bp", type=float, default=1.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    register()
    curves = [c.strip().upper() for c in args.only.split(",") if c.strip()] or supported_curve_names()
    eod_date = datetime.date.fromisoformat(args.eod_date)
    intraday_at = datetime.datetime.fromisoformat(args.intraday_at).replace(tzinfo=NY)

    _rule(f"1. mode matrix - {len(curves)} curves x 3 modes  (offline={args.offline})")
    matrix = mode_matrix(
        eod_date=eod_date, intraday_at=intraday_at, offline=args.offline, curves=curves
    )
    pivot = matrix.pivot(index="curve_name", columns="mode", values="n_tenors")
    pivot = pivot.reindex(columns=["eod", "intraday", "live"]).reindex(curves)
    print(pivot.fillna("FAIL").to_string())
    failed = matrix[~matrix["ok"].fillna(False)]
    if not failed.empty:
        print(f"\n  {len(failed)} (curve, mode) combination(s) did not serve:")
        for _, r in failed.iterrows():
            print(f"    {r['curve_name']:<20}{r['mode']:<10}{r['error']}: {r['reason'][:150]}")
    matrix.to_csv(out_dir / "mode_matrix.csv", index=False)
    print(f"\n  -> {out_dir / 'mode_matrix.csv'}")

    _rule("2. tie-out through MDP -> Query -> Structure")
    frame = run_tie_out(
        eod_date=eod_date, intraday_at=intraday_at, offline=args.offline, curves=curves
    )
    if frame.empty:
        print("  NO ROWS - nothing was priced.")
        return 3
    frame.to_csv(out_dir / "tie_out_rows.csv", index=False)
    summary = _summarise(frame)
    summary.to_csv(out_dir / "tie_out_summary.csv", index=False)

    for check in ("forward", "par", "backends", "interpolation"):
        sub = summary[summary["check"] == check]
        if sub.empty:
            continue
        print(f"\n-- {check}: worst |error| in bp, per curve and backend")
        wide = sub.pivot_table(
            index="curve_name", columns=["mode", "backend"], values="worst_abs_bp"
        )
        print(wide.reindex(curves).to_string(float_format=lambda v: f"{v:9.4f}"))

    _rule(f"3. verdict at +/-{args.tolerance_bp} bp")
    fwd = frame[(frame["check"] == "forward") & frame["err_bp"].notna()]
    if fwd.empty:
        print("  no published-forward comparisons ran - the +/-1bp claim CANNOT be made.")
        verdict = 4
    else:
        worst = fwd.loc[fwd["abs_err_bp"].idxmax()]
        n_bad = int((fwd["abs_err_bp"] > args.tolerance_bp).sum())
        print(f"  published-forward comparisons : {len(fwd)}")
        print(f"  curves covered                : {fwd['curve_name'].nunique()}")
        print(f"  worst |error|                 : {worst['abs_err_bp']:.4f} bp "
              f"({worst['curve_name']} {worst['point']} {worst['backend']})")
        print(f"  outside +/-{args.tolerance_bp} bp            : {n_bad}")
        if n_bad:
            bad = fwd[fwd["abs_err_bp"] > args.tolerance_bp]
            print(bad[["curve_name", "mode", "backend", "point", "citi", "model", "err_bp"]].to_string(index=False))
        verdict = 0 if n_bad == 0 else 1

    missing = sorted(set(curves) - set(fwd["curve_name"].unique())) if not fwd.empty else list(curves)
    if missing:
        print(f"\n  NOT covered by the published-forward check ({len(missing)}): {missing}")
        print("  (Citi publishes no RATES.OIS.<idx>.FWD.* tags for these, so the only available "
              "comparison is against their own calibration inputs.)")

    interp = frame[(frame["check"] == "interpolation") & frame["err_bp"].notna()]
    if not interp.empty:
        w = interp.loc[interp["abs_err_bp"].idxmax()]
        print(f"\n  drop-one-out interpolation, worst : {w['abs_err_bp']:.4f} bp "
              f"({w['curve_name']} {w['point']})")
        print("  This is a property of log-linear interpolation across a wide node gap, not a "
              "source defect - but it bounds what an OFF-node quote is worth on these curves.")

    (out_dir / "verdict.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.datetime.now(NY).isoformat(),
                "offline": bool(args.offline),
                "eod_date": eod_date.isoformat(),
                "intraday_at": intraday_at.isoformat(),
                "tolerance_bp": args.tolerance_bp,
                "n_curves": len(curves),
                "forward_comparisons": int(len(fwd)),
                "forward_worst_abs_bp": float(fwd["abs_err_bp"].max()) if not fwd.empty else None,
                "forward_outside_tolerance": int((fwd["abs_err_bp"] > args.tolerance_bp).sum())
                if not fwd.empty
                else None,
                "curves_without_published_forwards": missing,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\n  -> {out_dir / 'verdict.json'}")
    return verdict


if __name__ == "__main__":
    sys.exit(main())
