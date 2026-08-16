"""Harvest REAL LISTED option contracts (not constant maturity) from QuikStrike.

Why this exists
---------------
``scripts/harvest_ust_listed_vol.py`` pulled the CONSTANT-MATURITY panel
(``US_30`` = QuikStrike's interpolation across the expiry ladder). That panel is
not tradeable: it has no strike dimension and no expiry, so it cannot size a
straddle whose premium equals the curve carry (the JPM framework needs a real
contract with a real expiry, strike and premium) and it cannot support an
expected-payoff signal (which needs OTM quotes). This job replaces it with the
actual listed contracts -- ``USM26``, ``TYZ25``, ``SFRH27`` -- each carrying its
own **expiry date** and therefore its own **time to expiry**, which is the whole
point of moving off constant maturity.

The CM panel is NOT superseded. It is the control: a real contract at 30 days to
expiry should reproduce ``US_30``, and the two diverging as the contract ages is
exactly the term-structure information CM was interpolating away.

One call per contract-life, not one per year
---------------------------------------------
``harvest_ust_listed_vol.py`` chunks by year because a constant-maturity series
runs the full 2019-2026 window. A listed contract does not: it is quoted for a
few months (UST) to a few years (SFR) and then it is gone. Asking for the whole
window in ONE call therefore returns the contract's entire life and costs FEWER
requests than year-chunking, not more.

That shortcut was verified before it was relied on, because a silently truncated
series would look exactly like a short-lived contract (``scratchpad/probe3.py``,
measured):

    USM26  ABPV  full window 1 call -> 152 rows | 2 yearly chunks -> 152 rows
                 common 152, only-in-full 0, only-in-chunked 0, max|diff| 0.0
    SFRM26 ABPV  full window 1 call -> 938 rows | 8 yearly chunks -> 938 rows
                 common 938, only-in-full 0, only-in-chunked 0, max|diff| 0.0

Contract universe and expiry
----------------------------
Built from the repo's own contract machinery, never from hand-rolled month codes:

* UST -- ``definitions/USTFutureOptions.option_expiry_date`` (CME monthly rule:
  last Friday at least two business days before the last business day of the
  month PRECEDING the contract month).
* SFR -- ``MDP.STIRFutures._sofr_option_contracts.sofr_option_last_trade_date``
  (CME 460A01.J.1: the Friday preceding the third Wednesday, rolled back on a
  government-bond-calendar holiday). Deliberately NOT
  ``quarterly_contract_expiry_date``, which is the underlying future's IMM date
  five days LATER and would overstate every time to expiry by a week.

Both were tied out against the vendor's own last quote date before the harvest
(measured, every case last-quote == expiry - 1 business day)::

    USM26  2026-05-22 vs last quote 2026-05-21    USJ26  2026-03-27 vs 2026-03-26
    USZ19  2019-11-22 vs last quote 2019-11-21    TYF26  2025-12-26 vs 2025-12-24
    USH19  2019-02-22 vs last quote 2019-02-21    SFRM26 2026-06-12 vs 2026-06-11

so ``last_vs_expiry_days`` is recorded per series and a violation is reported as
coverage data rather than silently accepted.

Roots
-----
UST ``US`` (30y bond) and ``TY`` (10y) -- the two proven reachable as listed
tokens. ``UL``/``TN`` (Ultra Bond, Ultra 10y) raise "Invalid UST option contract
token" on this endpoint and exist only as constant maturity. SFR quarterlies are
reached as ``SFR*``; the vendor answers on the ``SR3*`` alias and the column
comes back named ``SR3M26 ABPV``, which is why ``contract_code`` is normalised to
the repo's canonical ``SFRM26`` and the vendor's token kept beside it as
``vendor_symbol``.

**Midcurves are not harvested and must not be.** A bare midcurve root raises, and
``root_globex="S0"`` SILENTLY RETURNS THE STANDARD SR3 SERIES -- S0, S2 and S3 all
returned the identical ``SR3M26`` column. A midcurve hint on this endpoint cannot
be trusted, so none is used.

Value types
-----------
``ABPV`` and ``ATM``, plus the 25-delta smile set. The smile ``qv_value_type``
tokens are ambiguous on their own (bare ``"Call"`` says nothing about the delta),
so the panel stores self-describing labels ``25D_CALL``, ``25D_PUT``, ``25D_RR``,
``25D_BF`` and the request parameters live in :data:`VALUE_TYPES`.

Units are NOT converted here. Values are stored exactly as quoted, because a
conversion baked into the parquet cannot be audited afterwards. See
``RVUtils/ConvexityRV/listed_contracts.py`` for the measured units verdict and
the conversion helpers.

Behaviour: resumable (skips series already on disk AND empties already recorded,
so a resume does not refetch known blanks), rate-limited, write-through after
every series, and failures recorded as data rather than dropped.

Usage::

    conda run -n stir python scripts/harvest_listed_contract_vol.py --dry-run
    conda run -n stir python scripts/harvest_listed_contract_vol.py
    conda run -n stir python scripts/harvest_listed_contract_vol.py --roots US --no-serial
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import io
import json
import logging
import os
import pathlib
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

OUT_DIR = REPO / "notebooks" / "data" / "convexity_rv"
PANEL = OUT_DIR / "listed_contract_vol.parquet"
COVERAGE = OUT_DIR / "listed_contract_vol_coverage.json"

#: UST option roots reachable as listed tokens on ``qs_timeseries``. UL and TN
#: are NOT here on purpose: both raise "Invalid UST option contract token".
UST_ROOTS = ["US", "TY"]

#: SFR quarterly root. The vendor also answers to SR3/SQ; SFR is the repo's
#: canonical form and what ``_sofr_option_contracts`` parses.
SFR_ROOTS = ["SFR"]

QUARTERLY_MONTH_CODES = ["H", "M", "U", "Z"]
ALL_MONTH_CODES = ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"]

#: label -> extra query parameters merged into ``{"globex_symbol": ...}``.
#: The label is what lands in the parquet's ``value_type``; it is deliberately
#: self-describing because ``qv_value_type="Call"`` alone loses the delta.
VALUE_TYPES: Dict[str, Dict[str, Any]] = {
    "ABPV":     {"qv_value_type": "ABPV"},
    "ATM":      {"qv_value_type": "ATM"},
    "25D_CALL": {"qv_value_type": "Call", "delta": 25, "option_type": "Call"},
    "25D_PUT":  {"qv_value_type": "Put", "delta": 25, "option_type": "Put"},
    "25D_RR":   {"qv_value_type": "RiskReversal", "delta": 25},
    "25D_BF":   {"qv_value_type": "Butterfly", "delta": 25},
}

#: ACT/365, matching ``load_sfr_contracts``' own ``tte`` convention so the two
#: panels' times to expiry are directly comparable.
DAYS_PER_YEAR = 365.0

_SINK = io.StringIO()


# --------------------------------------------------------------- the universe


def ust_expiry(contract_code: str) -> datetime.date:
    """Option expiry (last trading day) for a UST futures option contract.

    CME: "the last Friday which precedes by at least two business days the last
    business day of the month preceding the option contract month."

    This uses the repo's own contract parsing
    (``definitions.USTFutureOptions.parse_option_contract``) but **not** its
    ``option_expiry_date``, which resolves "business day" as Monday-to-Friday and
    therefore ignores exchange holidays. That is a real defect, not a nuance, and
    it was caught by the harvest's own tie-out against the vendor's last quote
    date:

    ==========  ==============  ==============  ===========================
    contract    repo rule       correct         evidence
    ==========  ==============  ==============  ===========================
    USM22       2022-05-27      2022-05-20      Memorial Day 2022-05-30 is
    TYM22       2022-05-27      2022-05-20      counted as a business day;
                                                last quote 2022-05-19, which
                                                is 1 bd before 05-20 and
                                                6 bd before 05-27
    USF21       2020-12-25      2020-12-18      the repo rule returns
                                                CHRISTMAS DAY as an expiry
    ==========  ==============  ==============  ===========================

    Everything else agrees, so the correction touches only the holiday cases.
    ``ust_expiry_legacy`` is kept so the difference stays measurable, and
    :func:`expiry_rule_disagreements` enumerates it across the universe.

    The calendar is the US **government bond** calendar rather than NYSE, for the
    same reason ``_sofr_option_contracts`` uses it: these are US Treasury
    products and it is the Treasury market's holiday schedule that closes them.
    """
    import QuantLib as ql
    from definitions.USTFutureOptions import MONTH_CODE_TO_NUM, parse_option_contract

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    _, code = parse_option_contract(contract_code)
    month = MONTH_CODE_TO_NUM[code[0]]
    year = 2000 + int(code[1:])
    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)

    last_bd = cal.adjust(ql.Date.endOfMonth(ql.Date(1, prev_month, prev_year)), ql.Preceding)
    cutoff = cal.advance(last_bd, ql.Period(-2, ql.Days))
    d = datetime.date(cutoff.year(), cutoff.month(), cutoff.dayOfMonth())
    while d.weekday() != 4:                       # the last Friday on or before it
        d -= datetime.timedelta(days=1)
    # "If such Friday is not a business day, trading terminates on the PRIOR
    # BUSINESS DAY" -- one day back, not back to the previous Friday. Getting
    # this wrong moves the January serials a whole week: the first version of
    # this function looped to the previous Friday and put USF21 on 2020-12-18,
    # whereupon the panel's last quote (2020-12-23) sat AFTER its own expiry --
    # a negative time to expiry, which is how the error announced itself.
    adj = cal.adjust(ql.Date(d.day, d.month, d.year), ql.Preceding)
    return datetime.date(adj.year(), adj.month(), adj.dayOfMonth())


def ust_expiry_legacy(contract_code: str) -> datetime.date:
    """The repo's weekday-only rule, kept so the correction stays measurable."""
    from definitions.USTFutureOptions import option_expiry_date
    return option_expiry_date(contract_code)


