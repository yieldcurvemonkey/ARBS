"""Probe 7: what does STIRFutureMDP.get_data return when the requested minute has no bar?

Three outcomes matter and they look identical in a P&L series:
  - it takes the LAST bar at-or-before  -> stale but causal (fine, cap the staleness)
  - it takes the NEAREST bar either way -> can be a bar AFTER the request  => LOOKAHEAD
  - it takes the day's close            -> every intraday timestamp is the same => fake zeros

Method: pull the raw minute bars for a day, then ask the MDP for prices at
timestamps chosen relative to KNOWN bar times, and identify which bar it served.
"""

from __future__ import annotations

import sys
import datetime

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")

import pandas as pd
import pytz

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP, _normalize_symbol, _to_barchart_symbol

NY = pytz.timezone("America/New_York")
LDN = pytz.timezone("Europe/London")


def bars_for(mdp, symbol: str, day: datetime.date, tz) -> pd.DataFrame:
    fetcher = mdp._get_barchart_fetcher(required_concurrency=2)
    start = tz.localize(datetime.datetime(day.year, day.month, day.day, 0, 0))
    end = tz.localize(datetime.datetime(day.year, day.month, day.day, 23, 59))
    bc = _to_barchart_symbol(_normalize_symbol(symbol) or symbol)
    per = fetcher.barchart_timeseries_api(
        barchart_symbols=[bc], start_date=start, end_date=end,
        interval=1, one_df=False, show_tqdm=False,
    ) or {}
    for _k, v in per.items():
        if v is not None and len(v):
            df = v.copy()
            if getattr(df.index, "tz", None) is not None:
                df.index = df.index.tz_convert(tz)
            return df
    return pd.DataFrame()


def _plain(ts) -> datetime.datetime:
    """MDP._as_datetime uses `type(ts) == datetime.datetime`, so a pd.Timestamp
    (a subclass) is REJECTED. Every timestamp handed to the MDP must be plain."""
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    return datetime.datetime(
        ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second, tzinfo=ts.tzinfo
    )


def mdp_price(mdp, symbol: str, ts) -> float | None:
    try:
        res = mdp.get_data({"symbols": [symbol], "timestamp": _plain(ts)})
    except Exception as e:  # noqa: BLE001
        return f"ERR {type(e).__name__}: {str(e)[:60]}"  # type: ignore[return-value]
    flat = []
    for _k, v in (res or {}).items():
        flat.extend(v if isinstance(v, list) else [v])
    return float(flat[0].price()) if flat else None


def label_match(px, bars: pd.DataFrame, ts) -> str:
    """Which bar does this price correspond to, relative to the request time?"""
    if not isinstance(px, float):
        return str(px)
    hits = bars.index[(bars["Close"] - px).abs() < 1e-9]
    if len(hits) == 0:
        return f"{px} (NO MATCHING BAR)"
    before = [h for h in hits if h <= ts]
    after = [h for h in hits if h > ts]
    if before:
        h = max(before)
        return f"{px} <- bar {h:%H:%M} ({int((ts - h).total_seconds() // 60):+d} min, CAUSAL)"
    h = min(after)
    return f"{px} <- bar {h:%H:%M} ({int((h - ts).total_seconds() // 60)} min AFTER) ** LOOKAHEAD **"


def run_case(mdp, symbol: str, day: datetime.date, tz, name: str) -> None:
    print(f"\n{'='*100}\n{name}: {symbol} on {day} ({tz})\n{'='*100}")
    bars = bars_for(mdp, symbol, day, tz)
    if bars.empty:
        print("  no bars")
        return
    times = list(bars.index)
    print(f"  {len(bars)} bars, {times[0]:%H:%M} .. {times[-1]:%H:%M}")

    # find the largest interior gap to probe inside
    gaps = [(times[i + 1] - times[i], times[i], times[i + 1]) for i in range(len(times) - 1)]
    gaps.sort(reverse=True, key=lambda x: x[0])
    biggest = gaps[0] if gaps else None

    probes: list[tuple[str, datetime.datetime]] = []
    probes.append(("exactly on a bar", times[len(times) // 2]))
    if biggest and biggest[0] > datetime.timedelta(minutes=2):
        mid = biggest[1] + (biggest[2] - biggest[1]) / 2
        print(f"  biggest interior gap: {biggest[1]:%H:%M} -> {biggest[2]:%H:%M} ({biggest[0]})")
        probes.append(("inside biggest gap", mid))
        probes.append(("1 min after gap start", biggest[1] + datetime.timedelta(minutes=1)))
        probes.append(("1 min before gap end", biggest[2] - datetime.timedelta(minutes=1)))
    probes.append(("30 min BEFORE first bar", times[0] - datetime.timedelta(minutes=30)))
    probes.append(("3 h BEFORE first bar", times[0] - datetime.timedelta(hours=3)))
    probes.append(("30 min AFTER last bar", times[-1] + datetime.timedelta(minutes=30)))

    for label, ts in probes:
        px = mdp_price(mdp, symbol, ts)
        print(f"  {label:26s} @ {ts:%H:%M}  ->  {label_match(px, bars, ts)}")


def main() -> None:
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    run_case(mdp, "SR3Z25", datetime.date(2025, 11, 20), NY, "DENSE / USD")
    run_case(mdp, "J8Z25", datetime.date(2025, 6, 11), LDN, "MEDIUM / GBP")
    run_case(mdp, "RAZ25", datetime.date(2025, 6, 11), LDN, "SPARSE / EUR ICE")
    run_case(mdp, "EBZ25", datetime.date(2025, 6, 11), LDN, "SPARSE / EUR CME")


if __name__ == "__main__":
    main()
