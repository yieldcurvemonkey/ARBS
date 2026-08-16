"""Harvest SOFR MID-CURVE listed option vol from Barchart per-strike EOD.

WHY THIS EXISTS
---------------
A SOFR mid-curve option is the listed analogue of a swaption on a FORWARD rate:
``3QZ26`` expires on the same day as the standard ``SFRZ26`` option (2026-12-11)
but is written on ``SFRZ29`` instead of ``SFRZ26``.  Same expiry, underlying three
years further out.  That is exactly the instrument needed to compare listed vol
against forward-curve structures, and it is the one thing the constant-maturity
QuikStrike panel (``ust_listed_vol.parquet``) cannot express.

WHY *THIS* ENDPOINT AND NOT ``qs_timeseries``
---------------------------------------------
``qs_timeseries`` cannot see mid-curves at all, and fails DANGEROUSLY:

  * a bare mid-curve root (``0QM26``) raises ``Invalid ... contract token``;
  * ``root_globex="S0"`` / ``product="S0"`` **silently returns the standard SR3
    series** -- S0, S2 and S3 all hand back the identical ``SR3M26`` column.  It
    looks like it worked.  Never trust a mid-curve hint on that endpoint.

The Barchart raw-EOD path does work.  Its cost shape is the good one: **one HTTP
call per (contract, strike, right) returns that leg's ENTIRE daily history**,
which is then cached forever.  Cost is therefore per-LADDER, not per-date -- adding
years of history to an existing ladder is free.

THE CACHE-POISONING HAZARD -- READ BEFORE SETTING ``--no-force``
----------------------------------------------------------------
``STIRFutureOptionMDP._fetch_barchart_eod_series`` records a permanent ``no_data``
marker for any symbol a batch failed to return, gated only on *some other* symbol
in the same batch having succeeded.  A partially-degraded batch therefore bakes
permanent misses for legs the vendor really does serve, and nothing but
``force_refresh=True`` will ever retry them.  This was observed: every near-money
``MMAZ26``/``MMBZ26`` leg sat as ``no_data`` while ``MMCZ26``'s full ladder held
218 clean daily bars.  So this script defaults to ``force_refresh=True`` for legs
currently marked ``no_data``, and records what it could not get AS DATA.

UNITS
-----
SR3 price = 100 - rate, so a NORMAL vol on the futures PRICE in price-points/yr is
numerically the same as a normal vol on the YIELD; x100 gives bp/yr, directly
comparable to QuikStrike ABPV.  The Bachelier inversion here was validated against
QuikStrike on two independent contracts spanning a 50% level difference:

    SFRM26  engine 45.01  vs  QuikStrike ABPV 44.74   (+0.6%)
    SFRZ26  engine 69.08  vs  QuikStrike ABPV 68.45   (+0.9%)

both over 2026-01-02..2026-03-31 with a flat 4% discount factor.  Mutation-tested:
tau x1.2 -> -7%, tau x0.8 -> +12%, tau in months -> -60%, price x1.1 -> +10%.

USAGE
-----
    # zero network; rebuild the panel from whatever legs are already cached
    python scripts/harvest_sofr_midcurve_vol.py --mode offline

    # small live probe, hard-capped, prints call count and wall time
    python scripts/harvest_sofr_midcurve_vol.py --mode probe --contracts 0QZ26 --max-calls 20

    # deliberate harvest of a ladder; ALWAYS pass a cap you are happy to spend
    python scripts/harvest_sofr_midcurve_vol.py --mode harvest \\
        --contracts 0QZ26 2QZ26 3QZ26 --max-calls 300
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import io
import json
import logging
import math
import os
import pathlib
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import brentq  # noqa: E402
from scipy.stats import norm  # noqa: E402

OUT_DIR = REPO / "notebooks" / "data" / "convexity_rv"
PANEL = OUT_DIR / "sofr_midcurve_probe.parquet"
COVERAGE = OUT_DIR / "sofr_midcurve_probe_coverage.json"

#: Mid-curve roots that CME lists as quarterlies, with their Barchart roots.
#: 0Q/2Q/3Q are proven reachable; 4Q/5Q are listed by CME but untested here.
MIDCURVE_ROOTS = {"0Q": "MMA", "2Q": "MMB", "3Q": "MMC", "4Q": "MMD", "5Q": "MME"}

#: Standard SR3 controls. Every mid-curve number is meaningless without the
#: same-expiry standard option beside it.
DEFAULT_CONTROLS = ["SFRZ26", "SFRM26"]

#: Discount factor rate. CME SOFR options are premium-up-front, so the settle is a
#: discounted expectation; 4% flat reproduces QuikStrike ABPV to <1% and avoids
#: dragging a curve MDP into a feasibility script.
DEFAULT_DF_RATE = 0.04

_SINK = io.StringIO()
_PREF = "rawEOD::v1::"


# --------------------------------------------------------------------------- #
# network guard + counter
# --------------------------------------------------------------------------- #
class NetGuard:
    """Count and hard-cap outbound HTTP.

    ``RVUtils.ConvexityRV.listed_cache_guard.cache_only`` patches ``requests``
    only.  The Barchart EOD data plane is **httpx** (``AsyncClient.get`` ->
    ``send``), and session tokens are cached at class level, so a warm process
    sails straight through a requests-only block.  This guard patches both, which
    is why the numbers it reports are the real ones.
    """

    def __init__(self, max_calls: int, *, block: bool):
        self.max_calls = int(max_calls)
        self.block = bool(block)
        self.n = 0
        self.urls: List[str] = []
        self._lock = threading.Lock()
        self._saved: Dict[str, Any] = {}

    def _bump(self, url: str) -> None:
        with self._lock:
            self.n += 1
            if len(self.urls) < 40:
                self.urls.append(url)
            n = self.n
        if self.block:
            raise RuntimeError(f"NetGuard: outbound HTTP blocked (offline mode): {url[:140]}")
        if n > self.max_calls:
            raise RuntimeError(f"NetGuard: hard cap of {self.max_calls} HTTP calls exceeded")

    def __enter__(self):
        import httpx
        import requests
        import requests.adapters

        guard = self

        orig_send = httpx.AsyncClient.send

        async def send(self, request, **kw):  # noqa: ANN001
            guard._bump(str(request.url))
            return await orig_send(self, request, **kw)

        orig_ssend = httpx.Client.send

        def ssend(self, request, **kw):  # noqa: ANN001
            guard._bump(str(request.url))
            return orig_ssend(self, request, **kw)

        orig_rsend = requests.adapters.HTTPAdapter.send

        def rsend(self, request, **kw):  # noqa: ANN001
            guard._bump(str(getattr(request, "url", "")))
            return orig_rsend(self, request, **kw)

        self._saved = {
            "a": (httpx.AsyncClient, "send", orig_send),
            "s": (httpx.Client, "send", orig_ssend),
            "r": (requests.adapters.HTTPAdapter, "send", orig_rsend),
        }
        httpx.AsyncClient.send = send
        httpx.Client.send = ssend
        requests.adapters.HTTPAdapter.send = rsend
        return self

    def __exit__(self, *exc):
        for cls, name, orig in self._saved.values():
            setattr(cls, name, orig)
        return False


# --------------------------------------------------------------------------- #
# cache introspection (zero network)
# --------------------------------------------------------------------------- #
def _cache():
    from Caching.DiskCacheMixin import DiskCacheMixin
    import diskcache

    return diskcache.FanoutCache(DiskCacheMixin.default_cache_path("STIRFutureOptionRawEOD_Cache"))


def cached_symbols(cache) -> List[str]:
    keys: List[str] = []
    for shard in cache._shards:
        keys.extend(list(shard.iterkeys()))
    return [k[len(_PREF):] for k in keys if isinstance(k, str) and k.startswith(_PREF)]


def cached_frame(cache, sym: str) -> Optional[pd.DataFrame]:
    ent = cache.get(_PREF + sym)
    if not isinstance(ent, dict) or ent.get("no_data"):
        return None
    f = ent.get("frame")
    return f if (f is not None and len(f)) else None


def cache_state(cache, sym: str) -> str:
    ent = cache.get(_PREF + sym)
    if ent is None:
        return "absent"
    if not isinstance(ent, dict):
        return "odd"
    if ent.get("no_data"):
        return "no_data"
    f = ent.get("frame")
    return "data" if (f is not None and len(f)) else "empty"


# --------------------------------------------------------------------------- #
# Bachelier
# --------------------------------------------------------------------------- #
def bachelier(F: float, K: float, tau: float, sigma: float, right: str, df: float = 1.0) -> float:
    if sigma <= 0 or tau <= 0:
        return df * (max(F - K, 0.0) if right == "C" else max(K - F, 0.0))
    s = sigma * math.sqrt(tau)
    d = (F - K) / s
    if right == "C":
        return df * ((F - K) * norm.cdf(d) + s * norm.pdf(d))
    return df * ((K - F) * norm.cdf(-d) + s * norm.pdf(d))


def implied_normal_vol(price, F, K, tau, right, df=1.0) -> Optional[float]:
    """sigma in PRICE POINTS per sqrt(year); None where the quote carries no vol."""
    if not (price and price > 0) or tau <= 0:
        return None
    intrinsic = df * (max(F - K, 0.0) if right == "C" else max(K - F, 0.0))
    if price <= intrinsic + 1e-12:
        return None
    try:
        return float(brentq(lambda s: bachelier(F, K, tau, s, right, df) - price,
                            1e-6, 5.0, xtol=1e-10, maxiter=200))
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# panel construction
# --------------------------------------------------------------------------- #
def atm_vol_series(
    cache,
    option_contract: str,
    *,
    df_rate: float = DEFAULT_DF_RATE,
    max_moneyness: float = 0.60,
    min_price: float = 0.0025 + 1e-9,
    symbols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Daily ATM normal vol (bp/yr) for one listed SOFR-style option contract.

    Nearest OTM listed strike each day (call if K>=F else put).  OTM rather than
    nearest-outright because a deep-ITM settle is nearly all intrinsic and carries
    no usable vol; ``min_price`` drops legs pinned at the 0.0025 minimum tick,
    which are the vendor's floor rather than a quote.
    """
    from MDP.STIRFutures._sofr_option_contracts import (
        _contract_to_barchart_contract, _decode_sofr_style_strike_token,
        _option_contract_to_underlying_contract, sofr_option_last_trade_date,
    )

    bc_opt = _contract_to_barchart_contract(option_contract)
    underlying = _option_contract_to_underlying_contract(option_contract)
    bc_ul = _contract_to_barchart_contract(underlying)

    fut = cached_frame(cache, bc_ul)
    if fut is None:
        raise RuntimeError(f"{option_contract}: no cached underlying {bc_ul}")
    ltd = sofr_option_last_trade_date(option_contract)
    if ltd is None:
        raise RuntimeError(f"{option_contract}: no last-trade-date rule (weekly root?)")

    syms = symbols if symbols is not None else cached_symbols(cache)
    legs: Dict[Tuple[float, str], pd.Series] = {}
    for s in syms:
        if not s.startswith(bc_opt + "|"):
            continue
        f = cached_frame(cache, s)
        if f is None:
            continue
        tok = s.split("|")[1]
        legs[(_decode_sofr_style_strike_token(tok[:-1]), tok[-1])] = f["Close"]
    if not legs:
        raise RuntimeError(f"{option_contract}: no cached option legs for {bc_opt}")

    ks_c = sorted(k for (k, r) in legs if r == "C")
    ks_p = sorted(k for (k, r) in legs if r == "P")

    rows: List[Dict[str, Any]] = []
    for dt, frow in fut.iterrows():
        d = pd.Timestamp(dt).date()
        if d >= ltd:
            continue
        F = float(frow["Close"])
        if not np.isfinite(F) or F <= 0:
            continue
        tau = (ltd - d).days / 365.0
        if tau <= 1 / 365.0:
            continue
        dfac = math.exp(-df_rate * tau) if df_rate else 1.0

        best = None
        for right, ks in (("C", sorted(k for k in ks_c if k >= F)),
                          ("P", sorted((k for k in ks_p if k <= F), reverse=True))):
            for k in ks:
                if abs(k - F) > max_moneyness:
                    break
                ser = legs.get((k, right))
                if ser is None or pd.Timestamp(dt) not in ser.index:
                    continue
                px = float(ser.loc[pd.Timestamp(dt)])
                if not np.isfinite(px) or px < min_price:
                    continue
                cand = (abs(k - F), k, right, px)
                if best is None or cand[0] < best[0]:
                    best = cand
                break

        if best is None:
            continue
        _, K, right, px = best
        sigma = implied_normal_vol(px, F, K, tau, right, dfac)
        if sigma is None:
            continue
        rows.append(dict(
            date=pd.Timestamp(d), contract=option_contract, barchart_root=bc_opt,
            underlying=underlying, is_midcurve=option_contract[:2] in MIDCURVE_ROOTS,
            expiry=pd.Timestamp(ltd), forward=F, strike=K, right=right,
            price=px, tau_yrs=tau, atm_bpvol=sigma * 100.0,
        ))
    return pd.DataFrame(rows)