def expiry_rule_disagreements(contracts: List[str]) -> List[Dict[str, Any]]:
    """Where :func:`ust_expiry` and the repo's rule differ, as data."""
    out: List[Dict[str, Any]] = []
    for c in contracts:
        try:
            a, b = ust_expiry(c), ust_expiry_legacy(c)
        except Exception:
            continue
        if a != b:
            out.append({"contract_code": c, "corrected": a.isoformat(),
                        "repo_rule": b.isoformat(), "days": (b - a).days})
    return out


def sfr_expiry(contract_code: str) -> datetime.date:
    """Option expiry (last trading day) for a SOFR quarterly option contract."""
    from MDP.STIRFutures._sofr_option_contracts import sofr_option_last_trade_date
    out = sofr_option_last_trade_date(contract_code)
    if out is None:
        raise ValueError(f"no SOFR option expiry rule for {contract_code}")
    return out


def build_universe(
    *,
    ust_roots: List[str],
    sfr_roots: List[str],
    first_expiry: datetime.date,
    ust_last_expiry: datetime.date,
    sfr_last_expiry: datetime.date,
    include_serial: bool,
) -> List[Dict[str, Any]]:
    """Every contract whose OPTION EXPIRY falls in the per-asset expiry window.

    Selection is on the option's expiry, not on the contract month, because the
    expiry is the only date that decides whether the contract was ever quoted
    inside the harvest window.

    The two asset classes need very different forward horizons and using one
    number for both wastes hundreds of calls on guaranteed blanks. Measured
    listing leads over the finished panel -- first quote to expiry:

    =====  ==================  =========  ==================================
    root   median lead         max lead   note
    =====  ==================  =========  ==================================
    US     122 d (~4 months)     241 d    serials print latest, quarterlies
    TY     127 d (~4 months)     241 d    earliest; 241 d is ~7.9 months
    SFR   1124 d (~3.1 years)   1458 d    SR3 options list years ahead
    =====  ==================  =========  ==================================

    So the UST horizon is a few months past the harvest end -- comfortably past
    the 241-day maximum, and far enough to include the empty contracts that
    document where listing stops -- while the SFR horizon runs to 2031, because
    contracts expiring in 2029 are quoted TODAY and the far ladder needs them.

    Quarterlies are emitted first for both asset classes and serials afterwards,
    so a run that is cut short still leaves the mandated quarterly panel whole --
    the write-through happens after every series.
    """
    out: List[Dict[str, Any]] = []
    last_by_asset = {"UST": ust_last_expiry, "SFR": sfr_last_expiry}

    def add(root: str, code: str, kind: str, expiry: datetime.date, asset: str) -> None:
        if not (first_expiry <= expiry <= last_by_asset[asset]):
            return
        out.append({
            "contract_code": f"{root}{code}",
            "root": root,
            "asset": asset,
            "contract_kind": kind,
            "expiry_date": expiry,
        })

    years = range(first_expiry.year - 1, max(ust_last_expiry.year, sfr_last_expiry.year) + 2)

    # -- pass 1: quarterlies (the mandate)
    for root in ust_roots:
        for y in years:
            for mc in QUARTERLY_MONTH_CODES:
                code = f"{mc}{y % 100:02d}"
                try:
                    add(root, code, "quarterly", ust_expiry(f"{root}{code}"), "UST")
                except Exception:
                    continue
    for root in sfr_roots:
        for y in years:
            for mc in QUARTERLY_MONTH_CODES:
                code = f"{mc}{y % 100:02d}"
                try:
                    add(root, code, "quarterly", sfr_expiry(f"{root}{code}"), "SFR")
                except Exception:
                    continue

    # -- pass 2: UST serial months. Not the mandate, but without them the listed
    #    expiry ladder has only ~2 live UST points per date and the 30-day
    #    matched comparison against the CM panel exists once a quarter instead of
    #    once a month. SFR serials are excluded: the SFR ladder is already dense.
    if include_serial:
        serial_codes = [mc for mc in ALL_MONTH_CODES if mc not in QUARTERLY_MONTH_CODES]
        for root in ust_roots:
            for y in years:
                for mc in serial_codes:
                    code = f"{mc}{y % 100:02d}"
                    try:
                        add(root, code, "serial", ust_expiry(f"{root}{code}"), "UST")
                    except Exception:
                        continue

    return out


