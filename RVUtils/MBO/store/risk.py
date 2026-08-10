"""The risk partition: what a basis point is worth, per instrument per session.

This exists as its own small table rather than as a column inside the event
store, and the reason is a failure this repo has already had.  A transient curve
error once produced an all-null DV01 set that was published as a successful run,
and nothing downstream could tell the difference between "no risk" and "risk not
computed".  Two consequences are designed in here:

* **A failed curve build writes null with ``source='FAILED'``, never a zero.**
  Zero is a number and it propagates; null with a reason does not.
* **The read path raises on a missing or null DV01.**  ``dv01_for`` refuses
  rather than returning NaN, so a Treasury panel asked for basis points fails
  loudly instead of producing a column of NaN that looks like a quiet session.

Keeping it separate also means a wrong DV01 costs one small file to rebuild
rather than a hundred gigabytes of replayed book, and that the event store stays
pure market data that never needs revisiting when a curve changes.

SR3 rows are synthesised at the intrinsic $25 per basis point so that every
consumer takes the same code path for every product.
"""
from __future__ import annotations

import datetime
import os
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from RVUtils.MBO.products import PRODUCTS, root_of, spec_for
from RVUtils.MBO.store.schema import RISK_SCHEMA, store_path, store_root

__all__ = [
    "Dv01Provider",
    "build_risk",
    "dv01_for",
    "dv01_map",
    "read_risk",
    "ustfutures_provider",
]

#: ``(product, symbol, date) -> dict`` with keys ``ctd``, ``conversion_factor``,
#: ``dv01_per_contract``, ``ctd_dv01``.  Raising is fine: the caller records the
#: failure rather than letting it stop a build.
Dv01Provider = Callable[[str, str, datetime.date], Dict[str, Optional[float]]]


def ustfutures_provider(product: str, symbol: str,
                        date: datetime.date) -> Dict[str, Optional[float]]:
    """DV01 from the repo's Treasury futures pricer.

    Imported lazily: it pulls curves, and the store must be buildable and
    testable on a machine with no market-data access.
    """
    from Query.USTFutures.USTFutureQuery import USTFutureQuery
    from Query.USTFutures.USTFutureValue import USTFutureValue
    from MDP.USTFutures.treasury_conversion_factors import resolve_delivery_contract

    q = USTFutureQuery(symbol=symbol, value=USTFutureValue.DV01)
    dv01 = float(q.evaluate(as_of=date))  # type: ignore[attr-defined]
    ctd = None
    cf = None
    try:
        ctd, _, _ = resolve_delivery_contract(symbol, date)
    except Exception:  # noqa: BLE001 - the CTD label is a nicety, DV01 is not
        pass
    return {"ctd": ctd, "conversion_factor": cf,
            "dv01_per_contract": dv01, "ctd_dv01": None}


def build_risk(root: str, product: str, date: datetime.date,
               symbols: Optional[Sequence[str]] = None,
               provider: Optional[Dv01Provider] = None) -> pd.DataFrame:
    """Build and write one session's risk rows.  Never raises on a pricer failure."""
    spec = spec_for(product)
    if symbols is None:
        symbols = _symbols_from_catalog(root, product, date)

    now = int(pd.Timestamp.utcnow().value)
    rows: List[dict] = []

    if spec.usd_per_bp_per_lot is not None:
        # A rate contract: the value of a basis point is a property of the
        # contract, not of a curve, so there is nothing to fail.
        for s in symbols:
            rows.append({
                "symbol": s, "ctd": None, "conversion_factor": None,
                "dv01_per_contract": float(spec.usd_per_bp_per_lot),
                "ctd_dv01": None, "source": "intrinsic", "ts_built": now,
            })
    else:
        fn = provider or ustfutures_provider
        for s in symbols:
            try:
                got = fn(product, s, date)
                dv01 = got.get("dv01_per_contract")
                ok = dv01 is not None and np.isfinite(float(dv01)) and float(dv01) != 0.0
                rows.append({
                    "symbol": s,
                    "ctd": got.get("ctd"),
                    "conversion_factor": got.get("conversion_factor"),
                    "dv01_per_contract": float(dv01) if ok else None,
                    "ctd_dv01": got.get("ctd_dv01"),
                    "source": fn.__name__ if ok else "FAILED",
                    "ts_built": now,
                })
            except BaseException:  # noqa: BLE001 - a failure must be recorded, not raised
                rows.append({
                    "symbol": s, "ctd": None, "conversion_factor": None,
                    "dv01_per_contract": None, "ctd_dv01": None,
                    "source": "FAILED", "ts_built": now,
                })

    df = pd.DataFrame(rows, columns=[f.name for f in RISK_SCHEMA])
    path = store_path(store_root(root), "risk", product, date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.part"
    pq.write_table(
        pa.Table.from_pandas(df, schema=RISK_SCHEMA, preserve_index=False),
        tmp, compression="zstd",
    )
    os.replace(tmp, path)
    return df


def _symbols_from_catalog(root: str, product: str,
                          date: datetime.date) -> List[str]:
    path = store_path(store_root(root), "catalog", product, date)
    if not os.path.exists(path):
        return []
    return list(pq.read_table(path, columns=["symbol"]).to_pandas()["symbol"])


def read_risk(root: str, product: str,
              dates: Iterable[datetime.date]) -> pd.DataFrame:
    """Risk rows for a product over some sessions, with a ``date`` column."""
    frames = []
    for d in dates:
        path = store_path(store_root(root), "risk", product, d)
        if not os.path.exists(path):
            continue
        df = pq.read_table(path).to_pandas()
        df["date"] = d
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=[f.name for f in RISK_SCHEMA] + ["date"])
    return pd.concat(frames, ignore_index=True)


def dv01_for(root: str, symbol: str, date: datetime.date) -> float:
    """Dollars per basis point for one instrument on one session.

    Raises on a missing row and on a null one.  Returning NaN would let a whole
    basis-point panel come back empty and look like a quiet session; that is the
    exact shape of the incident this partition is built to prevent.
    """
    product = root_of(symbol)
    if product is None:
        raise KeyError(f"cannot tell which product {symbol!r} belongs to")
    df = read_risk(root, product, [date])
    hit = df[df["symbol"] == symbol] if not df.empty else df
    if hit.empty:
        raise KeyError(
            f"no DV01 row for {symbol} on {date}: build the risk partition for "
            f"{product} first (RVUtils.MBO.store.risk.build_risk)"
        )
    v = hit.iloc[-1]["dv01_per_contract"]
    if v is None or not np.isfinite(float(v)):
        raise KeyError(
            f"no DV01 for {symbol} on {date}: the row exists but is null "
            f"(source={hit.iloc[-1]['source']!r}), which means the curve build "
            f"failed. Re-run build_risk rather than treating it as zero."
        )
    return float(v)


def dv01_map(root: str, symbols: Sequence[str],
             date: datetime.date) -> Dict[str, float]:
    """``symbol -> dv01`` for a panel request.  Raises on the first miss."""
    return {s: dv01_for(root, s, date) for s in symbols}