_BC_TO_ROOT = {v: k for k, v in MIDCURVE_ROOTS.items()}
_BC_TO_ROOT["SQ"] = "SFR"


def _distance_from_forward(cache, leg_symbol: str) -> float:
    """|strike - underlying close as of the option's expiry|.

    Anchored on the option's OWN last trading day, not the underlying's last bar.
    For an expired mid-curve the underlying outlives the option by years (0QZ24
    expires Dec-2024, its underlying SFRZ25 trades until Dec-2025), so the latest
    close would order the probe around a forward the option never saw.
    """
    from MDP.STIRFutures._sofr_option_contracts import (
        _contract_to_barchart_contract, _decode_sofr_style_strike_token,
        _option_contract_to_underlying_contract, sofr_option_last_trade_date,
    )

    try:
        bc_ct, leg = leg_symbol.split("|")
        root = _BC_TO_ROOT.get(bc_ct[:3]) or _BC_TO_ROOT.get(bc_ct[:2])
        code = bc_ct[len(bc_ct) - 3:]
        option_contract = f"{root}{code}"
        underlying = _option_contract_to_underlying_contract(option_contract)
        fut = cached_frame(cache, _contract_to_barchart_contract(underlying))
        if fut is None:
            return 1e9
        ltd = sofr_option_last_trade_date(option_contract)
        if ltd is not None:
            sub = fut[fut.index <= pd.Timestamp(ltd)]
            if len(sub):
                fut = sub
        return abs(_decode_sofr_style_strike_token(leg[:-1]) - float(fut["Close"].iloc[-1]))
    except Exception:
        return 1e9