# ------------------------------------------------------------------- fetching


def fetch_series(
    mdp,
    symbol: str,
    label: str,
    start: datetime.date,
    end: datetime.date,
    *,
    pause: float = 0.4,
) -> Tuple[Optional[pd.DataFrame], str]:
    """One (contract, value_type) series over [start, end] in a single call.

    Returns ``(df, note)``. ``df`` is None for an empty or failed series; the
    note carries the reason so the coverage file can distinguish "the contract
    was never listed" from "the request was rejected".
    """
    q = {"globex_symbol": symbol}
    q.update(VALUE_TYPES[label])
    req = {"endpoint": "qs_timeseries", "start": start, "end": end, "queries": [q]}
    try:
        with contextlib.redirect_stdout(_SINK), contextlib.redirect_stderr(_SINK):
            out = mdp.get_data(req)
        ts = (out or {}).get("qs_timeseries") or []
        if ts and isinstance(ts[0], pd.DataFrame) and not ts[0].empty:
            return ts[0], "ok"
        return None, "empty"
    except Exception as e:  # noqa: BLE001 - a rejected token is data, not a crash
        return None, f"{type(e).__name__}: {str(e)[:80]}"
    finally:
        time.sleep(pause)


def _business_days_between(a: datetime.date, b: datetime.date) -> int:
    return int(len(pd.bdate_range(min(a, b), max(a, b)))) - 1


