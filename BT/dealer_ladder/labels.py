"""G0 — the closest thing available to a direction-accuracy measurement.

There are no truth labels. No desk tickets or confirmations were available, so the
classifier's direction cannot be validated against ground truth and this study
never claims an accuracy number.

What CAN be done is a **pseudo-label** study. The direction call is a comparison of
a traded price to a curve mid, so its most likely failure mode is not a broken rule
but a bad mid — and the mid comes from a BARCHART-futures-derived curve, the same
family of prices the study later tries to predict. Re-running the *identical*
classifier against an INDEPENDENT mid therefore isolates exactly that failure mode:
any print whose direction flips was decided by curve disagreement, not by the rule.

The independent mids available:

``citivelo``            Citi Velocity `CVTSHIST` intraday USD SOFR par curve, ~927
                        warmed days. Swap-quote derived, so genuinely independent
                        of the futures strip. **Coverage hole: the source workbook's
                        sheets run Mon 00:01 -> Fri 11:59, so Friday afternoons have
                        no mid — and the reader does NOT fail there, it returns the
                        last available snapshot.** A 14:00 Friday request was
                        measured resolving successfully against an 11:59 curve. Every
                        comparison is therefore staleness-checked and a stale curve
                        counts as NO COVERAGE, never as agreement or as a flip.
``eris_live_intraday``  ERIS live SOFR snapshots. A second independent source, but
                        only a couple of days exist, so it is a spot check.

Both are USD **SOFR** curves. FED_FUNDS prints therefore have NO independent mid
here, and the flip study covers the SOFR universe only — a limitation of the study,
not a property of the FF prints.

Scale of the thing being measured, measured: on 2026-03-10 a 2Y swap priced 0.09 to
0.37 bp apart on the two curves. Typical on-market spread-to-mid is around half a
0.5 bp tick, so **curve disagreement is the same order as the signal the direction
call is reading**. That is the audit's point restated with numbers, and it is why
this gate exists.

The flip rate is a LOWER bound on disagreement-driven error and not an accuracy:
both curves can be wrong together, and a flip does not say which one was right.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from SDRUtils.stir_flow.classifier import classify_unit
from SDRUtils.stir_flow.pricing import CurvePricer, snap_timestamp

INDEPENDENT_SOURCES = {
    "citivelo": "USD-SOFR-1D",
    "eris_live_intraday": "USD-SOFR-1D",
}
# The classifier's own curves, for reference in the output.
OUR_CURVE_BY_INDEX = {
    "SOFR": "USD-SOFR-1D-Q12xM12STIRT",
    "FED_FUNDS": "USD-OIS-Q12xM12STIRT-SERFFX-MIX23",
}


def independent_pricer(source="citivelo") -> CurvePricer:
    """A ``CurvePricer`` backed by an independent curve source.

    Deliberately the SAME pricing wrapper the classifier uses, so the only thing
    that differs between our direction and the independent one is the curve. Any
    other difference would make a flip uninterpretable.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    if source not in INDEPENDENT_SOURCES:
        raise ValueError(f"unknown independent source {source!r}; "
                         f"expected one of {sorted(INDEPENDENT_SOURCES)}")
    return CurvePricer(mdp=IRSwapsMDP(source=source))


MAX_CURVE_STALENESS_MIN = 5.0


def _curve_timestamp(handle):
    """The independent curve's OWN timestamp, or NaT.

    Load-bearing: the citivelo reader defaults to ``method="asof"``, so a request
    for a minute the source does not cover returns the LAST AVAILABLE snapshot
    rather than failing. Measured directly — a 14:00 Friday request resolved
    successfully against an 11:59 curve, because the source workbook's sheets run
    Mon 00:01 to Fri 11:59. Treating that as "an independent mid at 14:00" would
    compare a trade to a mid from two hours earlier and score the difference as a
    classification flip, which is exactly the wrong conclusion.
    """
    try:
        meta = handle.meta() if hasattr(handle, "meta") else {}
        return pd.Timestamp(meta.get("timestamp"))
    except Exception:
        return pd.NaT


