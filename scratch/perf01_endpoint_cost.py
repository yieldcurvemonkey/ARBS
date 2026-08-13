"""What does each panel actually cost, on the wire and in the database?

The front end is data-intensive and that is not an opinion about it -- the
ladder ships one row per (bucket, session) and the prints chart now ships a
1-minute curve. This measures the four things that decide whether that is a
problem:

  1. SERVER time, warm, per endpoint.
  2. PAYLOAD, raw and gzipped -- what actually crosses the wire.
  3. ROWS SHIPPED vs ROWS USED. The heatmap renders 60 sessions; if the
     endpoint returns 629 the difference is pure waste, paid on every panel
     load, by every user.
  4. The HEAVIEST realistic case, not the median one. 2025-04-09 is the busiest
     measured SOFR 10Y D2C day (332 prints); a chart that is fine on a quiet
     Tuesday and unusable on the day everyone wants to look at is not fine.

Run against a PRODUCTION build. Dev-mode Next adds compile-on-demand to the
first hit of every route and dev-mode React re-renders far more than the
shipped bundle does; measuring dev and calling it performance would overstate
every number here.
"""
from __future__ import annotations

import gzip
import io
import json
import statistics
import sys
import time
import urllib.request as u

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3100"
API = f"{BASE}/api/usd-swaps-tape-v2"

# (label, path, what the panel actually consumes)
CALLS = [
    ("tape grid (200 rows, dd join)",
     "?limit=200", None),
    ("ladder /summary",
     "/direction/summary?venueClass=D2C&series=FLOW", None),
    ("ladder /standardised  ALL",
     "/direction/standardised?venueClass=D2C&series=FLOW", "heatmap uses 60 sessions"),
    ("ladder /standardised  60d",
     "/direction/standardised?venueClass=D2C&series=FLOW&from=2026-05-15", "same 60 sessions"),
    ("ladder /bucket 5-7Y",
     "/direction/bucket?venueClass=D2C&series=FLOW&bucket=5-7Y", None),
    ("ladder /coverage",
     "/direction/coverage?venueClass=D2C&series=FLOW", None),
    ("prints 10Y latest",
     "/direction/prints?tenor=10Y&rateIndex=SOFR&venueClass=D2C"
     "&kinds=OUTRIGHT&tenorMatch=strict&fwdMaxYears=0.02", None),
    ("prints 10Y BUSIEST DAY",
     "/direction/prints?date=2025-04-09&tenor=10Y&rateIndex=SOFR&venueClass=D2C"
     "&kinds=OUTRIGHT&tenorMatch=strict&fwdMaxYears=0.02", "332 prints measured"),
    ("prints 10Y busiest + packages + off-market",
     "/direction/prints?date=2025-04-09&tenor=10Y&rateIndex=SOFR&venueClass=D2C"
     "&kinds=OUTRIGHT,CURVE,FLY,PKG&tenorMatch=band&fwdMaxYears=0.25"
     "&includeOffMarket=true", "every filter relaxed at once"),
]

N_WARM = 5


def hit(path: str) -> tuple[float, bytes]:
    req = u.Request(API + path, headers={"Accept-Encoding": "identity"})
    t = time.perf_counter()
    with u.urlopen(req, timeout=600) as r:
        body = r.read()
    return (time.perf_counter() - t) * 1000, body


def describe(body: bytes) -> str:
    try:
        d = json.loads(body)
    except Exception:
        return ""
    bits = []
    if isinstance(d, dict):
        for k in ("rows", "data", "trades"):
            if isinstance(d.get(k), list):
                bits.append(f"{k}={len(d[k]):,}")
        mid = d.get("mid")
        if isinstance(mid, dict) and isinstance(mid.get("points"), list):
            bits.append(f"grid={len(mid['points']):,}")
        if isinstance(d.get("disclosures"), list):
            bits.append(f"discl={len(d['disclosures'])}")
    return " ".join(bits)


def main() -> int:
    print(f"target {BASE}\n")
    print(f"{'endpoint':<44} {'warm ms':>9} {'p95':>7} {'raw KB':>9} "
          f"{'gzip KB':>8} {'shape'}")
    print("-" * 118)
    out = {}
    for label, path, note in CALLS:
        try:
            hit(path)  # prime: route compile, PG plan, LRU
            times, body = [], b""
            for _ in range(N_WARM):
                ms, body = hit(path)
                times.append(ms)
        except Exception as e:  # noqa: BLE001
            print(f"{label:<44} ERROR {type(e).__name__}: {str(e)[:50]}")
            continue
        raw = len(body)
        gz = len(gzip.compress(body, 6))
        med = statistics.median(times)
        p95 = sorted(times)[-1]
        out[label] = dict(ms=med, raw=raw, gz=gz)
        print(f"{label:<44} {med:>9.1f} {p95:>7.0f} {raw/1024:>9.1f} "
              f"{gz/1024:>8.1f} {describe(body)}")
        if note:
            print(f"{'':<44} {'':>9} {'':>7} {'':>9} {'':>8} -> {note}")

    a = out.get("ladder /standardised  ALL")
    b = out.get("ladder /standardised  60d")
    if a and b:
        print()
        print("THE OVER-FETCH, MEASURED")
        print(f"  full history   {a['raw']/1024:8.1f} KB raw / {a['gz']/1024:6.1f} KB gz / {a['ms']:6.1f} ms")
        print(f"  60 sessions    {b['raw']/1024:8.1f} KB raw / {b['gz']/1024:6.1f} KB gz / {b['ms']:6.1f} ms")
        print(f"  wasted         {(a['raw']-b['raw'])/1024:8.1f} KB raw / "
              f"{(a['gz']-b['gz'])/1024:6.1f} KB gz / {a['ms']-b['ms']:6.1f} ms "
              f"  ({a['raw']/max(b['raw'],1):.1f}x the bytes the heatmap can draw)")

    # what the panel pays on a cold open of the Analytics tab
    panel = ["ladder /summary", "ladder /standardised  ALL", "ladder /bucket 5-7Y",
             "prints 10Y latest"]
    have = [out[k] for k in panel if k in out]
    if have:
        print()
        print("COLD OPEN OF THE ANALYTICS TAB (these four fire together)")
        print(f"  bytes  {sum(h['raw'] for h in have)/1024:8.1f} KB raw / "
              f"{sum(h['gz'] for h in have)/1024:6.1f} KB gz")
        print(f"  slowest single call {max(h['ms'] for h in have):.0f} ms "
              f"(they are parallel, so this is the wall clock, not the sum "
              f"{sum(h['ms'] for h in have):.0f} ms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
