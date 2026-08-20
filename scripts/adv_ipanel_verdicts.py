r"""Write the adversarial verdict table."""
from __future__ import annotations

import pathlib

import pandas as pd

DATA = pathlib.Path(r"C:\Users\chris\clee\ARBS-etf\notebooks\backtests\etf_rebalance\_data")

V = [
    # claim, report's number, my number, verdict, defect
    ("Panel shape 484,458 rows / 672 dates / 96 cusips / 11 marks",
     "484458/672/96/11", "484458/672/96/11", "CONFIRMED", "exact match"),
    ("As-of is the last print AT OR BEFORE the mark (no lookahead)",
     "asserted", "0 of 484,260 yield / 481,464 price marks violate", "CONFIRMED",
     "checker mutation-verified: 6 checks fire on a seeded-bad panel"),
    ("Same-calendar-day guard holds",
     "asserted", "0 cross-day resolutions", "CONFIRMED", "-"),
    ("staleness columns are arithmetically exact",
     "asserted", "max error 0.0 min", "CONFIRMED", "-"),
    ("Staleness table (15:00 med 0, 50.8% at mark, 1.16% >30min)",
     "0/50.8%/1.16%", "0/50.80%/1.16%", "CONFIRMED", "exact match; 09:30 also exact"),
    ("exec_lag >= 1 business day on holdings-derived fields",
     "n/a", "n/a", "N/A",
     "no holdings file is read; held_by_tlt is static meta and no signal was run"),
    ("Effects do not live only in stale marks",
     "not tested", "ceiling 0.0972 (<=30min) vs 0.0974 bp (<=5min)", "CONFIRMED",
     "freshness is irrelevant: 98.4% of 15:00 marks are <=5 min fresh"),
    ("Citi stamps are America/New_York",
     "4 arguments", "FOMC excess peaks at stamp 14, 3.33x; 17:00 movement collapses "
     "to 0.12x; DST centre-of-mass shift -0.245h not -1h", "CONFIRMED",
     "report's print-COUNT evidence is invalid (counts are flat around the clock, "
     "peak 19:00); movement-based test is the valid one and agrees"),
    ("No window came back silently downsampled",
     "0 downsampled", "96/96 served tags have GLOBAL min gap = 60s exactly; "
     "61 of 59,409 tag-days >=600s and all of those are >=3600s (near-empty days)",
     "CONFIRMED", "-"),
    ("Perfect-foresight 15:00->16:00 ceiling = 0.092 bp",
     "0.0917 (HOURLY layer, wide fit)", "0.0972 bp (MI01 layer, wide fit); "
     "0.0834 bp on resid_bp_tlt19", "CONFIRMED",
     "inherited from another agent's script, never recomputed here; my independent "
     "MI01 re-derivation is 6% HIGHER"),
    ("...but MEAN|fly| is the wrong ceiling statistic",
     "mean over all flies", "perfect foresight, best fly per date = 0.765 bp (wide) / "
     "0.4595 bp (tlt19)", "WEAKENED",
     "1.2% of seam flies DO beat the cost; the true perfect-foresight ceiling is 8x "
     "the reported one. Verdict survives, its stated margin does not"),
    ("Cost = 0.99 bp fly round trip (FedInvest bid/offer)",
     "0.9915", "0.9822 all bonds; 0.7864 on ttm>=19y; 0.7700 on ttm>=19y & held by TLT",
     "WEAKENED",
     "cost is taken over the whole 9.5-30y set while the ceiling and the 0.434 "
     "comparison are on ttm>=19y. Like-for-like cost is 0.77-0.79 bp, 22-27% lower. "
     "Not floor- or fallback-manufactured (115 of 41,174 spreads below the 0.5 floor)"),
    ("Cost convention (fly RT = 2 x full leg spread) is right",
     "0.99 vs daily 0.535", "same convention as costs.py; apples-to-apples",
     "CONFIRMED", "leg round trip = one full spread; |w| sums to 2 for a DV01-neutral fly"),
    ("FedInvest is struck ~11:34 NY, not ~15:00",
     "11:34/11:36, RMSE margin ~2%", "11:30 on a 37-candidate 15-min grid; argmin RMSE "
     "AND argmax daily-change corr both 11:30; 5 of 6 years pick 11:30 independently "
     "with a ~2x margin over the adjacent candidate", "CONFIRMED",
     "report UNDERSTATES its own case: its pooled 2% margin is diluted by 2 corrupt "
     "dates. Direction is airtight - Citi staleness could only move the true strike "
     "EARLIER than 11:30, never later"),
    ("Two-day step regression R2",
     "not reported", "0.510-0.525", "WEAKENED",
     "the script's own docstring calls a capped R2 on this test 'a warning, not a "
     "footnote'; the report omits it entirely"),
    ("'Reproduces the backfill's INDEPENDENT seam implementation to 0.0000 bp'",
     "6 of 6 windows", "true, but on RAW yield dispersion", "WEAKENED",
     "etf_seam_minute.py is a genuinely separate code path, so this validates the "
     "as-of resolver and the std. It does NOT validate the curve fit and does NOT "
     "validate the 0.092 ceiling, which is a different statistic entirely"),
    ("yield_gate_fail = 0 of 157,887 means the marks are clean",
     "0 failures", "220 bond-days on 3 dates disagree with FedInvest by 5-69.5 bp",
     "WEAKENED",
     "2024-08-05 is a whole-curve -5.99 bp level shift (sd only 0.38); 2023-08-01 and "
     "2023-12-04 similar. A possibility gate cannot see a plausible-but-misaligned "
     "curve. These 2 dates are why 2023's strike RMSE is 7.1 bp and flat"),
    ("Universe definition",
     "97 bonds ever held by TLT 2021-2026", "same", "WEAKENED",
     "'ever held' uses end-of-sample information to define the 2021 cross-section. "
     "Harmless for a dispersion/cost measurement, contaminating for any future signal"),
    ("Multiple testing: 40 cells, no signal search, nothing to deflate",
     "40 cells", "40 timestamp cells + 3 striketime script iterations (spec search) "
     "+ 3 fit variants x 11 marks + 8 horizons + 3 cost anchors", "CONFIRMED",
     "substantively correct: no P&L was maximised anywhere, so there is no alpha to "
     "deflate. The 11:30 selection survives its own 37-way search at p ~ 3e-6 "
     "(5 of 6 years agreeing on 1 of 37 cells)"),
    ("Arithmetic, one trade end to end (2023-11-03, 912810RY6/RZ3/SA7)",
     "-", "all 4 marks are exact 15:00:00/16:00:00 prints, stale 0; curve moved "
     "+1.945/+1.952/+1.971 bp; d(resid) -0.0104/-0.00985/-0.00539; "
     "fly = 2(-0.00985)-(-0.01040)-(-0.00539) = -0.00392 bp", "CONFIRMED",
     "ties out by hand to 5 decimals"),
    ("HEADLINE: the 15:00->16:00 seam family is DEAD",
     "0.092 / 0.99 = 0.093x", "at any attainable skill (rho<=0.2) gross is "
     "0.03-0.13 bp/trade against 0.77-0.99 bp cost = 0.04-0.24x. Even rho=1.0 "
     "perfect foresight trading the single best fly per date nets -0.23 bp/trade",
     "CONFIRMED",
     "verdict is right and is STRONGER than the report's own argument once the "
     "selective-trader escape route is closed"),
]


def main() -> int:
    pd.set_option("display.width", 300)
    pd.set_option("display.max_colwidth", 90)
    t = pd.DataFrame(V, columns=["claim", "report", "my_number", "verdict", "defect"])
    t.to_csv(DATA / "adv_ipanel_verdicts.csv", index=False)
    print(t[["claim", "verdict"]].to_string(index=False))
    print(f"\n{t['verdict'].value_counts().to_dict()}")
    print("wrote adv_ipanel_verdicts.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
