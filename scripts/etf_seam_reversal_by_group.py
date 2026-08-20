r"""Task 1, completed: the reversal of the 15:00->16:00 move, BY YEAR and BY DAY TYPE.

The pooled reversal numbers live in ``etf_seam_reversal.py``. This splits them, which
matters for one reason beyond completeness: forced buying into a month-end
reconstitution is supposed to push marks one way in the seam and let them come back
afterwards, so the month-end column of a level-reversal table is the classic
price-pressure signature and is the only cell here with a story attached.

Both versions of every reversal are reported, for the reason set out at length in
``etf_seam_reversal.py``: the seam ``y16 - y15`` and the overnight move
``y10_next - y16`` share the ``y16`` mark, so mark noise manufactures a negative
coefficient. The "clean" column measures the overnight leg from ``y17`` instead and
shares nothing with the seam.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.etf_seam_common import (  # noqa: E402
    DATA, FLY_ROUND_TRIP_BP, day_types, decompose, load_panel, newey_west_t,
)

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)


def beta(y: np.ndarray, x: np.ndarray, min_n: int) -> float:
    ok = np.isfinite(y) & np.isfinite(x)
    y, x = y[ok], x[ok]
    if len(y) < min_n:
        return np.nan
    xc = x - x.mean()
    d = float(np.dot(xc, xc))
    return float(np.dot(xc, y - y.mean()) / d) if d > 0 else np.nan


def main() -> int:
    p = load_panel(drop_early_close=True)
    p["seam"] = (p["y16"] - p["y15"]) * 100.0
    p["on_shared"] = (p["y10_next"] - p["y16"]) * 100.0
    p["on_clean"] = (p["y10_next"] - p["y17"]) * 100.0
    p["day_fwd"] = (p["y16_next"] - p["y16"]) * 100.0

    dec, obs = {}, {}
    for c in ("seam", "on_shared", "on_clean", "day_fwd"):
        dec[c], obs[c] = decompose(p, col=c)

    lev = pd.concat({c: dec[c].set_index("date")["level_bp"] for c in dec}, axis=1)
    dt = day_types(pd.DatetimeIndex(lev.index))
    lev = lev.join(dt[["day_type", "cal_days_to_month_end"]])
    lev["year"] = lev.index.year

    idio = obs["seam"][["date", "cusip", "idio"]].rename(columns={"idio": "seam"})
    for c in ("on_shared", "on_clean", "day_fwd"):
        idio = idio.merge(obs[c][["date", "cusip", "idio"]].rename(columns={"idio": c}),
                          on=["date", "cusip"], how="left")
    idio = idio.merge(dt[["day_type"]].reset_index(), on="date", how="left")
    idio["year"] = idio["date"].dt.year

    def table(key: str) -> pd.DataFrame:
        rows = []
        for k, g in lev.groupby(key, sort=True):
            gi = idio[idio[key] == k]
            m, se, t, n = newey_west_t(g["seam"])
            rows.append({
                key: k, "dates": len(g),
                "seam_level_mean_bp": float(g["seam"].mean()),
                "seam_level_nw_t": t,
                "seam_level_sd_bp": float(g["seam"].std()),
                "LEVEL_rev_shared_pct": -100 * beta(g["on_shared"].to_numpy(),
                                                    g["seam"].to_numpy(), 20),
                "LEVEL_rev_clean_pct": -100 * beta(g["on_clean"].to_numpy(),
                                                   g["seam"].to_numpy(), 20),
                "LEVEL_rev_to_next_close_pct": -100 * beta(g["day_fwd"].to_numpy(),
                                                           g["seam"].to_numpy(), 20),
                "IDIO_sd_bp": float(gi["seam"].std()),
                "IDIO_rev_shared_pct": -100 * beta(gi["on_shared"].to_numpy(),
                                                   gi["seam"].to_numpy(), 200),
                "IDIO_rev_clean_pct": -100 * beta(gi["on_clean"].to_numpy(),
                                                  gi["seam"].to_numpy(), 200),
                "IDIO_sd_vs_cost": float(gi["seam"].std()) / FLY_ROUND_TRIP_BP,
            })
        return pd.DataFrame(rows).set_index(key)

    by_type = table("day_type")
    by_year = table("year")
    print("=== SEAM LEVEL MOVE AND ITS REVERSAL, BY DAY TYPE ===")
    print("(a NEGATIVE seam_level_mean_bp is the sector RICHENING between the 15:00 "
          "cash mark and the 16:00 NAV strike)")
    print(by_type.round(4).to_string(), flush=True)
    print("\n=== BY YEAR ===")
    print(by_year.round(4).to_string(), flush=True)
    by_type.to_csv(DATA / "seam_reversal_by_daytype.csv")
    by_year.to_csv(DATA / "seam_reversal_by_year.csv")

    # Is the month-end level richening distinguishable from an ordinary day? This
    # is the only cell in the table with a structural story, so it gets a test
    # rather than an eyeball.
    a = lev.loc[lev["day_type"] == "month_end", "seam"]
    b = lev.loc[lev["day_type"] == "ordinary", "seam"]
    diff = float(a.mean() - b.mean())
    se = float(np.sqrt(a.var() / len(a) + b.var() / len(b)))
    print(f"\nmonth-end minus ordinary seam LEVEL move: {diff:+.4f} bp, "
          f"se {se:.4f}, t {diff / se:+.2f}, n {len(a)} vs {len(b)}. "
          f"|diff| / 0.535bp round trip = {abs(diff) / FLY_ROUND_TRIP_BP:.3f}x, and a "
          f"LEVEL move is not reachable by a butterfly in any case.", flush=True)
    pd.DataFrame([{"month_end_mean_bp": float(a.mean()),
                   "ordinary_mean_bp": float(b.mean()), "diff_bp": diff,
                   "se_bp": se, "t": diff / se, "n_month_end": len(a),
                   "n_ordinary": len(b),
                   "abs_diff_vs_cost": abs(diff) / FLY_ROUND_TRIP_BP}]).to_csv(
        DATA / "seam_monthend_level_test.csv", index=False)

    n_cells = len(by_type) * 6 + len(by_year) * 6 + 1
    print(f"\nCELLS EVALUATED IN THIS SCRIPT: {n_cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
