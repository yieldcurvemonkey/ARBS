# %% [markdown]
# # The outcome map — an atlas
#
# Per SR3 quarterly, the FOMC outcome space of its resolved-by-expiry meetings
# collapses (exchangeability, day-weight 1) to the distribution of the total
# move COUNT: a set of atoms on a 25bp grid around the forward. Each atom is a
# **cell**, and each cell is priced twice — by the listed 25bp butterfly centred
# on it, and by the same butterfly under the ZQ FedWatch lattice with its
# unresolved-meeting smear.
#
# This notebook establishes what the map looks like before any strategy is
# imposed on it: where it exists at all, what its richness decomposes into,
# whether probability conservation holds the way the triangle ledger said it
# does, how fast the pieces move, and whether the second linear source agrees
# with the first. Every number below is computed by the cell above it.

# %%
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append("../../")
sys.path.append("../backtests")

DATA = Path("../data/outcome_map")
cells = pd.read_parquet(DATA / "cells.parquet")
cells["as_of"] = pd.to_datetime(cells["as_of"])
day = cells.drop_duplicates(["as_of", "symbol"]).copy()

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)

print(f"cell rows      : {len(cells):,}")
print(f"contract-days  : {len(day):,}")
print(f"sessions       : {cells['as_of'].nunique():,}")
print(f"symbols        : {cells['symbol'].nunique()}")
print(f"sample         : {cells['as_of'].min().date()} -> "
      f"{cells['as_of'].max().date()}")

# %% [markdown]
# ## 1. Where the map exists — and the uncomfortable answer
#
# A map needs at least three cells, which needs at least two resolved meetings.
# For a quarterly SR3 option — which expires *before* its reference quarter
# begins — that pushes the whole object out past two months to expiry. The
# meeting-prob feasibility frontier put the convergence channel *inside* 60 dte
# (89.5% channel-1 under 30 days, 0% saturated). So the outcome map, as an
# object, lives on the far side of the frontier from the convergence regime.

# %%
band = pd.cut(day["dte"], [0, 30, 45, 60, 90, 130, 160, 200])
avail = day.groupby(band, observed=True).agg(
    contract_days=("as_of", "size"), n_cells=("n_cells", "mean"),
    n_resolved=("n_resolved", "mean"),
    off_lattice=("off_lattice_premium", "mean"))
print("=== map availability by days to expiry ===")
print(avail.round(3).to_string())
under60 = int((day["dte"] < 60).sum())
print(f"\ncontract-days under 60 dte: {under60} of {len(day)} "
      f"({under60 / len(day):.1%})")
print("by year:")
print(day.groupby(day["as_of"].dt.year).agg(
    contract_days=("as_of", "size"), sessions=("as_of", "nunique"),
    n_cells=("n_cells", "mean")).round(2).to_string())

# %% [markdown]
# ZIRP produces no map at all: with every priced jump at zero the two-point
# supports are degenerate, the lattice collapses to one atom, and there are no
# cells to compare. The map is an object of a *moving* policy rate.

# %% [markdown]
# ## 2. Probability conservation — one premium, redistributed
#
# The butterfly kernels are a partition of unity in the interior, so the sum of
# the on-lattice cell prices divided by 25bp is the mass each side puts *on* the
# lattice. The difference is the off-lattice premium, read through identical
# kernels on both sides. The triangle ledger measured it once, on two dates;
# here it is over 1,500 contract-days.

# %%
cons = day.groupby(pd.cut(day["dte"], [0, 90, 130, 160, 200]),
                   observed=True).agg(
    n=("as_of", "size"), off_lattice_pp=("off_lattice_premium", "mean"),
    level_a_bp=("fit_a", "mean"), tilt_b_bp=("fit_b", "mean"),
    curv_c_bp=("fit_c", "mean"))
cons["off_lattice_pp"] *= 100.0
print("=== conservation ledger and the fitted decomposition (means) ===")
print(cons.round(2).to_string())
print(f"\nshare of contract-days with a POSITIVE off-lattice premium: "
      f"{(day['off_lattice_premium'] > 0).mean():.1%}")