def strike_ladder(center: float, step: float = 0.125, half_width: float = 1.25) -> List[float]:
    n = int(round(half_width / step))
    return [round(center + i * step, 6) for i in range(-n, n + 1)]


def leg_symbols_for_ladder(cache, option_contract: str, *, step: float, half_width: float) -> List[str]:
    """Barchart leg symbols spanning where the underlying actually traded.

    Centred on the underlying's own realised range rather than a single forward,
    so one pass covers the whole contract life; OTM side only (call above, put
    below) because that is the side that carries vol.
    """
    from MDP.STIRFutures._sofr_option_contracts import (
        _contract_to_barchart_contract, _format_strike4,
        _option_contract_to_underlying_contract, sofr_option_last_trade_date,
    )

    bc_opt = _contract_to_barchart_contract(option_contract)
    underlying = _option_contract_to_underlying_contract(option_contract)
    fut = cached_frame(cache, _contract_to_barchart_contract(underlying))
    if fut is None:
        raise RuntimeError(f"{option_contract}: underlying {underlying} not cached; harvest it first")
    ltd = sofr_option_last_trade_date(option_contract)
    if ltd is not None:
        fut = fut[fut.index <= pd.Timestamp(ltd)]
    if not len(fut):
        raise RuntimeError(f"{option_contract}: underlying has no bars before expiry")

    lo, hi = float(fut["Close"].min()), float(fut["Close"].max())
    centre = round((lo + hi) / 2 / step) * step
    span = max(half_width, (hi - lo) / 2 + half_width)
    out: List[str] = []
    for k in strike_ladder(centre, step=step, half_width=span):
        tok = _format_strike4(k, contract=option_contract)
        out.append(f"{bc_opt}|{tok}C")
        out.append(f"{bc_opt}|{tok}P")
    return out


