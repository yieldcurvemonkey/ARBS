"""S3 -- ladder coverage vs universe retention, recomputed, not quoted.

Reads the per-unit frames `scratch/pkgskew_extract.py` wrote to
``D:\\pkgskew_cache`` over its pinned window (2024-03-01 .. 2026-08-07) and
reports three numbers rather than one:

  retained          DV01 the universe keeps, before any PKG-N recovery;
  recoverable       DV01 `package_price` can orient (PKG-4+ carrying a PTP);
  ladder-weightable DV01 that can actually be multiplied by ``2p - 1``.

The third is the one a reader needs, and it is not the second: the package
rule produces a per-leg SIGN and a ``deviation_bps`` but no ``p``, and
``ladder.unit_ladder_rows`` needs ``p`` -- see scratch/ddseam_ladder_trace.py,
which walks the three branches it can take.

Prints the cache vintage first: the ``exclusion`` column here is whatever
``universe.unit_frame`` said when the cache was built, which is the
pre-recovery split, and that is exactly the baseline wanted.

    python scratch/ddseam_coverage.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import pandas as pd  # noqa: E402

CACHE = pathlib.Path(os.environ.get("PKGSKEW_CACHE", r"D:\pkgskew_cache"))
COLS = ["dv01_proxy", "exclusion", "exclusion_detail", "any_ptp", "n_legs",
        "as_of_date"]

#: DV01 that `package_price.tape_gate` actually marks ``recoverable``, as
#: reported by the recovery workflow. NOT recomputed here: the gate reads
#: ``other_payment_amount`` / ``package_transaction_price`` per leg and the
#: cached ``legs_*.parquet`` carries only the ``has_ptp`` boolean, so running
#: the real gate needs the tape. Carried as an input so the arithmetic that
#: turns it into a percentage is in a script rather than in prose -- and so the
#: cross-check below can fail if it stops reconciling.
GATED_RECOVERED_DV01 = 12.07e9
GATED_RECOVERED_CLAIM_PCT = 71.92


def pct(a, b) -> float:
    return 100.0 * float(a) / float(b) if b else float("nan")


def main() -> int:
    meta = CACHE / "meta.json"
    if meta.exists():
        m = json.loads(meta.read_text())
        print(f"cache window {m.get('start')} .. {m.get('end')}")
        print(f"cache module vintage: {m.get('modules')}\n")

    files = sorted(CACHE.glob("units_*.parquet"))
    if not files:
        print(f"no units_*.parquet under {CACHE}")
        return 2
    u = pd.concat([pd.read_parquet(f, columns=COLS) for f in files],
                  ignore_index=True)
    d = pd.to_datetime(u["as_of_date"])
    print(f"{len(files)} monthly frames, {len(u):,} units, "
          f"{d.min().date()} .. {d.max().date()}, "
          f"{d.dt.date.nunique():,} distinct tape days")

    tot = float(u["dv01_proxy"].sum())
    kept = u["exclusion"].isna()
    kept_dv01 = float(u.loc[kept, "dv01_proxy"].sum())

    pkg4 = ((u["exclusion"] == "UNORIENTABLE_PKG")
            & (u["exclusion_detail"] == "PKG-4+"))
    pkg4_dv01 = float(u.loc[pkg4, "dv01_proxy"].sum())
    rec = pkg4 & u["any_ptp"].fillna(False).astype(bool)
    rec_dv01 = float(u.loc[rec, "dv01_proxy"].sum())

    print(f"\nuniverse DV01 (proxy)            {tot:>18,.0f}")
    print(f"retained, pre-recovery           {kept_dv01:>18,.0f}  "
          f"{pct(kept_dv01, tot):6.2f}%   units {int(kept.sum()):>9,}")
    print(f"PKG-4+ UNORIENTABLE              {pkg4_dv01:>18,.0f}  "
          f"{pct(pkg4_dv01, tot):6.2f}%   units {int(pkg4.sum()):>9,}")
    print(f"  ...any leg carries a PTP       {rec_dv01:>18,.0f}  "
          f"{pct(rec_dv01, tot):6.2f}%   units {int(rec.sum()):>9,}"
          f"   ({pct(rec_dv01, pkg4_dv01):.2f}% of the PKG-4+ pond)")
    print("    ^ the CRUDE gate (`pkgskew_analyse.py` section 8) and an upper "
          "bound only:\n      it asks whether a PTP exists, not whether it "
          "reconciles.")
    print(f"  ...`tape_gate` recoverable     {GATED_RECOVERED_DV01:>18,.0f}  "
          f"{pct(GATED_RECOVERED_DV01, tot):6.2f}%"
          f"   ({pct(GATED_RECOVERED_DV01, pkg4_dv01):.2f}% of the pond)"
          "   [input, see constant]")
    post = kept_dv01 + GATED_RECOVERED_DV01
    print(f"retained, post-recovery          {post:>18,.0f}  "
          f"{pct(post, tot):6.2f}%")

    # Known-answer check: the workflow's headline must fall out of THIS
    # denominator, or one of the two numbers is measured on a different
    # population and the comparison below is meaningless.
    delta = abs(pct(post, tot) - GATED_RECOVERED_CLAIM_PCT)
    print(f"\ncross-check: recomputed post-recovery retention "
          f"{pct(post, tot):.2f}% vs the reported "
          f"{GATED_RECOVERED_CLAIM_PCT:.2f}%  ->  "
          f"{'AGREES' if delta <= 0.01 else 'DISAGREES'} ({delta:.3f} pp)")

    print("\n--- what reaches the ladder -------------------------------------")
    print(f"universe retention   {pct(kept_dv01, tot):6.2f}% -> "
          f"{pct(post, tot):6.2f}%   "
          f"(+{pct(GATED_RECOVERED_DV01, tot):.2f} pp)")
    print(f"ladder-weightable    {pct(kept_dv01, tot):6.2f}% -> "
          f"{pct(kept_dv01, tot):6.2f}%   (+0.00 pp)")
    print("  because `package_price` produces no `p`: with `p = None` and no\n"
          "  exclusion `ladder.unit_ladder_rows` RAISES, and with an exclusion\n"
          "  set the unit lands in `excluded` and `delta_dv01` is never formed.\n"
          "  A package tau fitted on the package `z` with\n"
          "  `probability.fit_mixture` is what closes the gap.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
