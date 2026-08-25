"""Run the three expected-sentiment samples headless and pickle the results.

    conda run -n stir python notebooks/rv/fed_expected_sentiment_grids.py

The notebook imports the pickle rather than re-running the grids, so the
notebook executes in seconds and the expensive part is a plain process that can
be watched, killed and resumed. The pickle is written to the study directory and
is NOT committed; ``--quick`` cuts the rotation budget for a wiring check.
"""
from __future__ import annotations

import argparse
import io
import pathlib
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(HERE), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_expected_sentiment as E  # noqa: E402
import fed_expected_sentiment_run as R  # noqa: E402

OUT = HERE / "fed_expected_sentiment_results.pkl"

#: The three samples, and why each exists. They are never pooled into one
#: league: a Sharpe from one against a Sharpe from another compares instruments
#: AND samples at once.
SAMPLES = {
    "SR3": dict(
        structures=R.SR3_STRUCTURES,
        readings=("level", "chg"),
        start="2018-05-07",
        note="the tradeable book -- SR3 futures, 2018-05 onwards",
    ),
    "OIS21": dict(
        structures=("ois2y",),
        readings=("level", "chg"),
        start="2005-01-07",
        note=("21 years, a 2y SOFR OIS off the CurveStore discount factors. A "
              "MID, not an executable price -- and the clean re-run of the two "
              "shipped studies' 'does it reach the price' sections, which used "
              "the poisoned RATES.OIS.USD_SOFR.PAR.2Y tag"),
    ),
    "JPM": dict(
        structures=("out3", "ois2y"),
        readings=("level", "chg", "fit"),
        start="2018-05-07",
        note=("the ~121 weeks on which the point-in-time Fed sentiment index "
              "exists -- the only sample where the `fit` reading can run"),
    ),
}


def _p(*a):
    print(*a, flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="small rotation budget, for a wiring check")
    ap.add_argument("--only", default="", help="comma-separated sample names")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    draws = 60 if args.quick else 5000
    want = [s.strip() for s in args.only.split(",") if s.strip()] or list(SAMPLES)

    results = {}
    t_all = time.time()
    for name in want:
        spec = SAMPLES[name]
        _p("=" * 78)
        _p(f"{name}: {spec['note']}")
        _p("=" * 78)
        t0 = time.time()
        try:
            res = R.run_sample(label=name, structures=spec["structures"],
                               readings=spec["readings"], start=spec["start"],
                               rotation_draws=draws, show_progress=False)
        except Exception as exc:  # noqa: BLE001
            _p(f"  FAILED: {type(exc).__name__}: {exc}")
            results[name] = {"label": name, "error": f"{type(exc).__name__}: {exc}"}
            continue
        res["note"] = spec["note"]
        results[name] = res
        h = R.headline(res)
        _p(h.to_string())
        _p(f"  ... {time.time() - t0:.1f}s")

        # the vintage bound, on the pre-registered cell only
        try:
            prim = res["primary"]["config"]
            zc, _ = E.load_composite()
            import fed_detachment_prices as PX

            PX.seed_local_cache()
            syms = PX.sr3_universe(pd.Timestamp(spec["start"]).date(),
                                   pd.Timestamp("2026-08-24").date(), max_rank=4)
            panel = PX.settle_panel(syms)
            sess = np.asarray(pd.DatetimeIndex(panel.index).values,
                              dtype="datetime64[ns]")
            rate = (PX.curve_store_par_rate(2)
                    if prim.structure in E.NON_FUTURES else None)
            if rate is not None:
                # a non-futures leg trades on the RATE's sessions, not SR3's
                sess = np.asarray(pd.DatetimeIndex(rate.dropna().index).values,
                                  dtype="datetime64[ns]")
            vs = E.vintage_sensitivity(zc, prim, panel, sess, rate=rate,
                                       support=res['support'])
            res["vintage_sensitivity"] = vs
            _p("\n  vintage bound (composite delayed an extra d weeks):")
            _p("  " + vs.to_string(index=False).replace("\n", "\n  "))
        except Exception as exc:  # noqa: BLE001
            _p(f"  vintage sensitivity failed: {type(exc).__name__}: {exc}")
        _p("")

    with open(args.out, "wb") as f:
        pickle.dump(results, f)
    _p(f"\nwrote {args.out}  ({time.time() - t_all:.1f}s total)")

    _p("\n" + "=" * 78)
    _p("HEADLINES")
    _p("=" * 78)
    rows = [R.headline(r) for r in results.values() if "error" not in r]
    if rows:
        _p(pd.DataFrame(rows).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
