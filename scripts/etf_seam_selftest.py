r"""Self-tests for the two estimators this study invented, run against inputs whose
answers are known in advance.

A checking tool that is itself wrong reports success and hides the thing it was
built to find, so neither the noise-share identity nor the level/slope/idio
decomposition is trusted until it recovers a planted answer.

1. **Noise share.** Simulate an hourly mark tape with a known idiosyncratic true
   move and a known iid quoting error. The estimator
   ``2 * (beta_disjoint - beta_shared)`` must return the planted noise share of the
   measured move variance.
2. **Decomposition.** Plant a cross-section that is exactly level plus slope plus
   curvature plus a known idiosyncratic term, and check the recovered
   idiosyncratic standard deviation and the variance shares.
3. **Early-close detector.** Plant a day whose 15:00 and 16:00 marks are identical
   and check that it is flagged, and that an ordinary day is not.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.etf_seam_common import decompose  # noqa: E402


def ols_beta(y, x):
    xc = x - x.mean()
    return float(np.dot(xc, y - y.mean()) / np.dot(xc, xc))


def test_noise_share(seed: int = 7) -> None:
    rng = np.random.default_rng(seed)
    n = 200_000
    sd_true, sd_noise = 0.09, 0.05        # bp per hourly TRUE move / per MARK
    # Four marks y13, y14, y15, y16 -> moves d1(13->14), d2(14->15), d3(15->16).
    D = rng.normal(0, sd_true, size=(n, 3))          # independent true moves
    e = rng.normal(0, sd_noise, size=(n, 4))         # iid mark noise
    d1 = D[:, 0] + e[:, 1] - e[:, 0]
    d2 = D[:, 1] + e[:, 2] - e[:, 1]
    d3 = D[:, 2] + e[:, 3] - e[:, 2]
    b_shared = ols_beta(d2, d1)                      # shares mark y14
    b_disjoint = ols_beta(d3, d1)                    # shares nothing
    est = 2.0 * (b_disjoint - b_shared)
    planted = 2 * sd_noise ** 2 / (sd_true ** 2 + 2 * sd_noise ** 2)
    print(f"[noise share] planted {planted:.4f}  estimated {est:.4f}  "
          f"beta_shared {b_shared:+.4f}  beta_disjoint {b_disjoint:+.4f}")
    assert abs(est - planted) < 0.02, (est, planted)

    # And the correction it feeds: measured idio sd -> true idio sd.
    sd_meas = float(np.std(d3))
    sd_corr = sd_meas * np.sqrt(1 - est)
    print(f"[noise share] measured move sd {sd_meas:.4f} -> corrected "
          f"{sd_corr:.4f}, truth {sd_true:.4f}")
    assert abs(sd_corr - sd_true) < 0.004, (sd_corr, sd_true)


def test_decompose(seed: int = 11) -> None:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=300, freq="B")
    ttm = np.linspace(20.0, 30.0, 40)
    x = (ttm - ttm.mean()) / ttm.std()
    sd_idio = 0.07
    rows = []
    for d in dates:
        lev, slo, cur = rng.normal(0, 1.2), rng.normal(0, 0.3), rng.normal(0, 0.1)
        y = lev + slo * x + cur * x ** 2 + rng.normal(0, sd_idio, size=len(x))
        for i in range(len(x)):
            rows.append({"date": d, "isin": f"B{i:02d}", "cusip": f"C{i:02d}",
                         "ttm": ttm[i], "m": y[i]})
    p = pd.DataFrame(rows)
    per_date, per_obs = decompose(p, col="m")
    got = float(per_date["sd_idio_bp"].median())
    # A 40-point fit of 3 parameters shrinks the residual sd by sqrt(1 - 3/40).
    expect = sd_idio * np.sqrt(1 - 3 / 40)
    print(f"[decompose] planted idio sd {sd_idio:.4f}, expected after the fit "
          f"{expect:.4f}, recovered {got:.4f}")
    assert abs(got - expect) < 0.004, (got, expect)
    shares = (per_date["var_after_level"].sum() / per_date["var_total"].sum())
    print(f"[decompose] level share {1 - shares:.4f} "
          f"(planted level sd 1.2 vs everything else ~0.33 -> expect ~0.9)")
    assert 0.85 < 1 - shares < 0.96, shares

    # A planted CONSTANT level move with zero dispersion must show level share 1.
    p2 = p.copy()
    p2["m"] = p2["date"].map({d: rng.normal(0, 1.0) for d in dates})
    per_date2, _ = decompose(p2, col="m")
    s2 = 1 - per_date2["var_after_level"].sum() / per_date2["var_total"].sum()
    print(f"[decompose] pure level move -> level share {s2:.6f} (expect 1.0)")
    assert s2 > 0.999999, s2


def test_early_close() -> None:
    from scripts.etf_seam_panel import flag_early_close
    rng = np.random.default_rng(3)
    idx = pd.DatetimeIndex(["2024-07-02", "2024-07-03"])
    cols = [f"B{i}" for i in range(40)]
    m15 = pd.DataFrame(rng.normal(4.0, 0.01, size=(2, 40)), index=idx, columns=cols)
    m16 = m15 + rng.normal(0, 0.01, size=(2, 40))
    m16.loc["2024-07-03"] = m15.loc["2024-07-03"]      # the stale early close
    out = flag_early_close(m15, m16)
    print(f"[early close] flags: {out['is_early_close'].to_dict()}")
    assert not out.loc["2024-07-02", "is_early_close"]
    assert out.loc["2024-07-03", "is_early_close"]


def main() -> int:
    test_noise_share()
    test_decompose()
    test_early_close()
    print("\nALL SELF-TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
