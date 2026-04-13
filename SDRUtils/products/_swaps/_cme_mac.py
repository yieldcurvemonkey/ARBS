import datetime
import re
from io import StringIO

import pandas as pd
import requests
import ujson as json

import QuantLib as ql

_IMM_MONTH_CODES = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}


CME_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJsYXN0TmFtZSI6IkxlZSIsImNyZWF0ZWREYXRlIjoxNzY1MTI5NjI0LCJmaXN0TmFtZSI6IkNocmlzdG9waGVyIiwidW5vSWQiOiJVUjAwMDU1MjgzMiIsInVzZXJGaW5nZXJwcmludCI6IjE0OUYxMUM1MDM2ODU5NjJCMkY5MzkzMzA3RTJDMkJFOUMyQ0Y3MERGOTlDMEUxNkY2OEU5ODZFRDA4MzQ5QUQiLCJpc3MiOiJhdXRoMCIsInVzZXJUeXBlIjoiQiIsImV4cCI6MTc5NjY2NTYyNCwidXNlcklkIjoiNDIzMTgxIiwiZW1haWwiOiJjbDExNEBpbGxpbm9pcy5lZHUifQ.m-V5JPtYuTigqikPypbShQoJzYnHjsUJ5RiOdV5OEJE"
CME_USERID = "423181"

COOKIES_USERINFO = {
    "token": CME_TOKEN,
    "userId": CME_USERID,
}

COOKIES_DICT = {
    "userId": CME_USERID,
    "cmeToken": CME_TOKEN,
    "userinfo": json.dumps(COOKIES_USERINFO, separators=(",", ":")),
}


DEFAULT_CME_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-US,en;q=0.9",
    "cookie": "; ".join(f"{k}={v}" for k, v in COOKIES_DICT.items()),
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

from pathlib import Path
import os
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import tempfile


def _get_appdata_cache_dir(app_name: str = "mac_ref_cache") -> Path:
    if os.name == "nt":  # Windows
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:  # Linux / macOS
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    d = base / app_name
    d.mkdir(parents=True, exist_ok=True)
    return d


_MAC_CACHE_DIR = _get_appdata_cache_dir("cme_mac_ref")


def _mac_cache_path(year: int, month: int) -> Path:
    return _MAC_CACHE_DIR / f"mac_ref_{year:04d}_{month:02d}.parquet"


def _read_mac_cache(year: int, month: int) -> pd.DataFrame | None:
    p = _mac_cache_path(year, month)
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except Exception:
        return None


def _write_mac_cache(year: int, month: int, df: pd.DataFrame) -> None:
    p = _mac_cache_path(year, month)

    # atomic write
    with tempfile.NamedTemporaryFile(dir=p.parent, suffix=".parquet", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        df.to_parquet(tmp_path, engine="pyarrow", index=False)
        tmp_path.replace(p)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _parse_mac_tenor_years(tenor):
    if tenor is None or pd.isna(tenor):
        return None
    match = re.search(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>YR|YEAR|YEARS|MO|MON|MONTHS)", str(tenor).strip().upper())
    if not match:
        return None
    value = float(match.group("value"))
    unit = match.group("unit")
    if unit.startswith("Y"):
        return value
    if unit.startswith("M"):
        return value / 12.0
    return None


_TENOR_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>YR|YEAR|YEARS|MO|MON|MONTHS)", re.IGNORECASE)

_USG_CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)


def _to_ql_date(x) -> ql.Date | None:
    if x is None or (isinstance(x, float) and pd.isna(x)) or pd.isna(x):
        return None
    ts = pd.to_datetime(x, errors="coerce")
    if pd.isna(ts):
        return None
    return ql.Date(int(ts.day), int(ts.month), int(ts.year))


def _to_pd_ts(d: ql.Date | None) -> pd.Timestamp | None:
    if d is None:
        return None
    return pd.Timestamp(d.year(), d.month(), d.dayOfMonth())


