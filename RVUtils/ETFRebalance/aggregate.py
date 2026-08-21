"""The AGGREGATE long-end ladder: many ETFs, one bucket measure, one z-score.

What this module is for
-----------------------
The single-fund study asked "is TLT underweight this 3-month maturity bucket, and does
the bucket therefore richen". It is dead, on measurement (``RESULTS.md``). The follow-up
question the user asked is whether the answer changes when the ladder is built from
**every** ETF holding cash Treasuries at the long end rather than from one, on the
hypothesis that the aggregate footprint is bigger and the aggregate view is less noisy.

That question cannot be answered by adding active weights together, and the reason is the
first thing this module has to solve.

The different-denominator trap
------------------------------
An "active weight" is a share of a book, and the three long-end coupon funds do not have
the same book:

===== ============================================ ==========================
fund  index                                        inclusion band (years)
===== ============================================ ==========================
TLT   ICE US Treasury 20+ Year                     [20, inf)
SPTL  Bloomberg Long U.S. Treasury                 [10, inf)
VGLT  Bloomberg U.S. Long Treasury Bond            [10, inf)
===== ============================================ ==========================

Measured on the latest observation of each: 40 of SPTL's 97 positions and 39 of VGLT's 97
sit at or above 20 years -- i.e. **a little over half of each fund's market value is in
the 20y+ sector and the rest is not**. TLT's active weight in the 2045 bond is a deviation
from a 40-bond board; SPTL's is a deviation from a ~100-bond board. ``w_f - w_i`` for the
same CUSIP therefore means two different things, they are not on the same scale, and
adding them produces a number with no denominator at all. Doing it anyway is the single
most plausible way to get a confident wrong answer here.

The guard is :func:`assert_common_benchmark`, which compares the benchmark *vectors* --
the only thing that can see the problem, since the shapes, dtypes and ranges are all
identical either way. :func:`active_ladder` builds one benchmark and then asserts that
invariant on the funds it just measured, so the assertion can only fire if a future edit
reintroduces per-fund benchmarks; callers who assemble their own per-fund frames (the
natural way, one ``holdings_panel.with_active_weight`` call per fund) get the refusal
directly. A mutation test removes the check and requires the test to go red.

The two constructions that ARE denominator-consistent
------------------------------------------------------
**(a) OWNERSHIP -- the footprint.** Per bond, the par held by every qualifying fund,
divided by the bond's publicly held (ex-SOMA) amount outstanding. That ratio has the same
denominator for every fund by construction, so summing across funds is addition of
dollars, not of shares-of-different-things. Aggregated into a bucket it is
``sum(par held) / sum(free float)`` over the bonds in the bucket -- again dollars over
dollars. This is what :func:`ownership_ladder` builds, and it is the construction the
task names first.

**(b) ACTIVE WEIGHT AGAINST ONE COMMON BENCHMARK.** Restrict every fund to the SAME 20y+
slice, renormalise each fund's weights inside that slice, and measure each against the
same free-float-weighted 20y+ benchmark. Now every ``w_f`` and the single ``w_i`` are
shares of one board and the difference is comparable across funds.

What (b) throws away, stated rather than hidden
------------------------------------------------
Renormalising inside the 20y+ slice deletes each fund's view on *how much* long end to
hold at all. A fund that is uniformly light in the whole 20y+ sector against its own
10y+ index renormalises to neutral. That quantity is real and it is not measurable on a
common board, because TLT's board has no 10-20y half to be light in. So it is *reported*
instead of dropped: :func:`active_ladder` returns an ``offslice`` frame giving, per fund
per date, the share of its book outside the common slice and its in-slice DV01, and the
notebook prints it. The prior ladder work in this repo found exactly this kind of residual
running to 7.7% of a fund; here it is closer to 45%, which is far too large to leave
implicit.

Units: PAR and DV01, never the document's market value
-------------------------------------------------------
iShares publishes a **dirty** market value and N-PORT publishes a **clean** one (measured:
the iShares ``Market Value / Par Value`` sits +0.148 to +0.544 price points above its own
quoted clean price, while ``100 * valUSD / balance`` from N-PORT ties out to the clean
quote at the fourth decimal). Accrued interest is ``coupon x days-since-coupon``, so it
differs bond by bond and does **not** cancel cross-sectionally: mixing the two conventions
tilts every aggregate weight toward high-coupon bonds by construction. Every weight in
this module is therefore built from the document's **par** and the ARBS panel's own price
and duration, so the two sources are on one convention and the tilt cannot arise.

Knowability: ``available_from``, not ``date``
----------------------------------------------
SPTL and VGLT have no backfillable issuer endpoint. Their only history is SEC Form
N-PORT, which is **quarterly** and is published **53-62 days after** the date it
describes. A panel keyed on the N-PORT as-of date hands those two funds a two-month
lookahead -- larger than any edge this study is chasing by two orders of magnitude.

So every observation carries ``available_from``, and :func:`as_of_panel` gives each panel
date the most recent observation *published on or before it*, per fund. TLT and GOVT
update daily; SPTL and VGLT are a staircase that steps eight times a year (the two
issuers never share a reporting date -- SPTL files calendar quarter-ends, VGLT files
Feb/May/Aug/Nov). ``exec_lag`` in the engine then applies on top, so the daily funds are
still traded no earlier than the business day after their file.

There is a test that mutates the join to key on ``date`` and requires it to fail.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from MDP.ETFHoldings import store as holdings_store

# ---------------------------------------------------------------- the fund sets

#: The common slice every construction is measured on. The user's cut is the long end;
#: 20y+ is where TLT's board and the Bloomberg long funds' boards overlap, and it is the
#: band the single-fund result was produced on, so the comparison is like for like.
COMMON_BAND: Tuple[float, float] = (20.0, 31.0)


@dataclasses.dataclass(frozen=True)
class FundSet:
    """Which funds contribute, and by which route their history is obtainable.

    Split by ROUTE rather than by issuer because the two routes have completely
    different knowability: ``daily`` funds serve a dated file per business day, and
    ``nport`` funds are quarterly with a two-month publication lag. A construction that
    forgets which is which is a construction with a lookahead in it.
    """

    name: str
    daily: Tuple[str, ...] = ()
    nport: Tuple[str, ...] = ()
    note: str = ""

    @property
    def tickers(self) -> Tuple[str, ...]:
        return tuple(self.daily) + tuple(self.nport)

    def __len__(self) -> int:  # pragma: no cover - convenience
        return len(self.tickers)


#: The named fund sets the study compares. ``tlt_only`` is the control and MUST be run
#: through the identical pipeline: the headline is not the aggregate's Sharpe, it is the
#: difference between these two on the same dates with the same costs.
FUND_SETS: Dict[str, FundSet] = {
    "tlt_only": FundSet(
        "tlt_only", daily=("TLT",),
        note="the single-fund control -- same code path, same dates, same costs"),
    "coupon_long": FundSet(
        "coupon_long", daily=("TLT",), nport=("SPTL", "VGLT"),
        note="the user's cut: every >=$1bn coupon-UST ETF whose index reaches 20y+"),
    "coupon_long_govt": FundSet(
        "coupon_long_govt", daily=("TLT", "GOVT"), nport=("SPTL", "VGLT"),
        note="+ GOVT's 20y+ sleeve. GOVT is a 1y+ fund, so its long end is a sleeve of a "
             "much larger book; labelled separately because widening the set silently "
             "would make the old and the new number different experiments"),
    "daily_only": FundSet(
        "daily_only", daily=("TLT", "GOVT"),
        note="the two funds with a real DAILY history -- the aggregate you could have "
             "traded at daily frequency over the whole sample"),
}


def nport_dir() -> pathlib.Path:
    return holdings_store.cache_root() / "_nport"


# ---------------------------------------------------------------- loading

#: Columns every loader must produce, whatever the route. ``obs_date`` is the date the
#: holdings describe (already shifted to the daily-file convention for N-PORT);
#: ``available_from`` is the first date anybody outside the fund could see them.
OBS_COLS = ("ticker", "obs_date", "available_from", "cusip", "par", "source")


def load_daily(tickers: Sequence[str], *, start=None, end=None) -> pd.DataFrame:
    """Dated daily issuer files from the holdings store, Treasuries only.

    ``available_from`` is the file's own as-of date. The file is actually published
    overnight, so nothing in it is knowable at that day's close -- that one business day
    is charged by the engine's ``exec_lag`` (default 1), exactly as in the single-fund
    study, rather than being double-charged here.
    """
    if not tickers:
        return pd.DataFrame(columns=list(OBS_COLS))
    raw = holdings_store.load(list(tickers), start=start, end=end)
    if raw.empty:
        return pd.DataFrame(columns=list(OBS_COLS))
    keep = raw["Asset Class"].astype(str).str.strip().eq("Fixed Income")
    d = raw[keep]
    out = pd.DataFrame({
        "ticker": d["ticker"].astype(str),
        "obs_date": pd.to_datetime(d["date"]),
        "cusip": d["CUSIP"].astype(str).str.strip(),
        "par": pd.to_numeric(d["Par Value"], errors="coerce"),
    })
    out["available_from"] = out["obs_date"]
    out["source"] = "ishares_daily"
    out = out.dropna(subset=["par"])
    return (out.groupby(["ticker", "obs_date", "available_from", "cusip", "source"],
                        as_index=False)["par"].sum())


def load_nport(tickers: Sequence[str], *, start=None, end=None,
               directory: Optional[pathlib.Path] = None) -> pd.DataFrame:
    """Quarterly SEC N-PORT books, keyed on ``book_date`` and gated by ``available_from``.

    ``book_date`` -- not the regulatory ``date`` -- because an N-PORT report stamped D
    carries the par amounts of the daily file stamped the previous business day (measured
    bit-exactly on all 27 TLT quarters, where both sources exist). D is a month end, month
    end is the index rebalance, so the rows that differ between the two datings are
    precisely the bonds being rebalanced. Joining on the regulatory date misallocates
    1.1-3.8% of the book onto exactly the names this study trades.
    """
    if not tickers:
        return pd.DataFrame(columns=list(OBS_COLS))
    root = pathlib.Path(directory) if directory is not None else nport_dir()
    frames = []
    for t in tickers:
        p = root / f"{t.upper()}_nport.parquet"
        if not p.exists():
            raise FileNotFoundError(
                f"{t}: no N-PORT parquet at {p}. SPTL/VGLT have no backfillable issuer "
                f"endpoint, so N-PORT is their ONLY history -- run "
                f"`python -m MDP.ETFHoldings.nport_backfill` before asking for them."
            )
        d = pd.read_parquet(p)
        need = {"book_date", "available_from", "CUSIP", "Par Value", "Asset Class"}
        missing = need - set(d.columns)
        if missing:
            raise KeyError(f"{t}: N-PORT parquet is missing {sorted(missing)}")
        d = d[d["Asset Class"].astype(str).str.strip().eq("Fixed Income")]
        f = pd.DataFrame({
            "ticker": t.upper(),
            "obs_date": pd.to_datetime(d["book_date"]),
            "available_from": pd.to_datetime(d["available_from"]),
            "cusip": d["CUSIP"].astype(str).str.strip(),
            "par": pd.to_numeric(d["Par Value"], errors="coerce"),
        })
        f["source"] = "nport"
        frames.append(f.dropna(subset=["par", "available_from"]))
    out = pd.concat(frames, ignore_index=True)
    if start is not None:
        out = out[out["obs_date"] >= pd.Timestamp(start)]
    if end is not None:
        out = out[out["obs_date"] <= pd.Timestamp(end)]
    return (out.groupby(["ticker", "obs_date", "available_from", "cusip", "source"],
                        as_index=False)["par"].sum())


def load_observations(fs: FundSet, *, start=None, end=None,
                      nport_directory: Optional[pathlib.Path] = None) -> pd.DataFrame:
    """Every fund in the set, on one schema, with its own knowability date attached."""
    parts = [load_daily(fs.daily, start=start, end=end)]
    if fs.nport:
        parts.append(load_nport(fs.nport, start=None, end=end, directory=nport_directory))
    obs = pd.concat([p for p in parts if len(p)], ignore_index=True) \
        if any(len(p) for p in parts) else pd.DataFrame(columns=list(OBS_COLS))
    return obs.sort_values(["ticker", "obs_date", "cusip"]).reset_index(drop=True)


# ---------------------------------------------------------------- the as-of join


def as_of_panel(obs: pd.DataFrame, dates: Sequence[pd.Timestamp]) -> pd.DataFrame:
    """Per (panel date, fund): the freshest book PUBLISHED ON OR BEFORE that date.

    This is the function the whole no-lookahead claim rests on. It selects on
    ``available_from``, never on ``obs_date``, so a quarterly N-PORT book dated
    2020-02-28 does not enter the panel until it is filed at the end of April.

    Returns one row per (date, ticker, cusip) with the chosen ``obs_date`` and
    ``stale_days`` -- how old the book being used is. A staleness column is not decoration:
    for SPTL and VGLT it runs to 150 days and it is the honest measure of how much of the
    "aggregate" is a two-quarter-old photograph.
    """
    d = pd.DatetimeIndex(sorted(pd.DatetimeIndex(dates).unique()))
    if obs.empty or len(d) == 0:
        return pd.DataFrame(columns=["date", "ticker", "cusip", "par", "obs_date",
                                     "stale_days", "source"])

    #: Normalise the time resolution before any merge. The daily store hands back
    #: ``datetime64[ns]`` and the N-PORT parquets ``datetime64[ms]``; ``merge_asof``
    #: refuses to join across the two, and a silent ``astype`` further downstream would
    #: be the kind of coercion that quietly rounds a boundary date.
    obs = obs.copy()
    for c in ("obs_date", "available_from"):
        obs[c] = pd.to_datetime(obs[c]).astype("datetime64[ns]")
    d = d.astype("datetime64[ns]")

    out = []
    for tkr, g in obs.groupby("ticker", sort=True):
        # One row per observation: which book, and when it became public. An amended
        # filing can share a book_date, so keep the LAST available_from per obs_date.
        heads = (g.groupby("obs_date", as_index=False)["available_from"].max()
                 .sort_values("available_from"))
        # merge_asof: for each panel date, the latest available_from <= date.
        pick = pd.merge_asof(
            pd.DataFrame({"date": d}),
            heads.rename(columns={"available_from": "avail"}),
            left_on="date", right_on="avail", direction="backward",
        ).dropna(subset=["obs_date"])
        if pick.empty:
            continue
        pick["stale_days"] = (pick["date"] - pick["obs_date"]).dt.days
        sub = g.merge(pick[["date", "obs_date", "stale_days"]], on="obs_date", how="inner")
        out.append(sub[["date", "ticker", "cusip", "par", "obs_date", "stale_days", "source"]])

    if not out:
        return pd.DataFrame(columns=["date", "ticker", "cusip", "par", "obs_date",
                                     "stale_days", "source"])
    return pd.concat(out, ignore_index=True).sort_values(["date", "ticker", "cusip"]) \
        .reset_index(drop=True)


# ---------------------------------------------------------------- buckets


class DifferentDenominators(ValueError):
    """Raised when active weights measured against DIFFERENT benchmarks are combined."""


def assert_common_benchmark(per_fund: Mapping[str, pd.DataFrame], *,
                            w_col: str = "w_i", tol: float = 1e-9) -> None:
    """Refuse to combine per-fund active weights unless they share ONE index weight vector.

    This is the different-denominator trap made into an exception. The natural way to
    build a "multi-fund active weight" is to call ``holdings_panel.with_active_weight``
    once per fund and add the results. Each of those calls uses the fund's OWN spec, so
    TLT's ``w_i`` is a share of a 40-bond 20y+ board while SPTL's is a share of a
    ~100-bond 10y+ board. The two columns are both called ``w_i``, both live in [0, 1],
    both sum to 1, and adding the active weights built from them produces a number with no
    denominator -- a plausible-looking quantity that means nothing.

    Nothing about the shapes or the dtypes catches that. Only comparing the benchmark
    vectors themselves does, so that is what this checks: on every date the funds share,
    every fund's ``w_i`` for every CUSIP must agree to ``tol``.
    """
    names = list(per_fund)
    if len(names) < 2:
        return
    ref_name = names[0]
    ref = per_fund[ref_name]
    if w_col not in ref.columns:
        raise KeyError(f"{ref_name}: no {w_col!r} column to compare benchmarks on")
    ref_idx = ref.set_index(["date", "cusip"])[w_col]
    for nm in names[1:]:
        other = per_fund[nm]
        if w_col not in other.columns:
            raise KeyError(f"{nm}: no {w_col!r} column to compare benchmarks on")
        oth_idx = other.set_index(["date", "cusip"])[w_col]
        common = ref_idx.index.intersection(oth_idx.index)
        if len(common) == 0:
            continue
        diff = (ref_idx.loc[common] - oth_idx.loc[common]).abs()
        worst = float(diff.max())
        if worst > tol:
            bad = diff.idxmax()
            raise DifferentDenominators(
                f"{ref_name} and {nm} carry DIFFERENT benchmark weights: max |dw_i| = "
                f"{worst:.3e} > {tol:.1e} (worst at {bad}). Their active weights are "
                f"shares of different boards -- TLT is benchmarked to a 20y+ index and "
                f"SPTL/VGLT to a 10y+ one -- so adding them is not an aggregate, it is a "
                f"number with no denominator. Restrict every fund to one common slice and "
                f"re-derive w_i on that slice (aggregate.active_ladder does this), or use "
                f"the ownership construction, which is denominator-consistent already."
            )


def bucket_of(ttm: pd.Series, *, band_low: float, band_high: float,
              width_y: float) -> pd.Series:
    """Constant-maturity bucket, counted UP from the band's deletion boundary.

    Same rule as ``holdings_panel.bucket_index`` but stated on an explicit band rather
    than on one fund's spec, because the whole point here is that the funds have
    different bands and the bucket must belong to the SLICE, not to a fund.
    """
    k = np.floor((pd.to_numeric(ttm, errors="coerce") - band_low) / float(width_y))
    hi = np.floor((band_high - band_low) / float(width_y))
    return k.clip(lower=0, upper=hi)


def _rolling_z(frame: pd.DataFrame, value_col: str, *, key: str = "bucket",
               lookback: int = 250, min_periods: int = 120) -> pd.Series:
    """z of each bucket against its OWN trailing history, strictly backward-looking.

    ``shift(1)`` before the window, so the observation being scored is never inside the
    mean and standard deviation it is scored against. Without it a step change deflates
    its own z by contributing to the scale -- largest exactly where the signal claims to
    be strongest -- and for the N-PORT funds, whose contribution IS a step function, that
    would be systematic rather than incidental.
    """
    f = frame.sort_values([key, "date"])
    prior = f.groupby(key)[value_col].shift(1)
    mu = prior.groupby(f[key]).transform(
        lambda x: x.rolling(lookback, min_periods=min_periods).mean())
    sd = prior.groupby(f[key]).transform(
        lambda x: x.rolling(lookback, min_periods=min_periods).std())
    z = (f[value_col] - mu) / sd.replace(0.0, np.nan)
    return z.reindex(frame.index)


# ---------------------------------------------------------------- construction (a)


def ownership_ladder(
    asof: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    band: Tuple[float, float] = COMMON_BAND,
    width_y: float = 0.25,
    lookback: int = 250,
    min_periods: int = 120,
    float_col: str = "free_float",
) -> pd.DataFrame:
    """Construction (a): total ETF ownership of a bucket's publicly held float, and its z.

    Denominator-consistent by construction. Every fund's contribution is dollars of par;
    the denominator is dollars of float. Nothing here depends on any fund's index band,
    which is exactly why it can be aggregated across funds with different ones.

    Returns one row per (date, bucket): ``agg_par``, ``float_usd``, ``own`` (the ratio),
    ``own_z``, plus ``n_bonds`` and ``n_funds`` for auditing.
    """
    lo, hi = band
    u = universe[universe["ttm"].between(lo, hi, inclusive="left")].copy()
    if u.empty:
        raise ValueError(f"universe has no rows inside the common band {band}")
    u["bucket"] = bucket_of(u["ttm"], band_low=lo, band_high=hi, width_y=width_y)

    held = asof[asof["cusip"].isin(set(u["cusip"]))]
    per_bond = held.groupby(["date", "cusip"], as_index=False).agg(
        agg_par=("par", "sum"), n_funds=("ticker", "nunique"),
        stale_max=("stale_days", "max"))

    j = u[["date", "cusip", "bucket", "ttm", float_col, "outstanding_amt"]].merge(
        per_bond, on=["date", "cusip"], how="left")
    j["agg_par"] = j["agg_par"].fillna(0.0)
    j["n_funds"] = j["n_funds"].fillna(0.0)
    #: A bond whose float the panel does not carry must NOT be a zero denominator: it
    #: would make its bucket's ownership infinite or drop it entirely. Fall back to total
    #: outstanding, which is a real number that is merely the wrong one, and flag it.
    denom = pd.to_numeric(j[float_col], errors="coerce")
    j["float_fallback"] = ~np.isfinite(denom) | (denom <= 0)
    denom = denom.where(~j["float_fallback"], pd.to_numeric(j["outstanding_amt"], errors="coerce"))
    j["float_usd"] = denom

    g = j.groupby(["date", "bucket"], as_index=False).agg(
        agg_par=("agg_par", "sum"), float_usd=("float_usd", "sum"),
        n_bonds=("cusip", "nunique"), n_funds=("n_funds", "max"),
        stale_max=("stale_max", "max"), n_float_fallback=("float_fallback", "sum"),
        ttm_mid=("ttm", "median"),
    )
    g["own"] = g["agg_par"] / g["float_usd"].replace(0.0, np.nan)
    g["own_z"] = _rolling_z(g, "own", lookback=lookback, min_periods=min_periods)
    return g.sort_values(["date", "bucket"]).reset_index(drop=True)


# ---------------------------------------------------------------- construction (b)


def active_ladder(
    asof: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    band: Tuple[float, float] = COMMON_BAND,
    width_y: float = 0.25,
    lookback: int = 250,
    min_periods: int = 120,
    weight_basis: str = "dv01",
    combine: str = "book",
    float_col: str = "free_float",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Construction (b): every fund against ONE common 20y+ benchmark, then aggregated.

    Each fund's weights are renormalised inside the common slice, so ``w_f`` and ``w_i``
    are shares of the same board for every fund and the difference is comparable. That is
    the whole reason the slice exists -- see the module docstring on the
    different-denominator trap.

    ``combine``:
      ``book``   -- weight each fund's active vector by its own in-slice DV01, i.e. the
                    aggregate is DOLLARS of active position. A $46bn fund and a $10bn fund
                    do not have equal votes, because they do not have equal flows.
      ``equal``  -- one fund one vote. Kept because "the aggregate is less noisy" is a
                    claim about averaging views, and averaging views is the equal-weighted
                    version. Both are swept.

    Returns ``(ladder, offslice)``. The second frame is not optional output: renormalising
    inside the slice DELETES each fund's view on how much long end to hold at all, and
    that quantity is large here (SPTL and VGLT keep a little over half their book inside
    the slice). It is reported rather than dropped.
    """
    if combine not in ("book", "equal"):
        raise ValueError(f"combine must be 'book' or 'equal', got {combine!r}")
    if weight_basis not in ("dv01", "par", "mv"):
        raise ValueError(f"weight_basis must be 'dv01', 'par' or 'mv', got {weight_basis!r}")

    lo, hi = band
    u = universe[universe["ttm"].between(lo, hi, inclusive="left")].copy()
    if u.empty:
        raise ValueError(f"universe has no rows inside the common band {band}")
    u["bucket"] = bucket_of(u["ttm"], band_low=lo, band_high=hi, width_y=width_y)

    #: Risk/price per dollar of par, taken from the ARBS panel -- NEVER from the holdings
    #: document. iShares publishes a dirty market value and N-PORT a clean one, so a
    #: document-sourced weight would tilt the aggregate toward high-coupon bonds purely
    #: by accrued interest. See the module docstring.
    if weight_basis == "dv01":
        u["unit"] = pd.to_numeric(u["dv01_per_mm"], errors="coerce") / 1e6
    elif weight_basis == "mv":
        u["unit"] = pd.to_numeric(u["clean_price"], errors="coerce") / 100.0
    else:
        u["unit"] = 1.0

    flt = pd.to_numeric(u[float_col], errors="coerce")
    flt = flt.where(np.isfinite(flt) & (flt > 0),
                    pd.to_numeric(u["outstanding_amt"], errors="coerce"))
    u["idx_amt"] = flt * u["unit"]
    tot_idx = u.groupby("date")["idx_amt"].transform("sum")
    u["w_i"] = u["idx_amt"] / tot_idx.replace(0.0, np.nan)

    keys = u[["date", "cusip", "bucket", "unit", "w_i"]]

    # ---- per fund, inside the slice -------------------------------------------------
    inside = asof.merge(keys, on=["date", "cusip"], how="inner")
    inside["amt"] = inside["par"] * inside["unit"]
    tot_f = inside.groupby(["date", "ticker"])["amt"].transform("sum")
    inside["w_f"] = inside["amt"] / tot_f.replace(0.0, np.nan)
    inside["active"] = inside["w_f"] - inside["w_i"]

    #: The invariant the whole construction rests on, checked rather than assumed: every
    #: fund's active weight must be a deviation from the SAME benchmark vector. It holds
    #: here by construction (``w_i`` comes from ``keys``, built once), and that is exactly
    #: why it is cheap to assert -- an assertion that can only fire if a future edit
    #: reintroduces per-fund benchmarks, which is the failure this module exists to
    #: prevent.
    assert_common_benchmark(
        {t: g[["date", "cusip", "w_i"]] for t, g in inside.groupby("ticker")})

    # ---- what renormalising discarded ------------------------------------------------
    #: Per fund per date: how much of the book is OUTSIDE the common slice. Measured on
    #: par because that is the only quantity both sources publish on one convention, and
    #: on DV01 inside the slice because that is what the aggregate weights by.
    book_par = asof.groupby(["date", "ticker"], as_index=False)["par"].sum() \
        .rename(columns={"par": "book_par"})
    in_par = inside.groupby(["date", "ticker"], as_index=False).agg(
        inslice_par=("par", "sum"), inslice_amt=("amt", "sum"),
        n_inslice=("cusip", "nunique"), stale_days=("stale_days", "max"))
    offslice = book_par.merge(in_par, on=["date", "ticker"], how="left")
    for c in ("inslice_par", "inslice_amt", "n_inslice"):
        offslice[c] = offslice[c].fillna(0.0)
    offslice["inslice_share_par"] = offslice["inslice_par"] / offslice["book_par"].replace(0.0, np.nan)
    offslice["offslice_share_par"] = 1.0 - offslice["inslice_share_par"]

    # ---- aggregate -------------------------------------------------------------------
    if combine == "book":
        wt = offslice[["date", "ticker", "inslice_amt"]].rename(columns={"inslice_amt": "fw"})
    else:
        wt = offslice[["date", "ticker"]].assign(fw=1.0)
    tot_w = wt.groupby("date")["fw"].transform("sum")
    wt["fw"] = wt["fw"] / tot_w.replace(0.0, np.nan)

    #: The aggregate active weight of a bond is
    #:
    #:     sum_f  fw_f * (w_f,f(bond) - w_i(bond))   =   (sum_f fw_f * w_f,f) - w_i
    #:
    #: because the fund weights ``fw`` sum to one on every date. Writing it in that second
    #: form is what makes the not-held case correct WITHOUT a special branch: a fund that
    #: does not hold the bond contributes ``fw_f * 0`` to the first term, so a bond NO
    #: fund holds lands at exactly ``-w_i`` -- the most underweight name on the board, and
    #: the observation a naive inner join would delete precisely because it is empty.
    a = inside.merge(wt, on=["date", "ticker"], how="left")
    a["held_w"] = a["w_f"] * a["fw"]
    per_bond = a.groupby(["date", "cusip"], as_index=False).agg(
        held_w=("held_w", "sum"), n_funds=("ticker", "nunique"))

    j = keys.merge(per_bond, on=["date", "cusip"], how="left")
    j["held_w"] = j["held_w"].fillna(0.0)
    j["n_funds"] = j["n_funds"].fillna(0.0)
    j["active_agg"] = j["held_w"] - j["w_i"]

    g = j.groupby(["date", "bucket"], as_index=False).agg(
        active_agg=("active_agg", "sum"), w_i=("w_i", "sum"),
        n_bonds=("cusip", "nunique"), n_funds=("n_funds", "max"))
    g["active_rel"] = g["active_agg"] / g["w_i"].replace(0.0, np.nan)
    g["active_z"] = _rolling_z(g, "active_agg", lookback=lookback, min_periods=min_periods)
    g["active_rel_z"] = _rolling_z(g, "active_rel", lookback=lookback, min_periods=min_periods)
    return (g.sort_values(["date", "bucket"]).reset_index(drop=True),
            offslice.sort_values(["date", "ticker"]).reset_index(drop=True))


