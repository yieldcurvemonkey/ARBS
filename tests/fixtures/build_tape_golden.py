"""Build golden snapshot of TradeTape output for regression testing.

Run once (before optimization), produces pickle file consumed by
tests/test_tape_optimization.py::TestPartAEquivalence tests.

Usage: conda run -n stir python tests/fixtures/build_tape_golden.py
"""
import os
import sys
import datetime
import pickle

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
NOTEBOOK_DIR = os.path.join(PROJECT_ROOT, "notebooks", "sdr")

sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, NOTEBOOK_DIR)

import _usd_swaps_common as sdr
from SDRUtils.analytics.trade_tape import TradeTape

OUTPUT = os.path.join(HERE, "tape_golden_mar_2_6.pkl")


def build() -> None:
    classified_df, raw_df = sdr.load_usd_swaps(
        datetime.datetime(2026, 3, 2),
        datetime.datetime(2026, 3, 6),
        return_raw=True,
    )
    tape = TradeTape(classified_df, raw_df=raw_df)
    enriched = tape.compute()
    print(f"Enriched: {len(enriched):,} rows, {len(enriched.columns)} cols")

    with open(OUTPUT, "wb") as f:
        pickle.dump({
            "classified_df": classified_df,
            "raw_df": raw_df,
            "enriched": enriched,
        }, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"Wrote {OUTPUT} ({os.path.getsize(OUTPUT) / 1e6:.1f} MB)")


if __name__ == "__main__":
    build()