def _calculate_mac_expiration_date(row: pd.Series) -> pd.Timestamp | None:
    start_date = row.get("imm_start_date")
    tenor = row.get("tenor_designation")
    if pd.isna(start_date) or tenor is None or pd.isna(tenor):
        return None

    m = _TENOR_RE.search(str(tenor).strip())
    if not m:
        return None

    value = float(m.group("value"))
    unit = m.group("unit").upper()

    # QuantLib Period requires integer length; MAC tenors are effectively integer in practice.
    n = int(round(value))
    if n <= 0:
        return None

    if unit.startswith("Y"):
        period = ql.Period(n, ql.Years)
    elif unit.startswith("M"):
        period = ql.Period(n, ql.Months)
    else:
        return None

    ql_start = _to_ql_date(start_date)
    if ql_start is None:
        return None

    # Use US Govt Bond calendar for date advancement; Following is a reasonable convention here.
    ql_start = _USG_CAL.adjust(ql_start, ql.Following)  # Ensure start is a business day
    ql_exp = _USG_CAL.advance(ql_start, period, ql.Following, False)

    return _to_pd_ts(ql_exp)


def fetch_mac_ref_data(
    effective_date=None,
    imm_code=None,
    timeout: int = 10,
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch CME MAC Standard reference data for the given effective date or IMM code.
    Cached monthly in Parquet under AppData.
    """

    date_source = imm_code or effective_date
    if date_source is None:
        raise ValueError("detect_mac requires an effective_date or imm_code.")

    # ---------------- resolve year / month ----------------
    if isinstance(date_source, str):
        match = re.fullmatch(r"([FGHJKMNQUVXZ])(\d{2}|\d{4})", date_source.strip().upper())
        if match:
            month = _IMM_MONTH_CODES[match.group(1)]
            year_part = match.group(2)
            year = int(year_part) if len(year_part) == 4 else 2000 + int(year_part)
        else:
            parsed = pd.to_datetime(date_source, errors="raise")
            year, month = int(parsed.year), int(parsed.month)
    elif isinstance(date_source, (datetime.date, datetime.datetime)):
        year, month = int(date_source.year), int(date_source.month)
    else:
        parsed = pd.to_datetime(date_source, errors="raise")
        year, month = int(parsed.year), int(parsed.month)

    # ---------------- cache read ----------------
    if use_cache and not force_refresh:
        cached = _read_mac_cache(year, month)
        if cached is not None and not cached.empty:
            return cached.copy()

    # ---------------- network fetch ----------------
    try:
        url = f"https://www.cmegroup.com/trading/interest-rates/files/SIFMA-MAC-coupons-cusips-{year:04d}-{month:02d}.csv"
        response = requests.get(url, timeout=timeout, headers=DEFAULT_CME_HEADERS)
        response.raise_for_status()
    except Exception:
        url = f"https://www.cmegroup.com/trading/interest-rates/files/sifma-mac-coupons-cusips-{year:04d}-{month:02d}.csv"
        response = requests.get(url, timeout=timeout, headers=DEFAULT_CME_HEADERS)
        response.raise_for_status()

    response.encoding = response.apparent_encoding
    df = pd.read_csv(StringIO(response.text.replace("\u00a0", " ")))

    # ---------------- normalize ----------------
    df.columns = [col.strip() for col in df.columns]
    df = df.rename(
        columns={
            "IMM Start Date": "imm_start_date",
            "Tenor Designation": "tenor_designation",
            "Coupon": "coupon",
        }
    )
    df["imm_start_date"] = pd.to_datetime(df.get("imm_start_date"), errors="coerce").dt.normalize()
    df["coupon"] = pd.to_numeric(df.get("coupon"), errors="coerce")
    df["tenor_years"] = df["tenor_designation"].apply(_parse_mac_tenor_years)
    df["expiration_date"] = df.apply(_calculate_mac_expiration_date, axis=1)

    # ---------------- cache write ----------------
    if use_cache and not df.empty:
        _write_mac_cache(year, month, df)

    return df
