"""Build daily par-rate panels from the banked Citi tag cache (offline).

One parquet per curve index: rows = business days (2005+), columns = tenor
tokens, values = par rates in PERCENT exactly as the wire serves them. No
interpolation, no fill — missing prints stay NaN so consumers must mask.

Rebuild: ``conda run -n stir python notebooks/backtests/citivelo_rv/build_curve_panel.py``
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

INDICES = ["USD_SOFR", "EUR_EUROSTR", "GBP_SONIA", "JPY_TONAR", "CAD_CORRA"]


def main() -> None:
    from MDP.CitiVelocityExcel import tags as T
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    out_dir = _REPO / "notebooks" / "data" / "citivelo_rv"
    out_dir.mkdir(parents=True, exist_ok=True)
    quotes = CitiVeloQuotes(offline=True)

    for idx in INDICES:
        grid = T.ois_par_grid(idx)
        frame = quotes.frame(grid, "DAILY", start=datetime.date(2005, 1, 1),
                             end=datetime.date.today())
        if frame is None or frame.empty:
            print(f"{idx}: EMPTY — skipped")
            continue
        frame = frame.rename(columns={t: t.rsplit(".", 1)[-1] for t in frame.columns})
        frame = frame.sort_index()
        out = out_dir / f"par_grid_{idx}.parquet"
        frame.to_parquet(out)
        nn = frame.notna().sum().sum()
        print(f"{idx}: {frame.shape[0]} days x {frame.shape[1]} tenors, "
              f"{nn:,} prints, {frame.index[0].date()} -> {frame.index[-1].date()} -> {out.name}")


if __name__ == "__main__":
    main()
