"""SR3 listed-butterfly HISTORY availability probe (ledger L-0002 / L-0043 item 2).

A DATA PROBE, not a study. One question: does any feed this repo already reaches
serve **exchange-listed** SR3 spread/butterfly instruments *historically*? The
2026-08-07 MBO day measured the listed butterfly at a 0.506 bp round trip against
the 2.0 bp the STIR labs were killed at; re-costing those labs needs the listed
instrument's history, and one MBO day is not history.

Routes considered, and why this script probes the one it does:

* **Databento GLBX.MDP3** — the source of the one measured day. ``databento``
  0.83.0 is installed but no ``DATABENTO_API_KEY`` is set anywhere reachable
  (env, ``.env``, ``~/.databento``), and the only local file is
  ``C:/Users/chris/Downloads/glbx-mdp3-20260715.mbo.dbn.zst``. The historical API
  is therefore not reachable without the user. Recorded, not probed.
* **Barchart** — reachable today through ``MDP/STIRFutures/BARCHART``. Its EOD
  endpoint takes an arbitrary symbol string, so the question reduces to: is there
  a symbol encoding under which Barchart serves CME's listed spread instruments?
  That is what this probes.

Throttling: the recorded 429-storm incident (``project_stirf_mix23_barchart_ratelimit``)
came from the *intraday* fetcher running unthrottled and 429-blind. This probe is
EOD only, strictly sequential, one request per ``SLEEP_S`` seconds, and fewer than
a dozen requests total.

Run:  C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/sr3_listed_bf_history_probe.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import json
import pathlib
import sys
import time

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
SLEEP_S = 3.0
START = datetime.datetime(2026, 1, 2)
END = datetime.datetime(2026, 8, 7)

# Barchart maps SR3 -> SQ (BarchartFetcher._STIR_ROOT_TO_BARCHART). Two kinds of
# control, because a probe with only a positive control cannot tell "this symbol
# is wrong" from "this endpoint has no spreads":
#   * outright control  — the probe works at all (must return dated rows);
#   * CL calendar control — the most heavily traded listed calendar on any US
#     futures exchange. If Barchart's EOD endpoint served exchange-listed spread
#     instruments under ANY encoding, this is the one it would serve.
CANDIDATES = [
    ("outright control", "SQZ26"),
    ("outright control 2", "SQH27"),
    ("calendar dash", "SQZ26-SQH27"),
    ("calendar underscore", "SQZ26_SQH27"),
    ("calendar concat", "SQZ26H27"),
    ("calendar cme root", "SR3Z26-SR3H27"),
    ("butterfly dash", "SQZ26-SQH27-SQM27"),
    ("butterfly cme native", "SR3:BF Z6-H7-M7"),
    ("butterfly cme compact", "SR3BFZ6H7M7"),
    ("xproduct calendar control", "CLF27-CLG27"),
    ("xproduct calendar control 2", "CLF27_CLG27"),
]

#: Barchart answers an unknown symbol with HTTP 200 and a one-row body reading
#: ``Error: invalid symbol`` — which a naive ``len(df) > 0`` test scores as a HIT.
#: The first run of this probe did exactly that and reported all seven spread
#: encodings "served", i.e. the defect flattered the high-value outcome, on cue.
#: A row only counts if it carries a parsed DATE.
_ERROR_MARKER = "error"


def probe_one(fetcher, label: str, symbol: str) -> dict:
    """One EOD request. Never raises — a failure is a recorded result."""
    row = {"label": label, "symbol": symbol, "n_rows": 0, "n_dated_rows": 0,
           "first": None, "last": None, "served": False, "body": None,
           "error": None}
    try:
        out = fetcher.barchart_timeseries_api(
            [symbol], START, END, interval=None,
            max_concurrent_tasks=1, max_keepalive_connections=1,
            max_requests_per_second=1, show_tqdm=False,
        )
        df = None
        if isinstance(out, dict):
            df = next(iter(out.values()), None)
        elif isinstance(out, pd.DataFrame):
            df = out
        if df is not None and len(df):
            row["n_rows"] = int(len(df))
            row["body"] = str(df.iloc[0].to_dict())[:160]
            if isinstance(df.index, pd.DatetimeIndex):
                dates = df.index
            elif "Date" in df.columns:
                dates = pd.DatetimeIndex(pd.to_datetime(df["Date"], errors="coerce"))
            else:
                dates = pd.DatetimeIndex([])
            dates = dates[~pd.isna(dates)]
            row["n_dated_rows"] = int(len(dates))
            if len(dates):
                row["first"], row["last"] = str(dates.min().date()), str(dates.max().date())
            body_txt = " ".join(str(v) for v in df.iloc[0].tolist()).lower()
            row["served"] = bool(len(dates) > 0 and _ERROR_MARKER not in body_txt)
    except Exception as exc:  # noqa: BLE001 — a failing candidate is data
        row["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return row


def main() -> None:
    from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher

    fetcher = BarchartFetcher(global_timeout=30)
    rows = []
    for label, symbol in CANDIDATES:
        r = probe_one(fetcher, label, symbol)
        rows.append(r)
        print(f"{label:28s} {symbol:22s} rows={r['n_rows']:5d} dated={r['n_dated_rows']:5d} "
              f"served={r['served']!s:5s} {r['first']}..{r['last']} "
              f"{r['body'] or ''} {r['error'] or ''}", flush=True)
        time.sleep(SLEEP_S)
    fetcher.close()

    df = pd.DataFrame(rows)
    control_ok = bool(df[df["label"].str.startswith("outright")]["served"].any())
    spread_hits = df[(~df["label"].str.startswith("outright")) & df["served"]]
    verdict = {
        "probe": "SR3 listed spread/butterfly history availability, Barchart EOD",
        "window": f"{START.date()}..{END.date()}",
        "control_outright_served": control_ok,
        "n_candidates": int(len(df)),
        "spread_encodings_served": spread_hits["symbol"].tolist(),
        "xproduct_control_served": bool(
            df[df["label"].str.startswith("xproduct")]["served"].any()),
        "databento_reachable": False,
        "databento_note": ("databento 0.83.0 installed; no DATABENTO_API_KEY in env, "
                           ".env or ~/.databento; only local file is the single "
                           "2026-07-15 GLBX MBO day"),
        "conclusion": ("listed-spread history AVAILABLE via Barchart"
                       if len(spread_hits) else
                       "no Barchart encoding serves any exchange-listed spread "
                       "instrument (the CL calendar control fails identically); "
                       "listed-BF history NOT reachable from local feeds"),
    }
    assert control_ok, "outright control failed - the probe is broken, not the data"
    DATA.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DATA / "sr3_bf_history_probe.parquet")
    (DATA / "sr3_bf_history_probe.json").write_text(json.dumps(verdict, indent=1))
    print(json.dumps(verdict, indent=1))


if __name__ == "__main__":
    main()
