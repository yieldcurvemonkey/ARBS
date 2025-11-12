import datetime
import io
import gzip
import zlib
from typing import Optional, Dict

import pandas as pd  # Keep for compatibility
import polars as pl
import requests

DEFAULT_CME_HEADERS: Dict[str, str] = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-US,en;q=0.9",
    "dnt": "1",
    "priority": "u=0, i",
    "referer": "https://www.cmegroup.com/ftp/settle/TCF/",
    "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
}


def read_cme_tcf_with_headers(
    as_of: datetime.date,
    *,
    timeout: int = 30,
    headers: Optional[Dict[str, str]] = None,
    session: Optional[requests.sessions.Session] = None,
) -> pd.DataFrame:
    if not isinstance(as_of, datetime.date):
        raise TypeError("as_of must be a datetime.date")

    if as_of == datetime.date.today():
        as_of = (pd.Timestamp(as_of) - pd.tseries.offsets.BDay(1)).date()

    url = f"https://www.cmegroup.com/ftp/settle/TCF/TCF_{as_of:%Y%m%d}.csv"
    sess = session or requests.Session()
    hdrs = dict(DEFAULT_CME_HEADERS if headers is None else headers)

    # Build request
    resp = sess.get(url, headers=hdrs, timeout=timeout)
    if resp.status_code == 404:
        raise FileNotFoundError(f"TCF file not found for {as_of:%Y-%m-%d}: {url}")
    resp.raise_for_status()

    # Handle encodings (requests handles gzip/deflate; add br/zstd support)
    raw = resp.content
    enc = (resp.headers.get("Content-Encoding") or "").lower()
    if "br" in enc:
        try:
            import brotli

            raw = brotli.decompress(raw)
        except Exception as e:
            raise RuntimeError("Server replied Brotli-compressed but 'brotli' package is unavailable.") from e
    elif "zstd" in enc or "zstandard" in enc:
        try:
            import zstandard as zstd

            raw = zstd.ZstdDecompressor().decompress(raw)
        except Exception as e:
            raise RuntimeError("Server replied Zstandard-compressed but 'zstandard' package is unavailable.") from e
    elif "gzip" in enc:
        try:
            raw = gzip.decompress(raw)
        except Exception:
            # requests usually already handled gzip/deflate; ignore if already decompressed
            pass
    elif "deflate" in enc:
        try:
            raw = zlib.decompress(raw)
        except Exception:
            pass

    # Decode text (be forgiving)
    for enc_try in ("utf-8-sig", "utf-8", "latin1"):
        try:
            text = raw.decode(enc_try)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    # Trim leading blanks and keep from first delimiter-like line
    lines = [ln for ln in text.splitlines() if ln.strip()]
    head_idx = 0
    for i, ln in enumerate(lines[:20]):
        if any(ln.count(d) >= 1 for d in (",", "|", ";", "\t")):
            head_idx = i
            break
    csv_text = "\n".join(lines[head_idx:])

    # Sniff delimiter
    df = pd.read_csv(io.StringIO(csv_text), sep=None, engine="python")
    df.columns = [c.strip().replace(" ", "_").lower() for c in df.columns]
    df.insert(0, "as_of", pd.Timestamp(as_of))

    clearport_to_bbg = {
        "17": "US",
        "21": "TY",
        "25": "FV",
        "26": "TU",
        "3YR": "3Y",
        "TN": "UXY",
        "TWE": "TWE",
        "UBE": "WN",
    }
    df["ticker"] = df["pfcode"].map(clearport_to_bbg)
    return df