# ---------------------------------------------------------------- attaching


def attach(universe: pd.DataFrame, ladder: pd.DataFrame, *, column: str,
           out_column: str, band: Tuple[float, float] = COMMON_BAND,
           width_y: float = 0.25) -> pd.DataFrame:
    """Broadcast one bucket-level column back onto every bond in that bucket.

    Every CUSIP in a bucket receives the bucket's score, so the selection rule then picks
    between them on something other than a difference that is not there.

    MEASURED CAVEAT, stated at the point of use: in the 20y+ sector a 0.25-year bucket
    holds a **median of one bond** (mean 1.01, max 4, 40 occupied buckets against 40
    eligible bonds). At the long end, therefore, a 3-month bucket ladder is a per-CUSIP
    signal wearing a bucket's clothes; only at ``width_y >= 0.5`` (median 2 bonds) does
    the aggregation do anything at all. This is a property of the Treasury's issuance
    calendar, not of the code, and it is why ``width_y`` is swept.
    """
    u = universe.copy()
    u["bucket"] = bucket_of(u["ttm"], band_low=band[0], band_high=band[1], width_y=width_y)
    l = ladder[["date", "bucket", column]].rename(columns={column: out_column})
    return u.merge(l, on=["date", "bucket"], how="left")


def attach_many(universe: pd.DataFrame, specs: Mapping[str, Tuple[pd.DataFrame, str, float]],
                *, band: Tuple[float, float] = COMMON_BAND) -> pd.DataFrame:
    """``{out_column: (ladder, column, width_y)}`` -> one universe with all of them.

    Attaching every variant once, up front, is what lets the grid sweep fund set,
    construction and bucket width without ever rebuilding the universe -- which
    ``grid.run_grid`` would do, and which would discard these columns.
    """
    u = universe
    for out_col, (ladder, col, width) in specs.items():
        u = attach(u, ladder, column=col, out_column=out_col, band=band, width_y=width)
    return u


