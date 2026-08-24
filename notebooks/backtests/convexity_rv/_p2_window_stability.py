r"""GV block: is the brief's R2 a relationship, or a window?

The brief prints two OLS fits:

  BLUES CA on IMM_1x2y/IMM_1x5y/IMM_1x10y FLY RATE   n=161  R2=0.394  b=+0.1461
  BLUES CA on 10y10y/20y10y CURVE RATE               n=410  R2=0.505  b=-0.0993

The first reproduces exactly on this panel (const +7.6893, beta +0.1461,
R2 0.394).  The second is on a ~410-business-day window, and on the full 1,409
dates the same regression is R2 0.247 with beta -0.0790.  Those are not the
same statement, and the difference is worth measuring rather than explaining
away: a co-trend that is tight inside one regime and loose across several is a
different object from a stable pricing relationship, and only the second can
carry a hedge ratio.

Measures, for every declared leg against every primary structure:
  * the rolling 410-bd level R2 and beta, over the whole sample;
  * the Durbin-Watson of the level residual (a near-zero DW is the classic
    spurious-regression signature; the brief's own prints are 0.764 and 1.146);
  * the same statistics on WEEKLY data, where the CA mark noise is a smaller
    share of the variance;
  * the sub-window in which the brief's own number is reproduced, and what the
    same regression says everywhere else.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)

from RVUtils.ConvexityRV import gv_universe as U  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
CA = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
LEGS = pd.read_parquet(DATA / "p2_legs.parquet")
LEGS.index = pd.to_datetime(LEGS.index)
IDX = CA.index.intersection(LEGS.index)
CA, LEGS = CA.loc[IDX], LEGS.loc[IDX]
WIN = 410                       # the brief's own n


def sec(t: str) -> None:
    print(f"\n{'=' * 80}\n{t}\n{'=' * 80}")


def _ols(y: pd.Series, x: pd.Series) -> dict:
    j = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    if len(j) < 30:
        return {}
    X = np.column_stack([np.ones(len(j)), j["x"].to_numpy()])
    b, *_ = np.linalg.lstsq(X, j["y"].to_numpy(), rcond=None)
    e = j["y"].to_numpy() - X @ b
    r2 = 1.0 - e.var(ddof=0) / j["y"].to_numpy().var(ddof=0)
    dw = float(np.sum(np.diff(e) ** 2) / np.sum(e ** 2))
    return {"n": len(j), "const": float(b[0]), "beta": float(b[1]),
            "r2": float(r2), "dw": dw}


# ---------------------------------------------------------------------------
sec("1. The brief's two prints, reproduced and then extended")
# ---------------------------------------------------------------------------
y = CA[U.ca_col("BLUES")]
fly = LEGS["USD-SOFR-1D IMM_1x2y/IMM_1x5y/IMM_1x10y FLY RATE"]
cur = LEGS["USD-SOFR-1D 10y10y/20y10y CURVE RATE"]

rows = []
for name, x in (("IMM_1 2s5s10s fly", fly), ("10y10y/20y10y curve", cur)):
    for lab, sl in (("brief window (last 161)", slice(-161, None)),
                    ("brief window (last 410)", slice(-410, None)),
                    ("full sample (1409)", slice(None))):
        r = _ols(y.iloc[sl], x.iloc[sl])
        rows.append({"regressor": name, "window": lab, **r})
print(pd.DataFrame(rows).round(4).to_string(index=False))
print("\nThe brief's fly print (n=161, const +7.6893, beta +0.1461, R2 0.394) "
      "is the first row and reproduces exactly.  The curve print (n=410, "
      "R2 0.505, beta -0.0993) is a window statistic.")

# ---------------------------------------------------------------------------
sec(f"2. Rolling {WIN}-bd level R2: is the relationship stable?")
# ---------------------------------------------------------------------------
rows = []
for st in U.PRIMARY_STRUCTURES:
    yy = CA[U.ca_col(st)]
    for leg_id in U.LEGS:
        xx = U.leg_series(LEGS, leg_id, st)
        j = pd.concat([yy.rename("y"), xx.rename("x")], axis=1).dropna()
        r = j["y"].rolling(WIN).corr(j["x"])
        r2 = (r * r).dropna()
        b = (j["y"].rolling(WIN).cov(j["x"])
             / j["x"].rolling(WIN).var(ddof=1)).dropna()
        rows.append({
            "structure": st, "leg_id": leg_id,
            "r2_full": float(j["y"].corr(j["x"]) ** 2),
            "r2_roll_median": float(r2.median()),
            "r2_roll_min": float(r2.min()), "r2_roll_max": float(r2.max()),
            "beta_roll_median": float(b.median()),
            "beta_roll_min": float(b.min()), "beta_roll_max": float(b.max()),
            "beta_sign_flips": int((np.sign(b).diff().abs() > 0).sum()),
            "frac_beta_negative": float((b < 0).mean())})
W = pd.DataFrame(rows)
print(W.round(4).to_string(index=False))
W.to_parquet(DATA / "p2_window_stability.parquet")
_flips = int((W["frac_beta_negative"].between(0.02, 0.98)).sum())
_span = float((W["beta_roll_max"] - W["beta_roll_min"]).abs().median())
_med = float(W["beta_roll_median"].abs().median())
print(f"\nA hedge ratio needs a STABLE beta.  Across the {WIN}-bd rolling "
      f"windows the beta's range is {_span:.3f} at the median pair against a "
      f"median |beta| of {_med:.3f} -- a span {_span / _med:.1f}x the level "
      f"itself -- and the SIGN flips within the sample on {_flips} of "
      f"{len(W)} pairs.")

# ---------------------------------------------------------------------------
sec("3. The same regression at WEEKLY frequency")
# ---------------------------------------------------------------------------
rows = []
for st in U.PRIMARY_STRUCTURES:
    yy = CA[U.ca_col(st)].resample("W-WED").last()
    for leg_id in ("immF_2s5s10s", "immM_2s5s10s", "le_10y10y_20y10y",
                   "le_10y10y_15y10y"):
        xx = U.leg_series(LEGS, leg_id, st).resample("W-WED").last()
        lv = _ols(yy, xx)
        ch = _ols(yy.diff(), xx.diff())
        rows.append({"structure": st, "leg_id": leg_id,
                     "lvl_beta": lv.get("beta"), "lvl_r2": lv.get("r2"),
                     "lvl_dw": lv.get("dw"),
                     "chg_beta": ch.get("beta"), "chg_r2": ch.get("r2"),
                     "n_weeks": lv.get("n")})
WK = pd.DataFrame(rows)
print(WK.round(4).to_string(index=False))
print("\nWeekly sampling removes most of the CA's daily mark noise.  If the "
      "level relation were a pricing relationship rather than a co-trend, the "
      "CHANGE regression would strengthen here.  Compare chg_r2 with lvl_r2.")

summary = {
    "brief_fly_n161": _ols(y.iloc[-161:], fly.iloc[-161:]),
    "brief_curve_n410": _ols(y.iloc[-410:], cur.iloc[-410:]),
    "curve_full_sample": _ols(y, cur),
    "fly_full_sample": _ols(y, fly),
}
(DATA / "p2_window_stability.json").write_text(json.dumps(summary, indent=1))
print("\n" + json.dumps(summary, indent=1))