def reclassify_one(unit, direction_row, pricer, curve_name,
                   max_staleness_min=MAX_CURVE_STALENESS_MIN) -> dict:
    """Re-run the classifier on ``unit`` against ``curve_name``. Never raises.

    Returns a row carrying the independent direction and its spread-to-mid, or a
    ``reason`` when the independent curve could not price the unit — a missing mid
    must be visible as missing, because silently dropping it would bias the flip
    rate toward whichever days the independent source happens to cover.

    A curve whose own timestamp is more than ``max_staleness_min`` behind the
    decision minute is treated as NO COVERAGE, not as a comparison.
    """
    first = unit.legs.iloc[0]
    snap = snap_timestamp(first.get("original_execution_timestamp"),
                          first["execution_timestamp"])
    out = {
        "unit_key": direction_row["unit_key"],
        "as_of_date": first["as_of_date"],
        "snap_ts": snap,
        "trade_type": unit.kind,
        "rate_index_clean": first["rate_index_clean"],
        "our_direction": direction_row.get("dealer_direction"),
        "our_method": direction_row.get("classification_method"),
        "our_s2m_bps": direction_row.get("spread_to_mid_bps"),
        "our_confidence": direction_row.get("direction_confidence"),
        "our_curve_suspect": bool(direction_row.get("curve_suspect_trade")),
        "ind_direction": None,
        "ind_method": None,
        "ind_s2m_bps": np.nan,
        "ind_curve_ts": pd.NaT,
        "ind_staleness_min": np.nan,
        "coverage_ok": False,
        "reason": None,
    }
    try:
        handle = pricer.handle(curve_name, snap)
        curve_ts = _curve_timestamp(handle)
        out["ind_curve_ts"] = curve_ts
        if pd.notna(curve_ts):
            ct = curve_ts.tz_localize("America/New_York") if curve_ts.tzinfo is None \
                else curve_ts.tz_convert("America/New_York")
            stale = (pd.Timestamp(snap).tz_convert("America/New_York") - ct)
            out["ind_staleness_min"] = stale.total_seconds() / 60.0
            if abs(out["ind_staleness_min"]) > max_staleness_min:
                out["reason"] = (f"STALE_INDEPENDENT_CURVE "
                                 f"({out['ind_staleness_min']:.0f}min)")
                return out

        pricings = []
        for _, leg in unit.legs.iterrows():
            fixed = float(leg["fixed_rate"]) if unit.is_off_market else None
            pricings.append(pricer.price_leg(
                curve_name, snap, leg["effective_date"], leg["expiration_date"],
                notional=float(leg["notional"]), fixed_rate=fixed))
        res = classify_unit(unit, pricings)
        out["ind_direction"] = res.dealer_direction
        out["ind_method"] = res.classification_method
        out["ind_s2m_bps"] = res.spread_to_mid_bps
        out["coverage_ok"] = res.dealer_direction in ("PAID", "RECEIVED")
        if not out["coverage_ok"]:
            out["reason"] = "INDEPENDENT_UNKNOWN"
    except Exception as exc:  # noqa: BLE001 — a missing mid is data, not a crash
        out["reason"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return out


def stratified_sample(direction_rows, *, per_day=40, seed=0) -> list:
    """Sample up to ``per_day`` rows per session, SPREAD ACROSS the session.

    A plain head-N is biased in a way that matters here. A first smoke took the
    first 25 rows of a day and got prints from 02:16-03:59 ET — the thinnest part of
    the overnight session, where mid quality is worst and a flip rate would read high
    for reasons that have nothing to do with the classifier. Sampling is therefore
    stratified by execution HOUR within each session and then randomised inside the
    hour, so the flip rate describes the day rather than its quietest corner.
    """
    rng = np.random.default_rng(seed)
    rows = list(direction_rows)
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    if "as_of_date" not in frame.columns or "execution_timestamp" not in frame.columns:
        return rows[:per_day] if per_day else rows
    ts = pd.to_datetime(frame["execution_timestamp"], utc=True, errors="coerce")
    frame["_hour"] = ts.dt.tz_convert("America/New_York").dt.hour
    keep = []
    for _day, day_rows in frame.groupby("as_of_date", sort=True):
        hours = list(day_rows.groupby("_hour"))
        if not hours:
            continue
        per_hour = max(1, per_day // max(len(hours), 1))
        picked = []
        for _h, hour_rows in hours:
            take = min(per_hour, len(hour_rows))
            picked.extend(hour_rows.sample(take, random_state=int(rng.integers(1e9)))
                          .index.tolist())
        # top up to per_day from whatever is left, so a thin-hour day is not starved
        if per_day and len(picked) < per_day:
            rest = day_rows.index.difference(pd.Index(picked))
            extra = min(per_day - len(picked), len(rest))
            if extra:
                picked.extend(pd.Index(rest).to_series()
                              .sample(extra, random_state=int(rng.integers(1e9)))
                              .tolist())
        keep.extend(picked[:per_day] if per_day else picked)
    return [rows[i] for i in sorted(keep)]


def reclassify_units(units_by_key, direction_rows, *, source="citivelo",
                     limit=0, max_staleness_min=MAX_CURVE_STALENESS_MIN,
                     per_day=0, seed=0) -> pd.DataFrame:
    """Re-classify units the independent source could cover.

    ``direction_rows`` is an iterable of dicts from ``arbs_stir_direction_v1``.
    Only SOFR units are attempted: both independent sources are SOFR curves.

    ``per_day`` caps the work with a time-of-day-stratified sample. Worth using: the
    independent curve is read once per distinct decision minute, and over a six-month
    window that is tens of thousands of reads for a statistic that a few thousand
    prints already pins. ``limit`` is the blunt cap and is applied after sampling.
    """
    curve_name = INDEPENDENT_SOURCES[source]
    pricer = independent_pricer(source)
    rows_in = [d for d in direction_rows if d.get("rate_index_clean") == "SOFR"
               and d.get("unit_key") in units_by_key]
    if per_day:
        rows_in = stratified_sample(rows_in, per_day=per_day, seed=seed)
    rows = []
    for n, drow in enumerate(rows_in):
        if limit and n >= limit:
            break
        rows.append(reclassify_one(units_by_key[drow["unit_key"]], drow, pricer,
                                   curve_name, max_staleness_min=max_staleness_min))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["agrees"] = np.where(
        df["coverage_ok"] & df["our_direction"].isin(["PAID", "RECEIVED"]),
        df["ind_direction"] == df["our_direction"], np.nan)
    df["flipped"] = np.where(df["agrees"].notna(), 1.0 - df["agrees"], np.nan)
    return df


def flip_rate_table(recon: pd.DataFrame, by=("our_confidence",)) -> pd.DataFrame:
    """Flip rate by stratum, WITH the coverage denominator alongside.

    ``n_compared`` is the honest denominator; ``n_no_coverage`` is reported beside
    it so a stratum the independent source barely covers cannot masquerade as a
    clean agreement rate.
    """
    if recon.empty:
        return pd.DataFrame(columns=list(by) + ["n_units", "n_compared",
                                               "n_no_coverage", "flip_rate"])
    grp = recon.groupby(list(by), dropna=False)
    out = grp.agg(
        n_units=("unit_key", "nunique"),
        n_compared=("flipped", lambda s: int(s.notna().sum())),
        flip_rate=("flipped", "mean"),
    ).reset_index()
    nocov = grp.apply(lambda g: int((~g["coverage_ok"]).sum()),
                      include_groups=False).rename("n_no_coverage").reset_index()
    return out.merge(nocov, on=list(by), how="left")


def direction_skew_table(recon: pd.DataFrame, by=()) -> pd.DataFrame:
    """PAID share under OUR mid vs under the INDEPENDENT mid, side by side.

    This is what adjudicates the ~67-72% PAID skew. If our mid produces 72% PAID
    and an independent mid produces ~50% on the same prints, the skew is a mid
    artefact. If both produce ~72%, it is either real flow or a bias the two
    curves share.
    """
    if recon.empty:
        return pd.DataFrame()
    df = recon[recon["flipped"].notna()]
    if df.empty:
        return pd.DataFrame()
    keys = list(by)
    grp = df.groupby(keys, dropna=False) if keys else df.groupby(lambda _: "ALL")
    out = grp.apply(lambda g: pd.Series({
        "n": len(g),
        "our_paid_share": float((g["our_direction"] == "PAID").mean()),
        "ind_paid_share": float((g["ind_direction"] == "PAID").mean()),
        "flip_rate": float(g["flipped"].mean()),
    }), include_groups=False)
    return out.reset_index()


def implied_accuracy_bounds(flip_rate: float) -> dict:
    """Translate a flip rate into the attenuation band it implies.

    If two independent mids disagree on a share ``f`` of prints and each is right
    on the disagreements half the time, the accuracy of either is bounded above by
    ``1 - f/2``. That is a CEILING under a benign assumption, not an estimate:
    correlated mid errors make both worse simultaneously and this arithmetic cannot
    see them. Reported so the attenuation grid can be anchored to something
    measured rather than assumed.
    """
    if flip_rate is None or not np.isfinite(flip_rate):
        return {"flip_rate": np.nan, "accuracy_ceiling": np.nan,
                "attenuation_at_ceiling": np.nan}
    a = 1.0 - float(flip_rate) / 2.0
    return {"flip_rate": float(flip_rate), "accuracy_ceiling": a,
            "attenuation_at_ceiling": 2.0 * a - 1.0}