# --------------------------------------------------------------------------- #
# live fetch
# --------------------------------------------------------------------------- #
def fetch_legs(mdp, symbols: List[str], *, force: bool, pause: float) -> Dict[str, pd.DataFrame]:
    """One batched call per chunk; each symbol costs one HTTP call for FULL history."""
    got: Dict[str, pd.DataFrame] = {}
    today = datetime.date.today()
    for i in range(0, len(symbols), 8):
        chunk = symbols[i:i + 8]
        with contextlib.redirect_stdout(_SINK), contextlib.redirect_stderr(_SINK):
            out = mdp._fetch_barchart_eod_series(
                symbols=chunk, start=datetime.date(2018, 1, 1), end=today,
                show_tqdm=False, force_refresh=force,
                max_concurrent_tasks=4, max_keepalive_connections=4,
                max_requests_per_second=3,
            )
        for k, v in (out or {}).items():
            if v is not None and len(v):
                got[k] = v
        time.sleep(pause)
    return got


# --------------------------------------------------------------------------- #
def build_panel(cache, contracts: List[str], df_rate: float) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    syms = cached_symbols(cache)
    frames, cov = [], {}
    for ct in contracts:
        try:
            df = atm_vol_series(cache, ct, df_rate=df_rate, symbols=syms)
        except Exception as e:  # a contract with nothing on disk is data, not a crash
            cov[ct] = {"n": 0, "note": f"{type(e).__name__}: {e}"}
            print(f"  {ct:<8} NONE  ({type(e).__name__}: {e})")
            continue
        if df.empty:
            cov[ct] = {"n": 0, "note": "no solvable ATM quotes"}
            print(f"  {ct:<8} NONE  (legs cached but no solvable ATM quote)")
            continue
        frames.append(df)
        cov[ct] = {
            "n": int(len(df)), "first": str(df["date"].min().date()),
            "last": str(df["date"].max().date()),
            "median_bpvol": round(float(df["atm_bpvol"].median()), 3),
            "min_bpvol": round(float(df["atm_bpvol"].min()), 3),
            "max_bpvol": round(float(df["atm_bpvol"].max()), 3),
            "max_abs_daily_change_bp": round(float(df.sort_values("date")["atm_bpvol"].diff().abs().max()), 3),
            "underlying": str(df["underlying"].iloc[0]),
            "expiry": str(df["expiry"].iloc[0].date()),
            "is_midcurve": bool(df["is_midcurve"].iloc[0]),
        }
        print(f"  {ct:<8} {len(df):>5} rows  {df['date'].min():%Y-%m-%d}..{df['date'].max():%Y-%m-%d}  "
              f"median {df['atm_bpvol'].median():7.2f} bp/yr  "
              f"(underlying {df['underlying'].iloc[0]}, expiry {df['expiry'].iloc[0]:%Y-%m-%d})")
    panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return panel, cov