def _atomic_write(df: pd.DataFrame, path: pathlib.Path) -> None:
    """Write the panel via a temp file and ``os.replace``.

    The panel is rewritten after EVERY series (write-through, so a kill costs one
    series), which means a reader has ~1,500 chances to catch a half-written
    file. ``to_parquet`` truncates in place, and a reader landing in that window
    gets ``ArrowInvalid: Parquet magic bytes not found`` -- observed while the
    test suite ran against this file mid-harvest. ``os.replace`` is atomic on
    the same volume, so a concurrent reader sees either the old panel or the new
    one and never a torn one.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def _atomic_write_text(text: str, path: pathlib.Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def repair_expiries(panel: pd.DataFrame) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """Recompute ``expiry_date`` and ``tte_years`` from the CURRENT expiry rules.

    The panel is written incrementally across a long run and can be resumed days
    later, so rows can be stamped with an expiry rule that has since been
    corrected -- which is exactly what happened here when the UST holiday bug
    surfaced mid-harvest. Rather than leave the parquet as a mix of two vintages,
    every row's expiry is re-derived from the code on the way out. The rule is a
    pure function of the contract code, so this is idempotent and costs no
    network.

    Returns the repaired panel and the list of contracts whose expiry moved.
    """
    if panel.empty:
        return panel, []
    df = panel.copy()
    changes: List[Dict[str, Any]] = []
    fixed: Dict[str, pd.Timestamp] = {}
    for (code, asset), old in df.groupby(["contract_code", "asset"])["expiry_date"].first().items():
        try:
            want = pd.Timestamp(ust_expiry(code) if asset == "UST" else sfr_expiry(code))
        except Exception:
            continue
        fixed[code] = want
        if want != pd.Timestamp(old):
            changes.append({"contract_code": code, "was": str(pd.Timestamp(old).date()),
                            "now": str(want.date()),
                            "shift_days": int((pd.Timestamp(old) - want).days)})
    if fixed:
        df["expiry_date"] = df["contract_code"].map(fixed).fillna(df["expiry_date"])
        df["tte_years"] = (df["expiry_date"] - df["date"]).dt.days / DAYS_PER_YEAR
    return df, changes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ust-roots", nargs="*", default=UST_ROOTS)
    ap.add_argument("--sfr-roots", nargs="*", default=SFR_ROOTS)
    ap.add_argument("--value-types", nargs="*", default=list(VALUE_TYPES))
    ap.add_argument("--start", default="2019-01-01",
                    help="harvest window start; also the lower bound of each fetch")
    ap.add_argument("--end", default="2026-08-15", help="harvest window end")
    ap.add_argument("--ust-last-expiry", default=None,
                    help="default: end + 300 days. A UST option first prints ~7.2 "
                         "months before expiry, so anything further out is a "
                         "guaranteed blank; the buffer past that still records "
                         "where listing actually stops.")
    ap.add_argument("--sfr-last-expiry", default="2031-12-31",
                    help="SFR lists years out and those far contracts are quoted "
                         "TODAY, so the far ladder needs them")
    ap.add_argument("--no-serial", action="store_true",
                    help="quarterlies only (the mandated universe)")
    ap.add_argument("--pause", type=float, default=0.4)
    ap.add_argument("--force", action="store_true", help="refetch series already on disk")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    logging.disable(logging.WARNING)
    start = datetime.date.fromisoformat(a.start)
    end = datetime.date.fromisoformat(a.end)
    ust_last = (datetime.date.fromisoformat(a.ust_last_expiry) if a.ust_last_expiry
                else end + datetime.timedelta(days=300))
    sfr_last = datetime.date.fromisoformat(a.sfr_last_expiry)

    universe = build_universe(
        ust_roots=list(a.ust_roots),
        sfr_roots=list(a.sfr_roots),
        first_expiry=start,
        ust_last_expiry=ust_last,
        sfr_last_expiry=sfr_last,
        include_serial=not a.no_serial,
    )
    plan = [(c, vt) for c in universe for vt in a.value_types]
    print(f"universe: {len(universe)} contracts "
          f"({sum(1 for c in universe if c['contract_kind'] == 'quarterly')} quarterly, "
          f"{sum(1 for c in universe if c['contract_kind'] == 'serial')} serial)")
    for asset in ("UST", "SFR"):
        sub = [c for c in universe if c["asset"] == asset]
        if sub:
            print(f"  {asset}: {len(sub):>3} contracts, expiries "
                  f"{min(c['expiry_date'] for c in sub)} .. {max(c['expiry_date'] for c in sub)}")
    print(f"plan: {len(plan)} series, window {start} .. {end}, pause {a.pause}s")
    if a.dry_run:
        for c in universe[:20]:
            print(f"  {c['contract_code']:<8} {c['contract_kind']:<9} exp {c['expiry_date']}")
        print(f"  ... ({len(universe)} total)")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = pd.read_parquet(PANEL) if (PANEL.exists() and not a.force) else None
    cov: Dict[str, Dict] = {}
    if COVERAGE.exists() and not a.force:
        with contextlib.suppress(Exception):
            cov = json.loads(COVERAGE.read_text(encoding="utf-8"))

    have = set()
    if existing is not None and not existing.empty:
        have = set(map(tuple, existing[["contract_code", "value_type"]]
                       .drop_duplicates().values))
    # Empties are skipped on resume too, or every run refetches the known blanks
    # (the pre-2020 SFR contracts, which predate the SOFR option launch).
    known_empty = {tuple(k.split("|")) for k, v in cov.items() if int(v.get("n", 0)) == 0}
    if have or known_empty:
        print(f"resuming: {len(have)} series on disk, {len(known_empty)} known-empty")

    from MDP.USTFutures.USTFutureOptionMDP import USTFutureOptionMDP  # noqa: E402
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP  # noqa: E402

    with contextlib.redirect_stdout(_SINK), contextlib.redirect_stderr(_SINK):
        mdps = {
            "UST": USTFutureOptionMDP(source="USTFO_DUAL-QL"),
            "SFR": STIRFutureOptionMDP(source="STIRFO_DUAL-QL"),
        }

    rows: List[pd.DataFrame] = [existing] if existing is not None else []
    t_all = time.time()
    n_new = 0
    for i, (c, label) in enumerate(plan, 1):
        code = c["contract_code"]
        key = (code, label)
        if key in have or key in known_empty:
            continue
        # One call for the whole life: end at the expiry, since the contract
        # cannot be quoted after it.
        w_end = min(end, c["expiry_date"])
        if w_end < start:
            continue
        df, note = fetch_series(mdps[c["asset"]], code, label, start, w_end, pause=a.pause)
        if df is None or df.empty:
            print(f"[{i}/{len(plan)}] {code:<8} {label:<9} NONE  {note}")
            cov[f"{code}|{label}"] = {"n": 0, "note": note,
                                      "expiry": c["expiry_date"].isoformat()}
            _atomic_write_text(json.dumps(cov, indent=1), COVERAGE)
            continue

        col = str(df.columns[0])
        dates = pd.to_datetime(df.index)
        expiry = pd.Timestamp(c["expiry_date"])
        tidy = pd.DataFrame({
            "date": dates,
            "symbol": col.split(" ")[0],          # vendor token, e.g. "SR3M26"
            "vendor_column": col,
            "root": c["root"],
            "asset": c["asset"],
            "contract_code": code,                 # canonical, e.g. "SFRM26"
            "contract_kind": c["contract_kind"],
            "expiry_date": expiry,
            "tte_years": (expiry - dates).days / DAYS_PER_YEAR,
            "value_type": label,
            "value": pd.to_numeric(df[df.columns[0]], errors="coerce").to_numpy(),
        }).dropna(subset=["value"])
        if tidy.empty:
            cov[f"{code}|{label}"] = {"n": 0, "note": "all-nan",
                                      "expiry": c["expiry_date"].isoformat()}
            _atomic_write_text(json.dumps(cov, indent=1), COVERAGE)
            continue

        rows.append(tidy)
        n_new += 1
        last = tidy["date"].max().date()
        gap_bd = _business_days_between(last, c["expiry_date"])
        cov[f"{code}|{label}"] = {
            "n": int(len(tidy)),
            "root": c["root"],
            "asset": c["asset"],
            "kind": c["contract_kind"],
            "vendor_column": col,
            "expiry": c["expiry_date"].isoformat(),
            "first": str(tidy["date"].min().date()),
            "last": str(last),
            "last_vs_expiry_bd": int(gap_bd),
            "tte_first": float(tidy["tte_years"].max()),
            "tte_last": float(tidy["tte_years"].min()),
            "median": float(tidy["value"].median()),
            "note": note,
        }
        flag = "" if 0 <= gap_bd <= 3 else f"  *** last quote {gap_bd} bd before expiry"
        print(f"[{i}/{len(plan)}] {code:<8} {label:<9} {len(tidy):>4} rows "
              f"{tidy['date'].min():%Y-%m-%d}..{last} "
              f"tte {tidy['tte_years'].max():.2f}->{tidy['tte_years'].min():.3f}y "
              f"med {tidy['value'].median():.4f}{flag}")

        # Write through after every series so a kill costs one series.
        _atomic_write(pd.concat(rows, ignore_index=True), PANEL)
        _atomic_write_text(json.dumps(cov, indent=1), COVERAGE)

    if rows:
        panel = pd.concat(rows, ignore_index=True)
        panel, changed = repair_expiries(panel)
        if changed:
            print(f"\nexpiry repair: {len(changed)} contracts re-stamped from the "
                  f"current rule (a resumed run can carry an older vintage):")
            for c in changed[:10]:
                print(f"  {c['contract_code']:<8} {c['was']} -> {c['now']} "
                      f"({c['shift_days']:+d}d)")
        _atomic_write(panel, PANEL)
        print(f"\nwrote {PANEL}\n  rows={len(panel):,}  "
              f"series={panel.groupby(['contract_code', 'value_type']).ngroups}  "
              f"contracts={panel['contract_code'].nunique()}  "
              f"new this run={n_new}  ({time.time() - t_all:.0f}s)")
    _atomic_write_text(json.dumps(cov, indent=1), COVERAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