print("(positive = the surface holds mass the lattice cannot represent)")

# %%
dbin = pd.cut(cells["d"], [-9, -1.5, -0.5, 0.5, 1.5, 9])
shape = cells.groupby(dbin, observed=True).agg(
    n=("d", "size"), mass=("p_lattice", "mean"), rich_bp=("rich_bp", "mean"),
    even_bp=("even_bp", "mean"), odd_bp=("odd_bp", "mean"),
    resid_bp=("resid_bp", "mean"))
print("=== the average map, by signed distance from the forward (cells) ===")
print(shape.round(3).to_string())
mode_rich = float(cells.loc[cells["d"].abs() < 0.5, "rich_bp"].mean())
wing_rich = float(cells.loc[cells["d"].abs() > 1.5, "rich_bp"].mean())
print(f"\nmodal cells {mode_rich:+.2f}bp vs wing cells {wing_rich:+.2f}bp "
      f"— the modal deficit and the wing surplus, measured as prices")

# %% [markdown]
# ## 3. The tilt has a level, and the level is not a trade
#
# The even part {level, curvature} is the standing dispersion premium: one
# price, which the linvol grid and family B both measured as fairly-priced
# insurance. The odd part is the tilt — the surface putting on-lattice mass
# where the lattice does not. If the tilt were mean-zero, fading it would be a
# clean convergence trade. It is not.

# %%
tilt = day.groupby(day["as_of"].dt.year)["fit_b"].agg(["mean", "std", "size"])
tilt["mean_over_std"] = tilt["mean"] / tilt["std"]
print("=== fitted tilt b (bp of richness per 25bp cell), by year ===")
print(tilt.round(3).to_string())
print(f"\nwhole sample: mean {day['fit_b'].mean():+.3f}bp, "
      f"std {day['fit_b'].std():.3f}, "
      f"share positive {(day['fit_b'] > 0).mean():.1%}")

# %% [markdown]
# A persistently positive tilt means the surface holds more on-lattice mass at
# HIGHER rates than the lattice does. Both the mean (parity) and the total mass
# are pinned, so that has to be paid for off-lattice on the LOW-rate side: it is
# the on-lattice shadow of a one-sided cut tail, which an even basis in `d`
# cannot absorb. Fading the raw tilt is therefore a standing short of that tail
# wearing a convergence costume — which is why the grid carries a third rung,
# `pair_odd_dev`, measured against each contract's own trailing tilt.

# %%
p_floor = 0.01
cells["tradeable"] = cells["p_lattice"] >= p_floor
tr = cells.groupby(["as_of", "symbol"])["tradeable"].sum()
print("=== tradeable cells (>= 1% lattice mass) per contract-day ===")
print(tr.value_counts().sort_index().to_string())
print(f"\nfly centring error on the 6.25/12.5bp strike grid: "
      f"median {cells['offset_bp'].abs().median():.2f}bp, "
      f"p95 {cells['offset_bp'].abs().quantile(0.95):.2f}bp, "
      f"max {cells['offset_bp'].abs().max():.2f}bp")

# %% [markdown]
# ## 4. How fast the pieces move
#
# Pooled AR(1) within (symbol, cell) on each component. This sets the exit
# rules: a component with a 3-session half-life does not want a 15-session hold.

# %%
def pooled_ar1(frame: pd.DataFrame, col: str) -> tuple:
    piv = frame.pivot_table(index="as_of", columns=["symbol", "cell"],
                            values=col)
    xs, ys = [], []
    for c in piv.columns:
        s = piv[c].dropna()
        if len(s) < 20:
            continue
        xs.append(s.shift(1).iloc[1:].to_numpy())
        ys.append(s.iloc[1:].to_numpy())
    if not xs:
        return np.nan, np.nan, 0
    x, y = np.concatenate(xs), np.concatenate(ys)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    xm, ym = x - x.mean(), y - y.mean()
    phi = float(np.dot(xm, ym) / np.dot(xm, xm))
    hl = float(np.log(0.5) / np.log(abs(phi))) if 0 < abs(phi) < 1 else np.inf
    return phi, hl, len(x)