def verify(panel: pd.DataFrame) -> int:
    """Tie-out asserts. Returns the number of failures (0 = clean)."""
    fails: List[str] = []

    def chk(cond: bool, msg: str) -> None:
        print(("  OK   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)

    print("\n--- structural ---")
    chk(panel["atm_bpvol"].notna().all(), "no NaN vols")
    chk((panel["atm_bpvol"] > 0).all(), "all vols > 0")
    # Lower bound is 10, not 20: a front SR3 in its last weeks genuinely prints
    # sub-20 bp/yr once most of its reference quarter has already fixed (SFRM26
    # hit 16.8 on 2026-05-14).  That is the contract, not a bad quote.
    lo, hi = panel["atm_bpvol"].min(), panel["atm_bpvol"].max()
    chk(10 <= lo and hi <= 300, f"vols within 10..300 bp/yr (got {lo:.1f}..{hi:.1f})")
    chk((panel["tau_yrs"] > 0).all(), "tau > 0")
    chk((panel["date"] <= panel["expiry"]).all(), "date <= expiry")
    chk((panel["price"] > 0).all(), "prices > 0")

    print("\n--- ATM proxy sits near the forward, on the OTM side ---")
    mny = (panel["strike"] - panel["forward"]).abs()
    chk(mny.max() <= 0.60, f"max |K-F| {mny.max():.3f} <= 0.60 (median {mny.median():.4f})")
    c, p = panel[panel["right"] == "C"], panel[panel["right"] == "P"]
    chk((c["strike"] >= c["forward"] - 1e-9).all(), "all calls K >= F")
    chk((p["strike"] <= p["forward"] + 1e-9).all(), "all puts  K <= F")

    print("\n--- continuity ---")
    for ct, g in panel.sort_values("date").groupby("contract"):
        j = g["atm_bpvol"].diff().abs().max()
        chk(bool(j < 40), f"{ct}: max 1-day move {j:.2f} bp < 40")

    mc = panel[panel["is_midcurve"]]
    std = panel[~panel["is_midcurve"]]
    if not mc.empty and not std.empty:
        print("\n--- forward vol vs SAME-EXPIRY standard, on COMMON DAYS ---")
        # The comparison must be same-expiry AND same-days: the controls carry
        # years more history than the mid-curves, so a full-sample median of the
        # standard is a different regime, not a control.
        for ct in sorted(mc["contract"].unique()):
            sub = mc[mc["contract"] == ct]
            peer = std[std["expiry"] == sub["expiry"].iloc[0]]
            if peer.empty:
                continue
            j = sub.merge(peer, on="date", suffixes=("_mc", "_std"))
            if j.empty:
                continue
            ratio = (j["atm_bpvol_mc"] / j["atm_bpvol_std"]).median()
            chk(ratio > 1.0,
                f"{ct} vs {peer['contract'].iloc[0]}: forward vol / spot vol = "
                f"{ratio:.3f} > 1 ({len(j)} common days)")

    print("\n=== %s ===" % ("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILURE(S)"))
    return len(fails)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["offline", "probe", "harvest"], default="offline",
                    help="offline=0 HTTP; probe=tiny live test; harvest=ladder fetch")
    ap.add_argument("--contracts", nargs="*", default=["0QZ26", "2QZ26", "3QZ26"],
                    help="mid-curve option contracts, e.g. 0QZ26 2QZ26 3QZ26")
    ap.add_argument("--controls", nargs="*", default=DEFAULT_CONTROLS,
                    help="standard SR3 option contracts to include as the comparison")
    ap.add_argument("--max-calls", type=int, default=50,
                    help="HARD CAP on outbound HTTP calls; the run aborts past it. "
                         "Leave headroom over --plan-limit: session-token fetches "
                         "count too, and they are not one-per-leg.")
    ap.add_argument("--plan-limit", type=int, default=0,
                    help="probe mode: how many legs to request (default: --max-calls)")
    ap.add_argument("--step", type=float, default=0.125, help="strike ladder step")
    ap.add_argument("--half-width", type=float, default=1.25,
                    help="strikes either side of the underlying's realised range")
    ap.add_argument("--df-rate", type=float, default=DEFAULT_DF_RATE,
                    help="flat discount rate; 0.04 reproduces QuikStrike ABPV to <1%%")
    ap.add_argument("--pause", type=float, default=0.5, help="seconds between chunks")
    ap.add_argument("--no-force", action="store_true",
                    help="do NOT refetch legs marked no_data (trusts a possibly poisoned cache)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    ap.add_argument("--verify", action="store_true",
                    help="run tie-out asserts on the panel and exit non-zero on failure")
    a = ap.parse_args(argv)

    logging.disable(logging.WARNING)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = _cache()
    t0 = time.time()

    all_contracts = list(dict.fromkeys([*a.contracts, *a.controls]))
    net: Dict[str, Any] = {"mode": a.mode, "http_calls": 0, "cap": a.max_calls}

    if a.mode in ("probe", "harvest"):
        planned: List[str] = []
        for ct in a.contracts:
            try:
                legs = leg_symbols_for_ladder(cache, ct, step=a.step, half_width=a.half_width)
            except Exception as e:
                print(f"  {ct}: cannot plan ladder ({e})")
                continue
            for s in legs:
                st = cache_state(cache, s)
                if st == "data":
                    continue
                if st == "no_data" and a.no_force:
                    continue
                planned.append(s)
        if a.mode == "probe":
            # Smallest useful unit first: the legs nearest the CURRENT forward.
            # A probe that spends its budget on the far wing proves nothing --
            # deep-OTM legs settle at the 0.0025 minimum tick and carry no vol.
            planned.sort(key=lambda s: _distance_from_forward(cache, s))
            planned = planned[:max(0, a.plan_limit if a.plan_limit else a.max_calls)]
        print(f"plan: {len(planned)} leg(s) to fetch, cap {a.max_calls} HTTP calls")
        if a.dry_run:
            for s in planned:
                print(f"   {s}  [{cache_state(cache, s)}]")
            return 0
        if len(planned) > a.max_calls:
            print(f"ABORT: plan needs ~{len(planned)} calls > cap {a.max_calls}. "
                  f"Raise --max-calls deliberately.")
            return 2
        if not planned:
            print("nothing to fetch (all planned legs already have data)")

        before = {s: cache_state(cache, s) for s in planned}
        from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP  # noqa: E402
        with contextlib.redirect_stdout(_SINK):
            mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
        tnet = time.time()
        with NetGuard(a.max_calls, block=False) as guard:
            try:
                fetch_legs(mdp, planned, force=not a.no_force, pause=a.pause)
            except Exception as e:
                print(f"fetch stopped: {type(e).__name__}: {e}")
            net["http_calls"] = guard.n
            net["sample_urls"] = guard.urls[:5]
        net["wall_s"] = round(time.time() - tnet, 2)
        cache = _cache()
        after = {s: cache_state(cache, s) for s in planned}
        healed = [s for s in planned if before[s] != "data" and after[s] == "data"]
        net["fetched"] = len(planned)
        net["now_data"] = len(healed)
        net["healed_from_no_data"] = sum(1 for s in healed if before[s] == "no_data")
        net["per_call_s"] = round(net["wall_s"] / max(guard.n, 1), 3)
        print(f"\nHTTP calls {guard.n} in {net['wall_s']}s ({net['per_call_s']}s/call); "
              f"{len(healed)}/{len(planned)} legs now have data "
              f"({net['healed_from_no_data']} healed from no_data)")
        for s in healed[:15]:
            f = cached_frame(cache, s)
            print(f"   HEALED {s:<18} {before[s]:>8} -> data  n={len(f)} "
                  f"{str(f.index.min())[:10]}..{str(f.index.max())[:10]}")

    print(f"\nbuilding panel from cache ({a.mode}, df_rate={a.df_rate:.2%}):")
    panel, cov = build_panel(cache, all_contracts, a.df_rate)
    if panel.empty:
        print("no panel rows")
        return 1

    panel.to_parquet(PANEL, index=False)
    COVERAGE.write_text(json.dumps({"contracts": cov, "network": net,
                                    "df_rate": a.df_rate,
                                    "generated": datetime.datetime.now().isoformat(timespec="seconds")},
                                   indent=1), encoding="utf-8")
    print(f"\nwrote {PANEL}  rows={len(panel):,}  contracts={panel['contract'].nunique()}  "
          f"({time.time()-t0:.0f}s)")
    print(f"wrote {COVERAGE}")

    mc = panel[panel["is_midcurve"]]
    std = panel[~panel["is_midcurve"]]
    if not mc.empty and not std.empty:
        print("\nmid-curve vs same-expiry standard:")
        for ct in sorted(mc["contract"].unique()):
            sub = mc[mc["contract"] == ct]
            exp = sub["expiry"].iloc[0]
            peer = std[(std["expiry"] == exp)]
            if peer.empty:
                print(f"  {ct}: median {sub['atm_bpvol'].median():.2f} bp/yr (no same-expiry control)")
                continue
            j = sub.merge(peer, on="date", suffixes=("_mc", "_std"))
            if j.empty:
                continue
            print(f"  {ct} vs {peer['contract'].iloc[0]} ({len(j)} common days): "
                  f"midcurve {j['atm_bpvol_mc'].median():.2f} / standard "
                  f"{j['atm_bpvol_std'].median():.2f} bp/yr = "
                  f"ratio {(j['atm_bpvol_mc']/j['atm_bpvol_std']).median():.3f}, "
                  f"corr {j['atm_bpvol_mc'].corr(j['atm_bpvol_std']):.3f}")

    if a.verify:
        return 1 if verify(panel) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
