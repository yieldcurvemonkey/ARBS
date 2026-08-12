"""Settle the three unverified cross-currency conventions against market facts.

``MDP/CitiVelocityExcel/xccy/basis_data.py`` records three things it cannot check without a live
add-in and a market cross-check: which currency ``SPREAD_LEG`` denotes, which currency the swap is
assumed collateralised in, and **the sign**. Until they are settled a basis RV book's *direction*
is unproven — signal 1 is ``-(fwd - rolled)``, so a flipped sign inverts the whole strategy.

This settles them by asking the data questions whose answers are known independently of it:

1. **Level.** The EUR/USD and USD/JPY cross-currency bases have been persistently **negative** for
   over a decade — non-USD holders pay to borrow dollars. A 5y EUR/USD basis of about −20bp and a
   5y USD/JPY around −40bp are the textbook figures. If the wire returns positive numbers of that
   magnitude, the sign is inverted.
2. **Crisis fingerprint.** The basis blows out sharply *more negative* in a dollar funding squeeze.
   Two dated events are unambiguous: the post-Lehman quarter (Sep-Dec 2008) and March 2020. A
   series that spikes *positive* on those dates has the sign backwards. This is the strongest test
   because it does not depend on remembering a level.
3. **Which leg carries the spread.** A cross-currency swap quotes the basis on one leg and leaves
   the other flat. Whichever of ``BASE_LEG`` / ``SPREAD_LEG`` is materially non-zero is the one
   that carries it; if both are non-zero and differ, the convention is not what the module assumes.

Run it with Excel up and the Velocity add-in signed in::

    conda run -n stir python scripts/settle_xccy_conventions.py

It prints a verdict per test and an overall recommendation for ``CitiXccySource(sign=...)``.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("settle_xccy")

from BT.xccy_rv.data import xccy_basis_tag  # noqa: E402

#: Dollar-funding squeezes. The basis must move sharply NEGATIVE in these windows.
STRESS_WINDOWS = [
    ("post-Lehman", "2008-09-15", "2008-12-31"),
    ("COVID", "2020-03-01", "2020-04-15"),
]

#: (pair, tenor, expected sign, rough magnitude in bp) — the textbook figures.
LEVEL_EXPECTATIONS = [
    (("EUR", "USD"), "5Y", -1, 20.0),
    (("USD", "JPY"), "5Y", -1, 40.0),
    (("GBP", "USD"), "5Y", -1, 10.0),
]


def _fetch(quotes, tags, start, end):
    try:
        return quotes.frame(sorted(set(tags)), "DAILY", start=start, end=end)
    except Exception as exc:  # noqa: BLE001
        logger.error("fetch failed: %s: %s", type(exc).__name__, exc)
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2006-01-01")
    ap.add_argument("--end", default=str(datetime.date.today()))
    args = ap.parse_args()

    try:
        from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

        quotes = CitiVeloQuotes()
    except Exception as exc:  # noqa: BLE001
        logger.error("Velocity bridge unavailable: %s: %s", type(exc).__name__, exc)
        return 2

    verdicts = {}

    # ---------------------------------------------------------------- depth
    probe_tag = xccy_basis_tag("EUR", "USD", "5Y", "SPOT")
    logger.info("=== 0. DEPTH: %s ===", probe_tag)
    df = _fetch(quotes, [probe_tag], args.start, args.end)
    if df is None or df.empty or probe_tag not in df.columns:
        logger.error("no rows returned — the family may not serve on this entitlement")
        return 1
    s = df[probe_tag].dropna()
    logger.info("  %d rows, %s .. %s", len(s), s.index.min().date(), s.index.max().date())
    logger.info("  last %.2f | median %.2f | min %.2f | max %.2f", s.iloc[-1], s.median(), s.min(), s.max())

    # ------------------------------------------------------- 1. LEVEL / SIGN
    logger.info("=== 1. LEVEL: the basis is persistently negative for non-USD vs USD ===")
    tags = {p: xccy_basis_tag(p[0], p[1], t, "SPOT") for p, t, _, _ in LEVEL_EXPECTATIONS}
    lv = _fetch(quotes, list(tags.values()), args.start, args.end)
    level_votes = []
    for (pair, tenor, want_sign, mag) in LEVEL_EXPECTATIONS:
        tag = tags[pair]
        if lv is None or tag not in lv.columns:
            logger.warning("  %s/%s %s: no data", pair[0], pair[1], tenor)
            continue
        ser = lv[tag].dropna()
        if ser.empty:
            logger.warning("  %s/%s %s: empty", pair[0], pair[1], tenor)
            continue
        med = float(ser.median())
        got_sign = int(np.sign(med)) or 1
        ok = got_sign == want_sign
        level_votes.append(ok)
        logger.info(
            "  %s/%s %s: median %+7.2f bp (expected %s, order %gbp) -> %s",
            pair[0], pair[1], tenor, med, "negative" if want_sign < 0 else "positive", mag,
            "MATCHES" if ok else "INVERTED",
        )
    verdicts["level"] = (
        "matches" if level_votes and all(level_votes)
        else "inverted" if level_votes and not any(level_votes)
        else "inconclusive"
    )

    # -------------------------------------------------- 2. CRISIS FINGERPRINT
    logger.info("=== 2. CRISIS: a dollar squeeze drives the basis sharply MORE NEGATIVE ===")
    crisis_votes = []
    tag = tags[("EUR", "USD")]
    if lv is not None and tag in lv.columns:
        ser = lv[tag].dropna()
        for name, lo, hi in STRESS_WINDOWS:
            win = ser.loc[lo:hi]
            pre = ser.loc[: pd.Timestamp(lo)].tail(60)
            if len(win) < 5 or len(pre) < 5:
                logger.info("  %s: not covered by this history", name)
                continue
            move = float(win.min() - pre.median()) if True else 0.0
            # A squeeze should push the EXTREME away from the pre-window level, downward.
            extreme = float(win.min()) if abs(win.min() - pre.median()) > abs(win.max() - pre.median()) else float(win.max())
            direction = extreme - float(pre.median())
            ok = direction < 0
            crisis_votes.append(ok)
            logger.info(
                "  %s: pre-window median %+7.2f -> extreme %+7.2f (move %+7.2f bp) -> %s",
                name, float(pre.median()), extreme, direction,
                "MATCHES (widened negative)" if ok else "INVERTED (widened positive)",
            )
    verdicts["crisis"] = (
        "matches" if crisis_votes and all(crisis_votes)
        else "inverted" if crisis_votes and not any(crisis_votes)
        else "inconclusive"
    )

    # ------------------------------------------------------------ 3. WHICH LEG
    logger.info("=== 3. LEG: which of BASE_LEG / SPREAD_LEG actually carries the basis ===")
    base_tag = xccy_basis_tag("EUR", "USD", "5Y", "SPOT", leg="BASE_LEG")
    spread_tag = xccy_basis_tag("EUR", "USD", "5Y", "SPOT", leg="SPREAD_LEG")
    lg = _fetch(quotes, [base_tag, spread_tag], args.start, args.end)
    if lg is not None:
        for name, t in (("BASE_LEG", base_tag), ("SPREAD_LEG", spread_tag)):
            if t not in lg.columns:
                logger.info("  %s: absent", name)
                continue
            ser = lg[t].dropna()
            logger.info("  %-11s n=%5d  median %+7.2f  |median| %.2f  sd %.2f",
                        name, len(ser), ser.median(), abs(ser.median()), ser.std())
        if base_tag in lg.columns and spread_tag in lg.columns:
            b, sp = lg[base_tag].dropna(), lg[spread_tag].dropna()
            if not b.empty and not sp.empty:
                if abs(b.median()) < 0.5 and abs(sp.median()) > 1.0:
                    verdicts["leg"] = "SPREAD_LEG carries it (BASE_LEG is flat) — module default is right"
                elif abs(sp.median()) < 0.5 and abs(b.median()) > 1.0:
                    verdicts["leg"] = "BASE_LEG carries it — the module default is WRONG"
                else:
                    verdicts["leg"] = "both legs non-trivial — convention not as assumed, inspect by hand"
                logger.info("  -> %s", verdicts["leg"])

    # ------------------------------------------------------------- VERDICT
    logger.info("=== VERDICT ===")
    for k, v in verdicts.items():
        logger.info("  %-8s %s", k, v)

    sign_tests = [verdicts.get("level"), verdicts.get("crisis")]
    if all(v == "matches" for v in sign_tests if v):
        logger.info("  => use CitiXccySource(sign=+1). The wire agrees with the market convention.")
        rc = 0
    elif all(v == "inverted" for v in sign_tests if v):
        logger.info("  => use CitiXccySource(sign=-1). The wire signs the basis the other way.")
        rc = 0
    else:
        logger.warning("  => INCONCLUSIVE. Do not trade the direction on this evidence.")
        rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
