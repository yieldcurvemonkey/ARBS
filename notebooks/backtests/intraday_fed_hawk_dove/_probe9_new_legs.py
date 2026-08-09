"""Probe 9: data for the new legs, and a proper JPY post-mortem.

(a) EUR Euribor (IM = ICE, TV = Eurex), CAD CORRA (RG), CHF SARON (J2)
(b) JPY TONA - exhaust every Barchart root before concluding it is absent, then
    check what the warmed Citi Velocity minute curve actually holds.
"""

from __future__ import annotations

import sys
import io
import datetime
import traceback

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")

import pandas as pd
import pytz

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP, _normalize_symbol, _to_barchart_symbol

LDN = pytz.timezone("Europe/London")
TYO = pytz.timezone("Asia/Tokyo")
TOR = pytz.timezone("America/Toronto")
ZRH = pytz.timezone("Europe/Zurich")

MONTH_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}


def nth_q(root, ref, n=3):
    from rateslib.scheduling import next_imm
    imm = datetime.datetime(ref.year, ref.month, ref.day)
    for _ in range(n):
        imm = next_imm(imm)
    return f"{root}{MONTH_CODES[imm.month]}{str(imm.year)[-2:]}"


DATES = [datetime.date(y, 6, d) for y, d in
         [(2021, 15), (2022, 15), (2023, 14), (2024, 12), (2025, 11), (2026, 10)]]

NEW_ROOTS = {
    "IM": ("EUR Euribor 3M (ICE)", LDN),
    "TV": ("EUR Euribor 3M (Eurex)", LDN),
    "RG": ("CAD CORRA 3M (MX)", TOR),
    "J2": ("CHF SARON 3M (Eurex)", ZRH),
    "EB": ("EUR ESTR 3M (CME) [baseline]", LDN),
}


def minute_coverage(mdp):
    fetcher = mdp._get_barchart_fetcher(required_concurrency=4)
    rows = []
    for root, (label, tz) in NEW_ROOTS.items():
        for d in DATES:
            sym = nth_q(root, d)
            bc = _to_barchart_symbol(_normalize_symbol(sym) or sym)
            n, lo, hi = 0, None, None
            try:
                per = fetcher.barchart_timeseries_api(
                    barchart_symbols=[bc],
                    start_date=tz.localize(datetime.datetime(d.year, d.month, d.day, 0, 0)),
                    end_date=tz.localize(datetime.datetime(d.year, d.month, d.day, 23, 59)),
                    interval=1, one_df=False, show_tqdm=False,
                ) or {}
                for _k, v in per.items():
                    if v is not None and len(v):
                        idx = v.index
                        if getattr(idx, "tz", None) is not None:
                            idx = idx.tz_convert(tz)
                        n, lo, hi = len(v), idx.min().strftime("%H:%M"), idx.max().strftime("%H:%M")
                        break
            except Exception as e:  # noqa: BLE001
                lo = f"ERR {type(e).__name__}"
            rows.append(dict(root=root, label=label, date=d, symbol=sym, bars=n, first=lo, last=hi))
            print(f"  {root:3s} {d} {sym:8s} bars={n:5d} {lo or '-'}..{hi or '-'}", flush=True)
    return pd.DataFrame(rows)


def pricer_path(mdp):
    print("\nMDP.get_data -> RLSTIRFuturePricer @ 2025-11-20")
    for root in ["IM", "TV", "RG", "J2", "EB"]:
        sym = nth_q(root, datetime.date(2025, 11, 20))
        try:
            res = mdp.get_data({"symbols": [sym], "timestamp": datetime.date(2025, 11, 20)})
            flat = []
            for _k, v in (res or {}).items():
                flat.extend(v if isinstance(v, list) else [v])
            if flat:
                p = flat[0]
                print(f"  {sym:8s} price={p.price():.4f} curve={p.curve_key()} "
                      f"eff={p.effective_date()} mat={p.maturity_date()}")
            else:
                print(f"  {sym:8s} EMPTY")
        except Exception as e:  # noqa: BLE001
            print(f"  {sym:8s} ERROR {type(e).__name__}: {str(e)[:100]}")


# ---------------------------------------------------------------- JPY
JPY_CANDIDATES = [
    "T0", "IT",              # what the repo maps to JPY-TONA
    "JE", "JY", "TN", "TO", "JB", "JG", "TF", "J1", "J3", "JT", "TU", "YE",
]


def jpy_barchart(mdp):
    print("\n" + "=" * 92)
    print("JPY: exhaust Barchart roots (contract Z25, EOD pricer path)")
    print("=" * 92)
    for root in JPY_CANDIDATES:
        sym = f"{root}Z25"
        try:
            res = mdp.get_data({"symbols": [sym], "timestamp": datetime.date(2025, 11, 20)})
            flat = []
            for _k, v in (res or {}).items():
                flat.extend(v if isinstance(v, list) else [v])
            print(f"  {sym:7s} -> {'OK price=' + str(flat[0].price()) if flat else 'EMPTY'}")
        except Exception as e:  # noqa: BLE001
            print(f"  {sym:7s} -> {type(e).__name__}: {str(e)[:70]}")


def jpy_citivelo():
    print("\n" + "=" * 92)
    print("JPY: what does the warmed Citi Velocity curve store actually hold?")
    print("=" * 92)
    try:
        from Caching.curve_store import CurveStore
    except Exception as e:  # noqa: BLE001
        print(f"  cannot import CurveStore: {e}")
        return
    try:
        store = CurveStore()
    except Exception as e:  # noqa: BLE001
        print(f"  cannot construct CurveStore: {e}")
        return

    candidates = [
        "JPY-TONAR-1D-LCH-CITIVELOEXCELMIN",
        "JPY-TONAR-1D-CITIVELOEXCELMIN",
        "JPY-TONAR-1D-JSCC-CITIVELOEXCELMIN",
        "JPY-TONAR-1D-LCH", "JPY-TONAR-1D",
        "EUR-EUROSTR-1D-CITIVELOEXCELMIN",
        "GBP-SONIA-1D-CITIVELOEXCELMIN",
        "USD-SOFR-1D-CITIVELOEXCELMIN",
        "CAD-CORRA-1D-CITIVELOEXCELMIN",
        "CHF-SARON-1D-CITIVELOEXCELMIN",
    ]
    for name in candidates:
        try:
            ds = store.available_dates(name)
            if ds:
                print(f"  {name:42s} {len(ds):5d} days  {min(ds)} .. {max(ds)}")
            else:
                print(f"  {name:42s}     0 days")
        except Exception as e:  # noqa: BLE001
            print(f"  {name:42s} ERR {type(e).__name__}: {str(e)[:60]}")


def main():
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    print("=" * 92)
    print("PROBE 9a: minute-bar coverage for the new roots")
    print("=" * 92)
    try:
        df = minute_coverage(mdp)
        df.to_csv(r"C:\Users\chris\clee\ARBS-gcb\notebooks\backtests\intraday_fed_hawk_dove\_probe_newlegs.csv", index=False)
        print("\n--- bars by root ---")
        print(df.groupby(["root", "label"])["bars"].agg(["sum", "min", "max"]).to_string())
    except Exception:
        traceback.print_exc()

    try:
        pricer_path(mdp)
    except Exception:
        traceback.print_exc()

    try:
        jpy_barchart(mdp)
    except Exception:
        traceback.print_exc()

    try:
        jpy_citivelo()
    except Exception:
        traceback.print_exc()

    print("\nDONE")


if __name__ == "__main__":
    main()
