import re
import hashlib
import ujson as json

_FILENAME_RX = re.compile(r"[^A-Za-z0-9_.-]")  # keep only safe chars


def _slug(text: str) -> str:
    """ASCII-only slug suitable for filenames."""
    return _FILENAME_RX.sub("_", text)


def make_hashable(x):
    if isinstance(x, (tuple, list)):
        return tuple(make_hashable(e) for e in x)
    elif isinstance(x, dict):
        return tuple(sorted((make_hashable(k), make_hashable(v)) for k, v in x.items()))
    elif isinstance(x, set):
        return tuple(sorted(make_hashable(e) for e in x))
    elif callable(x):
        return _slug(f"{x.__module__}.{x.__qualname__}")
    elif isinstance(x, str):
        return _slug(x)
    else:
        return x


def to_filename_key(cfg: dict, max_len: int = 120) -> str:
    clean = make_hashable(cfg)
    json_txt = json.dumps(clean, separators=(",", ":"), sort_keys=True)
    slug = _slug(json_txt)

    if len(slug) <= max_len:
        return slug

    digest = hashlib.sha1(slug.encode()).hexdigest()[:8]
    return f"{slug[: max_len - 9]}_{digest}"


import numpy as np
from scipy.interpolate import interp1d
from typing import List, Tuple, Dict, Any


def _encode_interp1d(f: interp1d) -> Tuple[List[float], List[float], Dict[str, Any]]:
    # helper to cope with API drift
    def _get(obj, public: str, private: str, default=None):
        return getattr(obj, public, getattr(obj, private, default))

    kwargs = dict(
        kind=_get(f, "kind", "_kind", "linear"),
        bounds_error=_get(f, "bounds_error", "_bounds_error", False),
        fill_value=f.fill_value,
        assume_sorted=_get(f, "assume_sorted", "_assume_sorted", False),
    )
    return (f.x.tolist(), f.y.tolist(), kwargs)


def _decode_interp1d(state: Tuple[List[float], List[float], Dict[str, Any]]) -> interp1d:
    x, y, kw = state
    kind = kw.get("kind", "linear")
    if kind == "spline":
        kind = "cubic"
    kw["kind"] = kind
    return interp1d(np.asarray(x), np.asarray(y), **kw)