sub = cells[cells["tradeable"]]
rows = []
for col in ("rich_bp", "even_bp", "odd_bp", "resid_bp"):
    phi, hl, n = pooled_ar1(sub, col)
    rows.append({"component": col, "phi": round(phi, 4),
                 "half_life_sessions": round(hl, 2), "n_pairs": n})
print("=== pooled AR(1) of the cell components ===")
print(pd.DataFrame(rows).to_string(index=False))

# %% [markdown]
# ## 5. The second linear read
#
# The ZQ ladder bootstraps jumps out of monthly EFFR averages; the meeting-dated
# swap ladder reads them straight off a curve with no bootstrap, no month-end
# weight dilution and no expiry seam. They should agree. Where they do not, the
# hedge leg's mark is the thing in question, not the strategy.

# %%
zq = pd.read_parquet(DATA / "jumps_zq.parquet")
zq["as_of"] = pd.to_datetime(zq["as_of"])
sw_path = DATA / "jumps_swap.parquet"
if sw_path.exists():
    sw = pd.read_parquet(sw_path)
    sw["as_of"] = pd.to_datetime(sw["as_of"])
    j = zq.merge(sw, on=["as_of", "effective"], suffixes=("_zq", "_sw"))
    j["diff_bp"] = j["jump_bp_sw"] - j["jump_bp_zq"]
    print(f"overlapping (session, meeting) pairs: {len(j):,}")
    print("\n=== swap minus ZQ per-meeting jump (bp) ===")
    for label, m in (("first upcoming meeting", j["is_first"]),
                     ("all later meetings", ~j["is_first"])):
        g = j[m]["diff_bp"]
        print(f"  {label:24s} n={len(g):6,d}  median {g.median():+7.2f}  "
              f"MAD {g.sub(g.median()).abs().median():6.2f}  "
              f"|d|<=2bp {(g.abs() <= 2).mean():.1%}")
    print("\nThe first upcoming meeting is measured off the overnight fixing "
          "and is the contaminated one; the grid's swap leg drops it.")
else:
    print("no swap panel present")

# %% [markdown]
# ## 6. One map, in full
#
# A single contract-day, printed the way a trader would read it: the cells, what
# each side pays for them, and where the disagreement sits once the standing
# premium is projected out.

# %%
pick = (day[(day["n_cells"] >= 4) & (day["dte"].between(100, 160))]
        .sort_values("as_of").iloc[-1])
one = cells[(cells["as_of"] == pick["as_of"])
            & (cells["symbol"] == pick["symbol"])].sort_values("d")
print(f"=== {pick['symbol']} as of {pick['as_of'].date()}  "
      f"fwd {pick['forward_rate']:.3f}%  dte {int(pick['dte'])}  "
      f"smear {pick['smear_bp']:.1f}bp ===")
show = one[["atom_rate", "center_px", "d", "p_lattice", "p_opt", "p_fair",
            "mkt_bp", "fair_bp", "rich_bp", "even_bp", "odd_bp", "resid_bp"]]
print(show.round(4).to_string(index=False))
print(f"\nlattice mass on-lattice {one['p_fair'].sum():.3f} vs "
      f"surface {one['p_opt'].sum():.3f}  "
      f"-> off-lattice premium {pick['off_lattice_premium'] * 100:+.1f}pp")
print(f"fit: level {pick['fit_a']:+.2f}bp, tilt {pick['fit_b']:+.2f}bp/cell, "
      f"curvature {pick['fit_c']:+.2f}bp/cell^2")

# %% [markdown]
# ## What the atlas establishes
#
# Read off the cells above, in order: where the map exists at all, whether the
# premium is one price or many, whether the tilt is a deviation or a level, how
# fast each component decays, and whether the two linear markets agree about the
# object the hedge leg would be marked against. The grid notebook takes it from
# here.
