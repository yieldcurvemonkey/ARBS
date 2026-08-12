"""A minimal stand-in for ``pandas.Panel``, which was removed in pandas 1.0.

The optimizer this supports was written against pandas 0.x and represents a *time series of
matrices* — a covariance per date, a constraint-weight matrix per date. That is genuinely
three-dimensional and there is no natural DataFrame for it, so rather than reshape the maths this
provides the small slice of the old Panel API the optimizer actually uses:

``items`` (the time axis) → ``DataFrame(major_axis × minor_axis)``.

Only what is used is implemented. Anything else raising loudly is deliberate: a silent partial
Panel emulation would be worse than none.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd

__all__ = ["Panel3D", "as_panel3d"]


class _PanelLoc:
    def __init__(self, panel: "Panel3D"):
        self._p = panel

    def __getitem__(self, key):
        if isinstance(key, tuple):
            key = key[0]
        return self._p.frame(key)


class Panel3D:
    """``{item: DataFrame}`` with the handful of Panel behaviours the optimizer needs."""

    def __init__(
        self,
        data: Any = None,
        items: Optional[Iterable] = None,
        major_axis: Optional[Iterable] = None,
        minor_axis: Optional[Iterable] = None,
        dtype: Any = float,
    ):
        if data is None:
            if items is None:
                raise ValueError("Panel3D needs data or items")
            major = list(major_axis) if major_axis is not None else []
            minor = list(minor_axis) if minor_axis is not None else []
            self._d: Dict[Any, Optional[pd.DataFrame]] = {
                k: pd.DataFrame(index=major, columns=minor, dtype=dtype) for k in items
            }
            self._items = pd.Index(list(items))
        elif isinstance(data, Panel3D):
            self._d = {k: (v.copy() if v is not None else None) for k, v in data._d.items()}
            self._items = data._items.copy()
        elif isinstance(data, Mapping):
            self._d = {k: (pd.DataFrame(v) if v is not None else None) for k, v in data.items()}
            self._items = pd.Index(list(data.keys()))
        elif isinstance(data, np.ndarray):
            if data.ndim != 3:
                raise ValueError(f"Panel3D from ndarray needs ndim 3, got {data.ndim}")
            items = list(items) if items is not None else list(range(data.shape[0]))
            major = list(major_axis) if major_axis is not None else list(range(data.shape[1]))
            minor = list(minor_axis) if minor_axis is not None else list(range(data.shape[2]))
            self._d = {k: pd.DataFrame(data[i], index=major, columns=minor) for i, k in enumerate(items)}
            self._items = pd.Index(items)
        else:
            raise TypeError(f"cannot build a Panel3D from {type(data).__name__}")

    # -- axes ---------------------------------------------------------------
    @property
    def items(self) -> pd.Index:
        return self._items

    @property
    def major_axis(self) -> pd.Index:
        f = self._first_frame()
        return f.index if f is not None else pd.Index([])

    @property
    def minor_axis(self) -> pd.Index:
        f = self._first_frame()
        return f.columns if f is not None else pd.Index([])

    @property
    def shape(self):
        f = self._first_frame()
        return (len(self._items), 0 if f is None else f.shape[0], 0 if f is None else f.shape[1])

    def _first_frame(self) -> Optional[pd.DataFrame]:
        for k in self._items:
            v = self._d.get(k)
            if v is not None:
                return v
        return None

    # -- access -------------------------------------------------------------
    @property
    def loc(self) -> _PanelLoc:
        return _PanelLoc(self)

    @property
    def ix(self) -> _PanelLoc:  # the original called .ix; keep it working
        return _PanelLoc(self)

    def frame(self, key) -> pd.DataFrame:
        if key not in self._d:
            raise KeyError(f"{key!r} not in Panel3D items")
        v = self._d[key]
        if v is None:
            raise KeyError(f"{key!r} is empty in this Panel3D (reindexed but never filled)")
        return v

    def __getitem__(self, key) -> pd.DataFrame:
        return self.frame(key)

    def __setitem__(self, key, value) -> None:
        self._d[key] = None if value is None else pd.DataFrame(value)
        if key not in self._items:
            self._items = pd.Index(list(self._items) + [key])

    def __contains__(self, key) -> bool:
        return key in self._d and self._d[key] is not None

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def iteritems(self):
        for k in self._items:
            yield k, self._d[k]

    def items_pairs(self):
        return self.iteritems()

    # -- reshaping ----------------------------------------------------------
    def copy(self) -> "Panel3D":
        return Panel3D(self)

    def reindex(self, index: Iterable) -> "Panel3D":
        idx = pd.Index(list(index))
        out = Panel3D({k: self._d.get(k) for k in idx})
        out._items = idx
        return out

    def fillna(self, method: str = "ffill", axis: int = 0) -> "Panel3D":
        """Forward-fill *whole missing items* along the time axis.

        The optimizer calls ``reindex(index).fillna(method='ffill', axis=0)`` to carry a constraint
        matrix specified on a sparse set of dates across every date in the run.
        """
        if method != "ffill" or axis != 0:
            raise NotImplementedError("Panel3D.fillna supports only method='ffill', axis=0")
        out = Panel3D(self)
        last: Optional[pd.DataFrame] = None
        for k in out._items:
            v = out._d.get(k)
            if v is None:
                if last is not None:
                    out._d[k] = last.copy()
            else:
                last = v
        return out

    def dropna(self, how: str = "all") -> "Panel3D":
        """Drop items with no usable matrix.

        ``how='all'`` drops an item only when its whole frame is missing (or the item was never
        filled); ``how='any'`` drops an item with any NaN in it. The optimizer uses this to find
        the dates on which it can actually solve, so an over-eager rule silently shortens the run.
        """
        if how not in {"all", "any"}:
            raise NotImplementedError("Panel3D.dropna supports how in {'all','any'}")
        keep = []
        for k in self._items:
            v = self._d.get(k)
            if v is None or v.empty:
                continue
            isna = v.isna()
            if how == "all" and bool(isna.all().all()):
                continue
            if how == "any" and bool(isna.any().any()):
                continue
            keep.append(k)
        out = Panel3D({k: self._d[k] for k in keep})
        out._items = pd.Index(keep)
        return out

    def to_frame(self) -> pd.DataFrame:
        """Long form: a MultiIndex of (item, major) against the minor axis."""
        frames = {k: v for k, v in self._d.items() if v is not None}
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=0)

    def to_dict(self) -> Dict[Any, pd.DataFrame]:
        return {k: v for k, v in self._d.items() if v is not None}

    def __repr__(self) -> str:
        s = self.shape
        return f"<Panel3D items={s[0]} major={s[1]} minor={s[2]}>"


def as_panel3d(obj: Any) -> Panel3D:
    """Accept a Panel3D, a ``{date: DataFrame}`` mapping, or a 3-D ndarray."""
    if isinstance(obj, Panel3D):
        return obj
    return Panel3D(obj)
