"""Panel construction: strip slots, structure enumeration, CM labels, regimes.

Data-agnostic. The input everywhere is a **long** frame with one row per
(date, instrument) carrying an ordering column (the strip slot) and a value
column (the instrument's rate), plus whatever liquidity columns exist. Nothing
here knows what a SOFR future is.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "add_strip_slots", "enumerate_structures", "cm_label", "pivot_levels",
    "regime_tag", "structure_liquidity", "FLY_WEIGHTS",
]

#: weights on (front, belly, back) rates -- the desk/Query-layer convention
#: ``fly = 2*belly - front - back``. Same as RVUtils.FlyVsVol.FLY_WEIGHTS.
FLY_WEIGHTS: Tuple[float, float, float] = (-1.0, 2.0, -1.0)


def add_strip_slots(
    df: pd.DataFrame, *, date_col: str = "as_of", order_col: str = "imm_start",
    start_col: Optional[str] = "imm_start", slot_col: str = "slot",
    exclude_started: bool = True,
) -> pd.DataFrame:
    """Rank each date's instruments into strip slots 1, 2, 3, ...

    ``exclude_started`` drops instruments whose reference period has already
    begun (``start_col <= date``). For quarterly STIR futures that is what makes
    slot 1 the front contract that is **not yet accruing** -- the one a desk
    calls the front, and the one a curve's ``IMM_1xIMM_2`` resolves to. Keeping
    a partially-fixed contract in the strip would put a mechanically decaying
    leg into every front structure.
    """
    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col])
    if exclude_started and start_col is not None:
        out[start_col] = pd.to_datetime(out[start_col])
        out = out[out[start_col] > out[date_col]]
    out = out.sort_values([date_col, order_col])
    out[slot_col] = out.groupby(date_col)[order_col].rank(method="first").astype(int)
    return out.reset_index(drop=True)


def cm_label(slots: Sequence[int], *, compressed: bool = False) -> str:
    """Constant-maturity label for a structure on the given strip slots.

    ``compressed=False`` gives the repo's existing form ``SFR1/SFR2/SFR3``
    (see ``BT/signals/sfr_cal_spread_rv.py::cm_label``); ``True`` gives the
    desk shorthand ``SFR123``, which is unambiguous only while every slot is a
    single digit and is therefore rendered ``SFR-10-11-12`` beyond slot 9.
    """
    s = [int(x) for x in slots]
    if not compressed:
        return "/".join(f"SFR{i}" for i in s)
    if all(i < 10 for i in s):
        return "SFR" + "".join(str(i) for i in s)
    return "SFR-" + "-".join(str(i) for i in s)


#: pack colours by belly slot, matching RVUtils/ImpliedDistribution/_strip_utils
_PACKS = [(1, 4, "whites"), (5, 8, "reds"), (9, 12, "greens"), (13, 16, "blues")]


def pack_of(slot: int) -> str:
    for lo, hi, name in _PACKS:
        if lo <= slot <= hi:
            return name
    return "beyond"


def enumerate_structures(
    df: pd.DataFrame, *, spacing: int = 1, max_slot: int = 16,
    weights: Sequence[float] = FLY_WEIGHTS,
    date_col: str = "as_of", slot_col: str = "slot", value_col: str = "rate_pct",
    id_col: str = "code", scale: float = 100.0,
) -> pd.DataFrame:
    """Enumerate every equally-spaced N-leg structure on the strip, per date.

    Legs are the slots ``(i, i+spacing, i+2*spacing, ...)`` for as many weights
    as are supplied. The structure value is ``sum(w_j * value_j) * scale`` --
    with the default weights and ``scale=100`` that is
    ``(2*belly - front - back)`` in **bp** from rates in **percent**.

    Every structure is keyed on its **absolute** leg identifiers, so a key's
    series is one fixed set of contracts and no roll ever enters it. The
    constant-maturity slot is attached as a reporting tag (``cm_slot``,
    ``cm_label``, ``pack``) evaluated as of each date.

    Returns a long frame: ``as_of, key, <leg id/slot/value columns>,
    cm_slot, cm_label, cm_label_short, pack, value``.
    """
    n_legs = len(weights)
    if n_legs < 2:
        raise ValueError("need at least two legs")
    wide_v = df.pivot_table(index=date_col, columns=slot_col, values=value_col,
                            aggfunc="first")
    wide_id = df.pivot_table(index=date_col, columns=slot_col, values=id_col,
                             aggfunc="first")
    slots_avail = [c for c in wide_v.columns if c <= max_slot]
    frames = []
    for i in slots_avail:
        legs = [i + j * spacing for j in range(n_legs)]
        if legs[-1] > max_slot or any(l not in wide_v.columns for l in legs):
            continue
        val = sum(float(w) * wide_v[l] for w, l in zip(weights, legs)) * float(scale)
        ids = [wide_id[l] for l in legs]
        key = ids[0].astype(str)
        for extra in ids[1:]:
            key = key + "-" + extra.astype(str)
        belly = legs[n_legs // 2]
        blk = pd.DataFrame({
            date_col: wide_v.index, "key": key.to_numpy(), "value": val.to_numpy(),
            "cm_slot": belly, "cm_label": cm_label(legs),
            "cm_label_short": cm_label(legs, compressed=True),
            "pack": pack_of(belly), "front_slot": legs[0], "back_slot": legs[-1],
        })
        for j, l in enumerate(legs):
            blk[f"leg{j}_id"] = wide_id[l].to_numpy()
            blk[f"leg{j}_slot"] = l
            blk[f"leg{j}_value"] = wide_v[l].to_numpy()
        frames.append(blk)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["value", "key"])
    out = out[~out["key"].astype(str).str.contains("nan")]
    return out.sort_values([date_col, "cm_slot"]).reset_index(drop=True)


def structure_liquidity(
    struct: pd.DataFrame, contracts: pd.DataFrame, *, n_legs: int = 3,
    date_col: str = "as_of", id_col: str = "code",
    cols: Sequence[str] = ("volume", "open_interest"),
) -> pd.DataFrame:
    """Attach the **minimum** of each liquidity column across a structure's legs.

    The binding constraint on a package is its worst leg, so the minimum is the
    right summary: a fly whose back wing has no open interest is not tradeable
    however deep the belly is.
    """
    out = struct.copy()
    src = contracts[[date_col, id_col, *cols]].copy()
    src[date_col] = pd.to_datetime(src[date_col])
    for c in cols:
        parts = []
        for j in range(n_legs):
            m = src.rename(columns={id_col: f"leg{j}_id", c: f"_{c}{j}"})
            out = out.merge(m[[date_col, f"leg{j}_id", f"_{c}{j}"]],
                            on=[date_col, f"leg{j}_id"], how="left")
            parts.append(f"_{c}{j}")
        out[f"min_{c}"] = out[parts].min(axis=1)
        out = out.drop(columns=parts)
    return out


def pivot_levels(struct: pd.DataFrame, *, date_col: str = "as_of",
                 key_col: str = "key", value_col: str = "value") -> pd.DataFrame:
    """Long structure frame -> wide ``date x key`` level panel."""
    w = struct.pivot_table(index=date_col, columns=key_col, values=value_col,
                           aggfunc="first")
    w.index = pd.to_datetime(w.index)
    return w.sort_index()


#: US policy regimes, cut on FOMC decision dates. ZIRP covers the pandemic-era
#: floor; HIKING is liftoff to the last hike; PLATEAU is the hold; CUTTING
#: starts at the first cut. Fly levels and half-lives are not comparable across
#: these, which is the whole reason results are reported per regime.
DEFAULT_REGIMES: Tuple[Tuple[str, Optional[str], Optional[str]], ...] = (
    ("ZIRP", None, "2022-03-16"),
    ("HIKING", "2022-03-17", "2023-07-26"),
    ("PLATEAU", "2023-07-27", "2024-09-17"),
    ("CUTTING", "2024-09-18", None),
)


def regime_tag(dates: Iterable, regimes: Sequence[Tuple[str, Optional[str], Optional[str]]]
               = DEFAULT_REGIMES) -> pd.Series:
    """Label each date with its policy regime."""
    idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(list(dates))))
    out = pd.Series("OTHER", index=range(len(idx)), dtype=object)
    for name, lo, hi in regimes:
        m = np.ones(len(idx), dtype=bool)
        if lo is not None:
            m &= np.asarray(idx >= pd.Timestamp(lo))
        if hi is not None:
            m &= np.asarray(idx <= pd.Timestamp(hi))
        out[m] = name
    out.index = idx
    out.name = "regime"
    return out