# ---------------------------------------------------------------- diagnostics


def coverage_report(asof: pd.DataFrame, universe: pd.DataFrame,
                    *, band: Tuple[float, float] = COMMON_BAND) -> pd.DataFrame:
    """Per fund: dates covered, staleness, and share of the eligible board it holds.

    Printed before any P&L. The single-fund study's 2017 hole hid because a by-year median
    over ALL panel dates reported that year's breadth as 0.0%, which reads as "held
    nothing" rather than "no file". Everything here is computed over days a book exists.
    """
    lo, hi = band
    u = universe[universe["ttm"].between(lo, hi, inclusive="left")]
    board = u.groupby("date")["cusip"].nunique().rename("n_board")
    held = asof.merge(u[["date", "cusip"]], on=["date", "cusip"], how="inner")

    rows = []
    for tkr, g in held.groupby("ticker"):
        n_held = g[g["par"] > 0].groupby("date")["cusip"].nunique()
        share = (n_held / board.reindex(n_held.index)).dropna()
        src = g["source"].iloc[0]
        rows.append({
            "fund": tkr, "source": src,
            "first_date": g["date"].min().date(), "last_date": g["date"].max().date(),
            "panel_dates": int(g["date"].nunique()),
            "distinct_books": int(g["obs_date"].nunique()),
            "stale_days_med": float(g["stale_days"].median()),
            "stale_days_max": int(g["stale_days"].max()),
            "board_share_med": float(share.median()),
            "board_share_min": float(share.min()),
            "par_bn_med": float(g.groupby("date")["par"].sum().median() / 1e9),
        })
    return pd.DataFrame(rows).sort_values("fund").reset_index(drop=True)


