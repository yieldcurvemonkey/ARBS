# SDRUtils/stir_flow/book.py
"""Layer 2: synthetic single-dealer book MTM (ladder spec section 5)."""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd
import pytz

from SDRUtils.stir_flow import config
from SDRUtils.stir_flow import ladder_conventions as conv
from SDRUtils.stir_flow import ladder_state
from SDRUtils.stir_flow import vintage

NY = pytz.timezone("America/New_York")


def snap_mtm(ts):
    """The MTM mark instant: floor to the minute, with NO minus-one.

    Routed through ``as_intraday_instant`` for the same reason
    ``snap_timestamp`` is: this rule produces exactly midnight for anything in
    the 00:00 ET minute, and a source that overloads the timestamp argument
    reads midnight as end-of-day and marks the book against the day's CLOSE.
    """
    from SDRUtils.stir_flow.pricing import as_intraday_instant

    et = pd.Timestamp(ts)
    et = et.tz_convert(NY) if et.tzinfo else NY.localize(et.to_pydatetime())
    et = et.replace(second=0, microsecond=0)
    return as_intraday_instant(
        NY.localize(datetime.datetime(et.year, et.month, et.day, et.hour, et.minute))
    )


def reval_unit(legs, signs, pricer, curve_name, ts) -> float:
    npv = 0.0
    for (_, leg), sign in zip(legs.iterrows(), signs):
        lp = pricer.price_leg(curve_name, ts, leg["effective_date"], leg["expiration_date"],
                              notional=float(leg["notional"]),
                              fixed_rate=float(leg["fixed_rate"]))
        npv += -sign * lp.npv_pay
    return npv


def open_positions(prints_meta, unwinds, ts, half_lives,
                   eps_half_lives: float = conv.EPS_HALF_LIVES) -> pd.DataFrame:
    per_unit = prints_meta.drop_duplicates("unit_key").copy()
    if unwinds is not None and len(unwinds):
        dead = unwinds[pd.to_datetime(unwinds["unwind_visibility_ts"]) <= pd.Timestamp(ts)]
        per_unit = per_unit[~per_unit["unit_key"].isin(set(dead["unit_key"]))]
    w = ladder_state.print_weights(per_unit, ts, half_lives)
    eps = 0.5 ** eps_half_lives
    keep = w[w > eps]
    out = per_unit[per_unit["unit_key"].isin(keep.index)].copy()
    out["weight"] = out["unit_key"].map(keep)
    return out


@dataclasses.dataclass
class BookSnapshot:
    ts: object
    ladders: dict
    per_unit: pd.DataFrame
    gross_pnl_usd: float
    residual_pnl_usd: float


def book_snapshot(units_by_key, direction_rows, prints, unwinds, pricer, ts, *,
                  half_lives=None, weighting="expected", include_suspect=False,
                  entry_marks=None) -> BookSnapshot:
    half_lives = half_lives or conv.PROVISIONAL_HALF_LIVES_MIN
    mts = snap_mtm(ts)
    ladders = {
        space: ladder_state.ladder_at(prints, ts, space=space, half_lives=half_lives,
                                      weighting=weighting, include_suspect=include_suspect,
                                      unwinds=unwinds)
        for space in sorted(prints["bucket_space"].unique())
    }
    open_df = open_positions(prints, unwinds, ts, half_lives)
    recs = []
    for _, row in open_df.iterrows():
        key = row["unit_key"]
        unit = units_by_key.get(key)
        drow = direction_rows.get(key)
        if unit is None or drow is None:
            continue
        curve_name = config.CURVE_FOR[drow["rate_index_clean"]]
        signs = conv.dealer_leg_signs(unit.kind, drow["classification_method"],
                                      drow["dealer_direction"], len(unit.legs))
        npv = reval_unit(unit.legs, signs, pricer, curve_name, mts)
        entry = (entry_marks or {}).get(key, 0.0)
        recs.append(dict(unit_key=key, npv_usd=npv, entry_npv_usd=entry,
                         pnl_usd=npv - entry, weight=row["weight"]))
    cols = ["unit_key", "npv_usd", "entry_npv_usd", "pnl_usd", "weight"]
    per_unit = pd.DataFrame(recs, columns=cols) if recs else pd.DataFrame(columns=cols)
    gross = float(per_unit["pnl_usd"].sum()) if len(per_unit) else 0.0
    residual = float((per_unit["pnl_usd"] * per_unit["weight"]).sum()) if len(per_unit) else 0.0
    return BookSnapshot(ts=ts, ladders=ladders, per_unit=per_unit,
                        gross_pnl_usd=gross, residual_pnl_usd=residual)


def eod_mark_rows(units_by_key, direction_rows, entry_marks, pricer, mark_date,
                  open_unit_keys) -> list:
    mark_ts = NY.localize(datetime.datetime(mark_date.year, mark_date.month, mark_date.day, 17, 0))
    rows = []
    for key in open_unit_keys:
        unit, drow = units_by_key.get(key), direction_rows.get(key)
        if unit is None or drow is None:
            continue
        curve_name = config.CURVE_FOR[drow["rate_index_clean"]]
        signs = conv.dealer_leg_signs(unit.kind, drow["classification_method"],
                                      drow["dealer_direction"], len(unit.legs))
        npv = reval_unit(unit.legs, signs, pricer, curve_name, mark_ts)
        entry = (entry_marks or {}).get(key, 0.0)
        rows.append(dict(unit_key=key, mark_ts=mark_ts, mark_kind="EOD", npv_usd=npv,
                         pnl_since_entry_usd=npv - entry, curve_name=curve_name,
                         code_vintage=vintage.code_vintage()))
    return rows
