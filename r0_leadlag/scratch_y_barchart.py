"""Minimal, self-contained Barchart EOD volume fetch (external reconciliation source).

Deliberately NOT importing MDP.STIRFutures.BARCHART.BarchartFetcher: that class
carries proxy pools / token caches / rate limiters that would drag R0 into shared
state.  This is 40 lines of requests, used once, read-only.
"""
import sys, json
from io import StringIO
from urllib.parse import quote
import pandas as pd
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")


def _tokens(sess: requests.Session, dummy="ZN"):
    url = f"https://www.barchart.com/futures/quotes/{quote(dummy)}/interactive-chart"
    r = sess.get(url, headers={"User-Agent": UA, "accept": "text/html"}, timeout=30)
    r.raise_for_status()
    lar = sess.cookies.get("laravel_token")
    xsrf = sess.cookies.get("XSRF-TOKEN")
    if not xsrf:
        raise RuntimeError("no XSRF-TOKEN cookie")
    from urllib.parse import unquote
    return lar, unquote(xsrf)


def eod(symbol: str, start="20260501", end="20260810"):
    s = requests.Session()
    lar, xsrf = _tokens(s, dummy=symbol)
    url = (f"https://www.barchart.com/proxies/timeseries/historical/queryeod.ashx?"
           f"symbol={quote(symbol)}&data=daily&maxrecords=640&volume=contract&order=asc"
           f"&start={start}&end={end}")
    h = {"User-Agent": UA, "dnt": "1", "x-xsrf-token": xsrf,
         "referer": f"https://www.barchart.com/futures/quotes/{quote(symbol)}/interactive-chart"}
    r = s.get(url, headers=h, timeout=40)
    if r.status_code != 200 or not r.text.strip():
        raise RuntimeError(f"{symbol}: HTTP {r.status_code} len={len(r.text)}")
    df = pd.read_csv(StringIO(r.text), header=None)
    cols = ["Symbol", "Date", "Open", "High", "Low", "Close", "Volume", "OpenInterest"]
    df.columns = cols[: len(df.columns)]
    return df


if __name__ == "__main__":
    out = {}
    for sym in sys.argv[1:]:
        try:
            df = eod(sym)
            out[sym] = {str(d): int(v) for d, v in zip(df["Date"], df["Volume"])}
            print(sym, "rows", len(df), "last", df.tail(2).to_dict("records"))
        except Exception as e:
            print(sym, "ERR", repr(e)[:200])
    with open("C:/Users/chris/clee/ARBS-r0/r0_leadlag/cache/barchart_eod_vol.json", "w") as f:
        json.dump(out, f)
    print("wrote", sum(len(v) for v in out.values()), "day-rows")
