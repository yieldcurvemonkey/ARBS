import datetime
from enum import Enum
from typing import Union

DateLike = Union[datetime.date, datetime.datetime]


def _to_utc_naive(dt: DateLike) -> datetime.datetime:
    if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
        dt = datetime.datetime(dt.year, dt.month, dt.day)
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt  # naive UTC


def _dt_to_epoch_ns(dt: DateLike) -> int:
    dtu = _to_utc_naive(dt)
    return int(dtu.timestamp() * 1_000_000_000)


def _canonicalize_value(v):
    if isinstance(v, (datetime.date, datetime.datetime)):
        return _to_utc_naive(v).isoformat()
    if isinstance(v, Enum):  # IRSwapValue is an Enum
        return v.name
    if isinstance(v, (list, tuple)):
        return [_canonicalize_value(x) for x in v]
    if isinstance(v, dict):
        # sort keys to ensure determinism
        return {k: _canonicalize_value(v[k]) for k in sorted(v.keys())}
    return v  # numbers/strings/None