def independence(ladders: Mapping[str, pd.DataFrame], column: str) -> pd.DataFrame:
    """Correlation of the bucket measure across fund sets -- how many views is this really.

    The brief's measurement on one date was SPTL vs VGLT +0.952, i.e. effectively one view
    rather than two. This is the same question asked over the whole panel and over the
    quantity actually traded.
    """
    wide = {}
    for name, l in ladders.items():
        wide[name] = l.set_index(["date", "bucket"])[column]
    w = pd.DataFrame(wide)
    return w.corr()


# ---------------------------------------------------------------- the build


def column_name(construction: str, fund_set: str, width_y: float,
                combine: str = "") -> str:
    """One deterministic name per (construction, fund set, bucket width, combine).

    Every variant is attached to ONE universe up front and selected by name at run time.
    That is not tidiness: ``grid.run_grid`` calls ``prepare_universe`` itself for each of
    its own cache keys and rebuilds the frame from the holdings store, which would discard
    every attached column silently and leave ``sig_precomputed`` raising -- or worse,
    leave a stale column from a different variant in place.
    """
    w = f"w{width_y:g}".replace(".", "")
    tail = f"__{combine}" if combine else ""
    return f"agg_{construction}__{fund_set}__{w}{tail}"


def first_complete_date(asof: pd.DataFrame, fs: FundSet) -> Optional[pd.Timestamp]:
    """The first panel date on which EVERY fund in the set has a published book.

    Before it, an "aggregate" ladder is one or two of its funds wearing the aggregate's
    name. That matters far more than it sounds, because the signal is a z-score against
    the bucket's OWN history: if SPTL and VGLT switch on part-way through, the series
    being standardised has a level shift in it that belongs to no bond, and the z reads
    that shift as a dislocation on every bucket at once. So a fund set's ladder starts
    here, and the comparison against ``tlt_only`` is run from the same date for both.
    """
    if asof.empty:
        return None
    firsts = asof.groupby("ticker")["date"].min()
    missing = set(fs.tickers) - set(firsts.index)
    if missing:
        raise ValueError(f"{fs.name}: no observations at all for {sorted(missing)}")
    return pd.Timestamp(firsts.max())


