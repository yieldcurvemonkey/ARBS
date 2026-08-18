"""Financing and coupon carry for a DV01-matched UST switch, in spread bp per day.

The whole economics of the trade lives here
-------------------------------------------
An on-the-run Treasury is rich in yield *and* finances below GC. Those two facts are the
same fact: you are paid to hold the security and you pay to borrow it. A switch that is
long the seasoned issue and short the on-the-run therefore collects the yield premium as
it decays and pays the specialness the whole time it is on.

ARBS' own carry model cannot see this. ``Query/FixedRateBonds/carry_roll.py:584``
resolves ONE rate per date -- ``load_us_treasury_gc_fixing_pct``, which is the last
overnight SOFR (or Fed Funds) fixing -- and applies it to every bond in the universe.
Both legs of a switch then finance at the identical rate, the financing nets to
approximately zero, and the trade appears to be free. It is not: the JPM panel puts mean
specialness at 16.9bp (20y), 4.6bp (10y) and 4.0bp (5y) when an issue is special at all.
So this module carries its own per-issue financing and the engine must run with the
engine-native carry OFF, or the two double-count.

Carry lives in YIELD space, not cash space (this is the part that is easy to get wrong)
----------------------------------------------------------------------------------------
The obvious formula -- coupon income minus repo financing, converted to yield bp by
dividing by duration -- is WRONG here, and it fails in a way that looks plausible. It was
tried first and tied out against JPM's published per-CUSIP ``3m Carry`` at corr 0.158.

The tell is in JPM's own numbers. On 2025-08-26 two issues maturing within days of each
other:

    912828ZB9  cpn 1.125  price  96.60   JPM 3m carry  -12.9 bp
    91282CMP3  cpn 4.125  price 102.82   JPM 3m carry  -12.8 bp

Identical carry from a 1.125% discount bond and a 4.125% premium bond. Cash carry cannot
do that -- the low-coupon bond earns a quarter of the coupon income. What makes them equal
is pull-to-par: the discount bond's missing coupon comes back as price accretion. Cash
accounting books that accretion as *price return*; this engine measures price return as
``-D x dy``, which does not see it at all. Mixing the two drops the accretion entirely and
charges the coupon difference twice.

In yield space the identity is

    total return / (P x D)  =  (y - r) x dt / D  -  dy

so **carry = (y - r) / D per year**, independent of coupon. Verified against JPM's
``3m Carry`` -- which is exactly ``3m Fwd YTM - Spot YTM``, confirmed row-by-row (-15.4 vs
-15.5, -16.1 vs -16.0) -- with per-bucket correlations of

    0-2y 0.86 | 2-3y 0.92 | 3-5y 0.94 | 5-7y 0.98 | 7-10y 0.996 | 10-20y 0.93 | 20-40y 0.92

The residual is a near-constant COMMON-MODE offset of ~2 price-bp per quarter (flat across
every maturity bucket once multiplied by duration), most likely JPM discounting on a term
repo curve where this uses a flat rate. It matters less than it looks: a switch differences
two bonds of nearly equal duration, so a common price offset ``b`` contributes
``b x (1/D_long - 1/D_short)`` -- about 0.003bp per quarter on a 10y pair, against a
premium of 0.7-1.8bp. It is a level error in outright carry and a rounding error in switch
carry.

Specialness enters as ``r = GC - special``, hence ``+special/D`` on the long leg and
``-special/D`` on the short. The classic switch is short the on-the-run, which is the
special leg, so this term is the price of admission.

Conventions
-----------
* Year fractions ACT/360 (money-market), matching the tie-out.
* Specialness is floored at 0. An issue financing measurably ABOVE GC is a mode-estimation
  artefact, not a market state, and letting it through would pay the strategy to be short
  an ordinary bond.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

DEFAULT_REPO_PANEL = (
    pathlib.Path(__file__).resolve().parents[2]
    / "notebooks" / "backtests" / "ust_switch" / "_data" / "jpm_issue_repo_panel.parquet"
)

#: The JPM package is the only per-ISSUE financing source available, and it runs
#: 2016-08-10 .. 2025-08-26. The study window is 2010-2026, so ~40% of the sample has no
#: measured financing. That gap is filled by a MODEL (see :func:`build_specialness_model`)
#: and every result is reported in three financing modes so the reader can see what the
#: model is doing:
#:   "actual"   -- JPM per-issue specialness, restricted to the JPM window. Headline.
#:   "modelled" -- full window; JPM inside it, per-(tenor, rank, age) model outside.
#:   "none"     -- no financing at all. The control that shows how much of the result is
#:                 the financing assumption rather than the price action.
FINANCING_MODES = ("actual", "modelled", "none")

JPM_START = pd.Timestamp("2016-08-10")
JPM_END = pd.Timestamp("2025-08-26")


# --------------------------------------------------------------------------------------


def load_repo_panel(path: Optional[pathlib.Path] = None) -> pd.DataFrame:
    p = pathlib.Path(path or DEFAULT_REPO_PANEL)
    if not p.exists():
        raise FileNotFoundError(
            f"no JPM repo panel at {p}. Build it first:\n"
            f"  python notebooks/backtests/ust_switch/build_jpm_repo_panel.py"
        )
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    df["maturity"] = pd.to_datetime(df["maturity"])
    return df


def attach_financing(
    panel: pd.DataFrame,
    repo: pd.DataFrame,
    *,
    horizon: str = "1m",
) -> pd.DataFrame:
    """Join per-issue repo onto the bond panel on (date, coupon, maturity).

    CUSIP is not the join key because the JPM extract does not carry one in the
    issue-specific report; (coupon, maturity) identifies a US Treasury uniquely, and a
    reopening shares both with its original -- which is correct, since a reopening IS the
    same security and finances as one.

    ``horizon`` picks the 1m or 3m repo. 1m is the default: the trade's natural holding
    period is one auction cycle (roughly a month at the front, a quarter at the long end),
    and the 1m rate is the one an actual financing desk would roll.
    """
    lvl, sp, gc = f"repo_{horizon}", f"special_{horizon}_bp", f"gc_{horizon}"
    r = repo[["date", "cpn", "maturity", lvl, sp, gc]].rename(
        columns={lvl: "repo_pct", sp: "special_bp", gc: "gc_pct", "maturity": "maturity_date"}
    )
    out = panel.merge(r, on=["date", "cpn", "maturity_date"], how="left")

    # Specialness cannot be negative (see module docstring).
    out["special_bp"] = out["special_bp"].clip(lower=0.0)
    out["has_actual_financing"] = out["repo_pct"].notna() & out["gc_pct"].notna()
    return out


# --------------------------------------------------------------------------------------
# modelled specialness for the pre-2016 / post-2025 window


def build_specialness_model(panel: pd.DataFrame) -> pd.DataFrame:
    """Median specialness by (tenor, rank, days-since-issue bucket), fitted on JPM data.

    Median, not mean: specialness is a spiky, one-sided variable (a squeeze prints 100bp+
    while the modal day prints 0), and a mean would extrapolate a squeeze that was not
    happening into every quiet year. The median is the level a financing desk would
    actually plan around.

    Age bucket matters as much as rank: a rank-0 bond one day after auction and one day
    before the next auction are different securities from a financing desk's point of
    view, and lumping them hides the decay the trade is trying to harvest.
    """
    d = panel[panel["has_actual_financing"]].copy()
    if d.empty:
        raise ValueError("no rows with actual financing -- cannot fit the model")
    d["age_days"] = (d["date"] - d["issue_date"]).dt.days
    d["age_bucket"] = pd.cut(
        d["age_days"], bins=[-1, 7, 21, 45, 90, 180, 10_000],
        labels=["0-7", "8-21", "22-45", "46-90", "91-180", "180+"],
    )
    g = (
        d.groupby(["tenor", "rank", "age_bucket"], observed=True)["special_bp"]
        .agg(["median", "mean", "count"])
        .reset_index()
        .rename(columns={"median": "special_bp_model"})
    )
    return g


def apply_specialness_model(panel: pd.DataFrame, model: pd.DataFrame) -> pd.DataFrame:
    """Fill ``special_bp`` where no measured financing exists."""
    out = panel.copy()
    out["age_days"] = (out["date"] - out["issue_date"]).dt.days
    out["age_bucket"] = pd.cut(
        out["age_days"], bins=[-1, 7, 21, 45, 90, 180, 10_000],
        labels=["0-7", "8-21", "22-45", "46-90", "91-180", "180+"],
    )
    out = out.merge(
        model[["tenor", "rank", "age_bucket", "special_bp_model"]],
        on=["tenor", "rank", "age_bucket"],
        how="left",
    )
    # Any (tenor, rank, bucket) the model never saw falls back to the tenor/rank median.
    fallback = (
        model.groupby(["tenor", "rank"])["special_bp_model"].median().rename("special_bp_fb").reset_index()
    )
    out = out.merge(fallback, on=["tenor", "rank"], how="left")
    out["special_bp_model"] = out["special_bp_model"].fillna(out["special_bp_fb"]).fillna(0.0)
    out["special_bp_filled"] = out["special_bp"].where(out["has_actual_financing"], out["special_bp_model"])
    return out.drop(columns=["special_bp_fb"])


def attach_gc_fallback(panel: pd.DataFrame) -> pd.DataFrame:
    """GC outside the JPM window, from the repo's own SOFR/FF fixing ladder.

    SOFR is itself an overnight Treasury repo rate, so it is the right GC proxy, and
    ``MDP/CitiVelocityExcel/repo/store.py`` reaches the same conclusion for the term
    curve. Outside SOFR's history (pre-2018) the ladder falls back to Fed Funds.

    NOTE: the LEVEL of GC barely matters to a switch -- it appears on both legs with
    opposite signs and cancels to first order. What does not cancel is the SPECIALNESS
    difference, which is why that is modelled carefully and this is not.
    """
    from Query.FixedRateBonds.carry_roll import load_us_treasury_gc_fixing_pct

    out = panel.copy()
    need = out.loc[out["gc_pct"].isna(), "date"].dropna().unique()
    cache = {}
    for d in need:
        dd = pd.Timestamp(d).date()
        try:
            cache[d] = load_us_treasury_gc_fixing_pct(as_of_date=dd)
        except Exception:
            cache[d] = np.nan
    fill = out["date"].map(cache)
    out["gc_pct"] = out["gc_pct"].fillna(fill)
    return out


# --------------------------------------------------------------------------------------
# the daily carry itself




@dataclass(frozen=True)
class CarryConfig:
    #: "actual" | "modelled" | "none" -- see FINANCING_MODES.
    mode: str = "modelled"
    #: Isolate the specialness term and drop the (y - GC) level term. A control, not a
    #: trading choice: it answers "how much of the carry is the thing ARBS' native model
    #: cannot see", which is the whole reason this module exists.
    specialness_only: bool = False
    repo_horizon: str = "1m"


def _leg_carry_bp_per_year(leg: pd.DataFrame, *, specialness_only: bool = False) -> pd.Series:
    """Carry of one bond, in yield bp per YEAR, in the same space as the price P&L.

    See the module docstring: carry = (y - r) / D. Positive means the yield can rise by
    this much per year before the position breaks even.
    """
    y_bp = leg["YTM"] * 100.0
    gc_bp = leg["gc_pct"] * 100.0
    sp_bp = leg["special_used_bp"]
    dur = leg["MOD_DURATION"].replace(0.0, np.nan)
    if specialness_only:
        return sp_bp / dur
    # r = GC - specialness, so (y - r) = (y - GC) + specialness
    return (y_bp - gc_bp + sp_bp) / dur


def daily_carry_bp(
    long_leg: pd.DataFrame,
    short_leg: pd.DataFrame,
    cfg: CarryConfig,
) -> pd.Series:
    """Carry of a DV01-matched long/short switch, in spread bp per YEAR.

    The engine multiplies by the actual year-fraction between marks. Both frames must be
    indexed by date and carry ``YTM``, ``MOD_DURATION``, ``gc_pct``, ``special_used_bp``.
    """
    if cfg.mode == "none":
        return pd.Series(0.0, index=long_leg.index)
    cl = _leg_carry_bp_per_year(long_leg, specialness_only=cfg.specialness_only)
    cs = _leg_carry_bp_per_year(short_leg, specialness_only=cfg.specialness_only)
    return cl.sub(cs, fill_value=0.0)


def specialness_only_carry_bp(
    long_leg: pd.DataFrame, short_leg: pd.DataFrame
) -> pd.Series:
    """The specialness term alone, in spread bp per YEAR.

    ``+special_long/D_long - special_short/D_short``. Long a special issue is a BENEFIT
    (you finance it cheaply); short a special issue is a COST (you earn a below-GC rate on
    the cash you posted). The classic switch is short the on-the-run, which is the special
    leg, so this term is the price of admission and is normally negative.

    Isolated because the (y - GC) level term is large but nearly identical on two bonds of
    the same maturity, so it cancels; reporting only the total would hide that the
    specialness is the part actually doing the work.
    """
    return (
        _leg_carry_bp_per_year(long_leg, specialness_only=True)
        .sub(_leg_carry_bp_per_year(short_leg, specialness_only=True), fill_value=0.0)
    )
