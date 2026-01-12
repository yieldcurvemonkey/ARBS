import datetime
import numpy as np
import pandas as pd


def merge_package_legs_to_one_row(
    df: pd.DataFrame,
    *,
    package_id_col: str = "package_id",
    package_type_col: str = "package_type",
    legs_col: str = "package_legs",
    delim: str = " / ",
    sort_legs_by: tuple[str, ...] = ("tenor_years", "expiration_date", "trade_id"),
    strip_spot_prefix_in_trade_label: bool = True,
) -> pd.DataFrame:
    """
    Collapse multi-leg packages (same package_id + package_type) into a single row.

    Rules:
      - columns that are identical across legs -> keep scalar (first)
      - columns that vary across legs -> join leg values with `delim` in leg order
      - trade_label: optionally strip leading "spot " per leg before joining
    """
    if df.empty:
        return df.copy()

    out = df.copy()

    def _eq(a, b) -> bool:
        # robust equality that won't produce ambiguous array truth values
        if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
            try:
                return np.array_equal(a, b, equal_nan=True)
            except TypeError:
                # older numpy: equal_nan not supported for some dtypes
                return np.array_equal(a, b)
        return a == b

    def _is_na_scalar(x) -> bool:
        # NA check that is guaranteed to return a bool (not a bool-array)
        if x is None:
            return True
        if isinstance(x, float) and np.isnan(x):
            return True
        if isinstance(x, (np.floating,)):
            return bool(np.isnan(x))
        if isinstance(x, pd.Timestamp):
            return pd.isna(x)
        if isinstance(x, (datetime.date, datetime.datetime)):
            return False
        # avoid pd.isna on array-likes (returns array)
        if isinstance(x, (list, tuple, dict, set, np.ndarray)):
            return False
        try:
            return bool(pd.isna(x))
        except Exception:
            return False

    def _is_empty(x) -> bool:
        # unified "empty" predicate for scalars + containers + arrays
        if _is_na_scalar(x):
            return True
        if isinstance(x, str):
            return x == ""
        if isinstance(x, np.ndarray):
            return x.size == 0
        if isinstance(x, (list, tuple, dict, set)):
            return len(x) == 0
        return False

    def _fmt(x) -> str:
        if _is_empty(x):
            return ""
        if isinstance(x, pd.Timestamp):
            return x.isoformat()
        if isinstance(x, (datetime.date, datetime.datetime)):
            return x.isoformat()
        if isinstance(x, (float, np.floating)):
            return f"{float(x):g}"
        if isinstance(x, (int, np.integer)):
            return str(int(x))
        # if arrays slip through, stringify stably
        if isinstance(x, np.ndarray):
            return np.array2string(x, separator=",", threshold=20)
        return str(x)

    def _all_equal(vals) -> bool:
        if not vals:
            return True
        first = vals[0]
        for v in vals[1:]:
            if not _eq(v, first):
                return False
        return True

    def _merge_series(s: pd.Series, *, colname: str) -> object:
        vals = list(s.tolist())

        # special: keep legs list as list (not delimited string)
        if colname == legs_col:
            for v in vals:
                if isinstance(v, list) and len(v) > 0:
                    return v
            return vals[0]

        # if everything is NA/empty -> NA
        non_empty = [v for v in vals if not _is_empty(v)]
        if not non_empty:
            return np.nan

        # if all non-empty values identical -> keep scalar
        if _all_equal(non_empty) and len(set(map(_fmt, non_empty))) == 1:
            return non_empty[0]

        # otherwise join (preserve order)
        if colname == "trade_label" and strip_spot_prefix_in_trade_label:
            joined = []
            for v in vals:
                sv = _fmt(v)
                if sv.lower().startswith("spot "):
                    sv = sv[5:]
                if sv != "":
                    joined.append(sv)
            return delim.join(joined) if joined else np.nan

        joined = [_fmt(v) for v in vals]
        joined = [x for x in joined if x != ""]
        return delim.join(joined) if joined else np.nan

    pack_mask = out[package_id_col].notna() & out[package_type_col].notna() & (out[package_type_col] != "OUTRIGHT")

    passthrough = out.loc[~pack_mask].copy()

    merged_rows = []
    for (_, _), g in out.loc[pack_mask].groupby([package_type_col, package_id_col], sort=False):
        g2 = g.copy()

        for c in sort_legs_by:
            if c not in g2.columns:
                g2[c] = np.nan
        g2 = g2.sort_values(list(sort_legs_by), kind="mergesort")

        merged = {}
        for col in g2.columns:
            merged[col] = _merge_series(g2[col], colname=col)
        merged_rows.append(merged)

    merged_df = pd.DataFrame(merged_rows) if merged_rows else out.iloc[0:0].copy()
    result = pd.concat([passthrough, merged_df], ignore_index=True)
    return result