def build_ladders(
    universe: pd.DataFrame,
    *,
    fund_sets: Sequence[str] = ("tlt_only", "coupon_long"),
    widths: Sequence[float] = (0.25,),
    combines: Sequence[str] = ("book",),
    band: Tuple[float, float] = COMMON_BAND,
    lookback: int = 250,
    min_periods: int = 120,
    weight_basis: str = "dv01",
    ladder_start: Optional[Any] = None,
    align_starts: bool = True,
    nport_directory: Optional[pathlib.Path] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Every (fund set x width x construction) ladder, plus the diagnostics, in one pass.

    Returns a dict with ``specs`` (ready for :func:`attach_many`), ``ladders``,
    ``offslice``, ``coverage`` and ``asof`` -- the last so the notebook can show what the
    as-of join actually chose without recomputing it.
    """
    dates = pd.DatetimeIndex(sorted(universe["date"].unique()))
    specs: Dict[str, Tuple[pd.DataFrame, str, float]] = {}
    ladders: Dict[str, pd.DataFrame] = {}
    offslices: Dict[str, pd.DataFrame] = {}
    coverage: Dict[str, pd.DataFrame] = {}
    asofs: Dict[str, pd.DataFrame] = {}
    starts: Dict[str, Optional[pd.Timestamp]] = {}

    # ---- pass one: load, and find out when each set is genuinely complete -----------
    for fs_name in fund_sets:
        fs = FUND_SETS[fs_name]
        obs = load_observations(fs, end=dates.max(), nport_directory=nport_directory)
        asof = as_of_panel(obs, dates)
        asofs[fs_name] = asof
        starts[fs_name] = first_complete_date(asof, fs)
        coverage[fs_name] = coverage_report(asof, universe, band=band)

    #: ONE start date across every set being compared, so the z-scores are standardised
    #: against the same amount of history. The task's framing -- same dates, same costs --
    #: has to bind here, BEFORE the backtest: a z built on ten years of history is a
    #: different signal from one built on eighteen months, not the same signal on more
    #: days, and letting ``tlt_only`` keep its extra four years would be comparing two
    #: estimators rather than two fund sets.
    common = max([v for v in starts.values() if v is not None], default=None)
    if ladder_start is not None:
        common = pd.Timestamp(ladder_start)
    if verbose:
        print("\nfirst date each fund set is COMPLETE:", flush=True)
        for k, v in starts.items():
            print(f"   {k:20s} {v.date() if v is not None else 'n/a'}", flush=True)
        print(f"   -> ladders start "
              f"{common.date() if common is not None else 'n/a'} "
              f"({'aligned across sets' if align_starts else 'per set'})", flush=True)

    twin_done: set = set()
    for fs_name in fund_sets:
        fs = FUND_SETS[fs_name]
        asof = asofs[fs_name]
        lo_date = common if (align_starts and common is not None) else starts[fs_name]
        if lo_date is not None:
            asof = asof[asof["date"] >= lo_date]
            uni_fs = universe[universe["date"] >= lo_date]
        else:
            uni_fs = universe
        if verbose:
            print(f"\n--- fund set {fs_name}: {', '.join(fs.tickers)} from "
                  f"{lo_date.date() if lo_date is not None else '?'} ---", flush=True)
            print(coverage[fs_name].to_string(index=False), flush=True)

        for w in widths:
            own = ownership_ladder(asof, uni_fs, band=band, width_y=w,
                                   lookback=lookback, min_periods=min_periods)
            key = column_name("own", fs_name, w)
            ladders[key] = own
            specs[key] = (own, "own_z", w)

            for cb in combines:
                act, off = active_ladder(asof, uni_fs, band=band, width_y=w,
                                         lookback=lookback, min_periods=min_periods,
                                         weight_basis=weight_basis, combine=cb)
                akey = column_name("act", fs_name, w, cb)
                ladders[akey] = act
                specs[akey] = (act, "active_z", w)
                offslices[akey] = off

            #: The NULL TWIN of the ownership ladder: the same bucket construction on the
            #: bucket's share of the BOARD's free float, which reads no holdings file at
            #: all. The parent study found the equivalent twin of ``bucket_hist_z`` was
            #: LARGER than the signal itself, so it is carried here from the start rather
            #: than discovered afterwards.
            twin = own[["date", "bucket", "float_usd", "n_bonds", "ttm_mid"]].copy()
            tot = twin.groupby("date")["float_usd"].transform("sum")
            twin["float_share"] = twin["float_usd"] / tot.replace(0.0, np.nan)
            twin["float_share_z"] = _rolling_z(twin, "float_share", lookback=lookback,
                                               min_periods=min_periods)
            #: ONE twin per width, not one per fund set. It reads no holdings file, so
            #: every set produces the identical column -- and four copies of one null,
            #: each counted as a separate configuration, would inflate the trial count
            #: that the deflated Sharpe is computed against. Naming it "board" says what
            #: it is a property of.
            tkey = column_name("floattwin", "board", w)
            if tkey not in twin_done:
                ladders[tkey] = twin
                specs[tkey] = (twin, "float_share_z", w)
                twin_done.add(tkey)

    return {"specs": specs, "ladders": ladders, "offslice": offslices,
            "coverage": coverage, "asof": asofs, "starts": starts,
            "ladder_start": common}


# ---------------------------------------------------------------- the runner


def run_overlays(
    overlays: Sequence[Mapping[str, Any]],
    *,
    base: Optional[Mapping[str, Any]] = None,
    universe: pd.DataFrame,
    funnel: Optional[Mapping[str, Any]] = None,
    progress: bool = True,
    keep_results: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """``grid.run_grid`` with the universe PINNED, because ours carries attached columns.

    ``grid.run_grid`` caches a universe per ``(fund, universe, curve, price_basis)`` key
    and rebuilds it with ``prepare_universe`` on a miss. That is right for the single-fund
    study and wrong here: the aggregate score lives in columns attached after preparation,
    and a rebuild drops them. So this is the same loop over the same
    ``engine.run_config``/``engine.summarize`` pair with the rebuild removed, and every
    downstream helper (``grid.expand``, ``grid.league``, ``grid.attach_dsr_from_pnl``) is
    reused unchanged.

    Per-trade P&L is always kept (a few kB per row) because the deflated Sharpe needs it;
    whole ``Result`` objects are ~1MB each and are kept only on request -- retaining them
    for a large grid is what made the parent study's largest funds thrash.
    """
    from RVUtils.ETFRebalance import engine as EN

    rows: List[Dict[str, Any]] = []
    kept: Dict[str, Any] = {}
    it = overlays
    if progress:
        try:
            import tqdm
            it = tqdm.tqdm(overlays, desc="AGG-GRID", unit="cfg")
        except ImportError:  # pragma: no cover
            pass

    for ov in it:
        cfg = EN.merge_config({**dict(base or {}), **dict(ov)})
        name = cfg.get("name", "?")
        try:
            res = EN.run_config(cfg, universe=universe, prepared_funnel=dict(funnel or {}))
        except Exception as exc:
            rows.append({"name": name, "trades": 0,
                         "error": f"{type(exc).__name__}: {exc}",
                         "config": json.dumps(dict(ov), default=str)})
            continue
        s = EN.summarize(res)
        row = {"name": name, **s, "config": json.dumps(dict(ov), default=str)}
        if res.closed is not None and not res.closed.empty:
            row["_pnl"] = res.closed["pnl_bp"].to_numpy(float)
        rows.append(row)
        if keep_results:
            kept[name] = res

    return pd.DataFrame(rows), kept
