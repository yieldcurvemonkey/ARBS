r"""Is every cached MI01 date one that was actually REQUESTED?

92,879 rows stamped 2026-08-20 - the fetch day - are in the MI01 cache on all 192
served tags, and no MI01 request ever asked for a window ending later than
2026-08-06. Two explanations, with opposite consequences:

* the add-in appends the CURRENT session to a bounded request, in which case the
  extra rows are real data on one extra day and cost nothing; or
* the window logic leaks, in which case dates all over the history are arriving
  from requests that did not ask for them and the coverage census is measuring
  something other than what it claims.

The two are told apart by asking for the FULL set of unrequested dates rather
than by explaining away the one that was noticed. Requested spans are widened by
the measured bound offset - the request bound is read as UTC and the stamps come
back America/New_York, so a window can legitimately serve up to five hours before
its own start.
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache  # noqa: E402


def main() -> int:
    recs = [json.loads(l) for l in (DATA / "intraday_backfill_manifest.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]
    man = pd.DataFrame(recs)
    mi = man[man["layer"] == "mi01"]
    spans = [(pd.Timestamp(a) - pd.Timedelta(hours=6), pd.Timestamp(b))
             for a, b in zip(mi["w0"], mi["w1"])]
    # The two targeted auction windows are requested outside the manifest.
    for a in ("2026-08-13", "2026-05-13"):
        d = pd.Timestamp(a)
        spans.append((d - pd.Timedelta(days=2, hours=6), d + pd.Timedelta(days=2)))
    # The pre-existing four-day warm from an earlier session.
    spans.append((pd.Timestamp("2026-08-04") - pd.Timedelta(hours=6),
                  pd.Timestamp("2026-08-08")))

    requested = set()
    for a, b in spans:
        requested |= set(pd.date_range(a.normalize(), b.normalize(), freq="D").date)
    print(f"{len(spans)} requested MI01 spans covering {len(requested)} calendar dates")

    cache = CitiVeloTagCache()
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    extra: dict = {}
    total_rows = 0
    for isin in uni["isin"].astype(str):
        for value in ("YIELD", "PRICE"):
            s = cache.read(f"RATES.BOND.{isin}.{value}", "MI01", "CLOSE")
            if s is None or s.empty:
                continue
            d = pd.Series(s.index).dt.date
            total_rows += len(s)
            for day, n in d.value_counts().items():
                if day not in requested:
                    extra[day] = extra.get(day, 0) + int(n)
    print(f"cached MI01 rows: {total_rows:,}")
    if not extra:
        print("UNREQUESTED DATES: none. Every cached row is inside a window that was asked for.")
        return 0
    e = pd.Series(extra).sort_index()
    print(f"\nUNREQUESTED DATES: {len(e)}, carrying {int(e.sum()):,} rows "
          f"({100 * e.sum() / total_rows:.3f}% of the layer)")
    print(e.to_string())
    e.rename("rows").to_csv(DATA / "intraday_mi01_unrequested_dates.csv")
    print("\nwrote intraday_mi01_unrequested_dates.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
