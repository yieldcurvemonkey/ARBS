r"""Short, bounded live verification against a signed-in Citi Velocity add-in.

Run from the repo root::

    <env>/python.exe MDP/CitiVelocityExcel/harvest/verify_live.py

This settles the facts the hermetic suite CANNOT: the hermetic tests prove the
client is self-consistent against a fake built from the same understanding of the
add-in, which is exactly the kind of circularity a live probe breaks.

What it checks, in order:

1. the connect path against the real Running Object Table;
2. the two known-good control tags (nothing after this is trusted if they fail);
3. **the unit of the wire** for ``ATM_RFR.NORMAL`` - basis points or decimal.
   This is declared, not measured, everywhere else in the package;
4. a 44-tenor par grid in ONE ``CVTSHIST`` call, and whether the block parses;
5. **explicit start/end date bounds**, whose format is inferred from the add-in's
   own saved functions rather than confirmed against ``CVTSHIST``;
6. **``RATES.SWAP_LIBOR``**, whose shape has never been confirmed to serve data;
7. ``SWAP_SPREAD``, which ``CVMETADATA`` claims has zero valid tenors;
8. a real curve stripped from real quotes, repricing its own inputs.

It is DELIBERATELY SHORT - roughly a dozen ``CV*`` calls. It drives the user's own
Excel process, and the risk of a long unattended run is not worth the marginal
information. Do not add a sweep here; and never ``Stop-Process`` it mid-call,
which wedges the OLE server for ~15 minutes.
"""

from __future__ import annotations

import datetime
import pathlib
import sys
import traceback

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:  # probe script only; never in library code
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402

from MDP.CitiVelocityExcel import tags as T  # noqa: E402
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient  # noqa: E402

CONTROLS = (
    "RATES.OIS.USD_SOFR.PAR.10Y",
    "RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y",
)


def _rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    _rule("1. connect")
    try:
        client = CitiVelocityExcelClient.connect(attempts=1, readiness_timeout=120.0)
    except Exception as exc:  # noqa: BLE001 - the report IS the exception
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("connected")

    try:
        # -- 2. controls ------------------------------------------------
        _rule("2. control tags (nothing below is trusted if these fail)")
        verdicts = client.validate(list(CONTROLS), period="1M")
        for tag, verdict in verdicts.items():
            print(f"  {verdict:<10} {tag}")
        if any(v != "valid" for v in verdicts.values()):
            print("\nCONTROLS FAILED - refusing to report anything else.")
            return 2

        # -- 3. the unit of the wire ------------------------------------
        _rule("3. UNIT OF THE WIRE for ATM_RFR.NORMAL (declared 'bp' everywhere)")
        vol = client.fetch_timeseries([CONTROLS[1]], "DAILY", period="1M")[CONTROLS[1]]
        last = float(vol.iloc[-1])
        print(f"  {CONTROLS[1]}")
        print(f"  latest = {last!r}   ({len(vol)} rows, {vol.index[-1]:%Y-%m-%d})")
        if 10.0 <= last <= 400.0:
            print("  -> BASIS POINTS of annualised normal vol. served_unit='bp' is CORRECT.")
        elif 0.001 <= last <= 0.04:
            print("  -> DECIMAL. served_unit='bp' is WRONG; the vol layer must be told 'decimal'.")
        elif 1.0 <= last <= 10.0:
            print("  -> PERCENT. Neither declared unit fits; investigate before using the cube.")
        else:
            print("  -> UNRECOGNISED magnitude. Do not use the cube until this is understood.")

        # -- 4. one call, 44 tenors -------------------------------------
        _rule("4. a 44-tenor par grid in ONE CVTSHIST call")
        grid_tags = T.ois_par_grid("USD_SOFR")
        before = client.calls
        grid = client.fetch_frame(grid_tags, "DAILY", period="1M")
        print(f"  requested {len(grid_tags)} tags, used {client.calls - before} call(s)")
        print(f"  block: {grid.shape[0]} rows x {grid.shape[1]} columns")
        failures = client.last_failures()
        if failures:
            print(f"  per-tag failures ({len(failures)}): {list(failures.items())[:6]}")
        if not grid.empty:
            latest = grid.iloc[-1].dropna()
            print(f"  {grid.index[-1]:%Y-%m-%d}: "
                  + ", ".join(f"{c.rsplit('.', 1)[-1]}={v:.5f}" for c, v in latest.items()
                              if c.rsplit('.', 1)[-1] in {"2Y", "5Y", "10Y", "30Y"}))

        # -- 5. explicit date bounds ------------------------------------
        _rule("5. EXPLICIT start/end bounds (format inferred, never confirmed)")
        end = datetime.date.today()
        start = end - datetime.timedelta(days=14)
        windowed = client.fetch_timeseries([CONTROLS[0]], "DAILY", start=start, end=end)
        if CONTROLS[0] in windowed:
            series = windowed[CONTROLS[0]]
            print(f"  start={start} end={end} -> {len(series)} rows, "
                  f"{series.index.min():%Y-%m-%d}..{series.index.max():%Y-%m-%d}")
            inside = series.index.min().date() >= start - datetime.timedelta(days=5)
            print(f"  -> bounds were {'HONOURED' if inside else 'IGNORED - the format is wrong'}")
        else:
            print(f"  NO DATA with explicit bounds: {client.last_failures()}")
            print("  -> the yyyyMMdd bound format is probably wrong. Prefer period=.")

        # -- 6. SWAP_LIBOR ----------------------------------------------
        _rule("6. RATES.SWAP_LIBOR (shape recorded, never confirmed to serve)")
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            libor_tags = [
                T.swap_libor(ccy, "PAR", "10Y", warn=False) for ccy in ("EUR", "GBP", "JPY", "AUD", "INR")
            ]
        libor = client.validate(libor_tags, period="1M")
        for tag, verdict in libor.items():
            print(f"  {verdict:<10} {tag}")
        served = sum(1 for v in libor.values() if v == "valid")
        print(f"  -> {served}/{len(libor)} serve. "
              + ("SWAP_LIBOR IS USABLE." if served else "SWAP_LIBOR DOES NOT SERVE on this shape."))

        # -- 7. SWAP_SPREAD ---------------------------------------------
        _rule("7. SWAP_SPREAD (CVMETADATA claims zero valid tenors here)")
        spread_tags = [T.ois_swap_spread("USD_SOFR", t) for t in T.SWAP_SPREAD_LIQUID_TENORS]
        spreads = client.validate(spread_tags, period="1M")
        served = sum(1 for v in spreads.values() if v == "valid")
        print(f"  {served}/{len(spreads)} tenors serve through CVTSHIST")
        print(f"  sample: {[(t.rsplit('.', 1)[-1], v) for t, v in list(spreads.items())[:6]]}")

        # -- 8. a real curve, repriced ----------------------------------
        _rule("8. strip a curve from REAL quotes and reprice its own inputs")
        if grid.empty:
            print("  skipped: no par grid")
        else:
            from MDP.CitiVelocityExcel.curves import (
                build_ql_ois_curve,
                build_rl_ois_curve,
                forward_rate,
                par_reprice_errors_bp,
                ql_forward_rate,
            )

            row = grid.iloc[-1]
            par_rates = {
                tag.rsplit(".", 1)[-1]: float(v) for tag, v in row.items() if pd.notna(v)
            }
            ref = grid.index[-1].date()
            rlc = build_rl_ois_curve(par_rates=par_rates, ref_date=ref, citi_index="USD_SOFR")
            errors = par_reprice_errors_bp(rlc)
            print(f"  rateslib: {len(par_rates)} tenors, max |reprice error| "
                  f"{errors.abs().max():.3e} bp")
            qlc = build_ql_ois_curve(par_rates=par_rates, ref_date=ref, citi_index="USD_SOFR")
            print(f"  {'forward':<12}{'rateslib':>12}{'QuantLib':>12}{'gap bp':>10}")
            for fwd, tenor in (("1Y", "1Y"), ("5Y", "5Y"), ("10Y", "10Y")):
                a = forward_rate(rlc, forward=fwd, tenor=tenor)
                b = ql_forward_rate(qlc, forward=fwd, tenor=tenor)
                print(f"  {fwd}x{tenor:<9}{a:>12.6f}{b:>12.6f}{(a - b) * 100:>10.5f}")

            quoted_10y = par_rates.get("10Y")
            model_10y = forward_rate(rlc, forward="0D", tenor="10Y")
            if quoted_10y is not None:
                print(f"\n  EQUIVALENCE on live data: quote {quoted_10y:.6f} vs "
                      f"repriced {model_10y:.6f}  ({abs(quoted_10y - model_10y) * 100:.4f} bp)")

        _rule("done")
        print(f"total CV* calls: {client.calls}")
        return 0
    except Exception:  # noqa: BLE001 - print and still tear down cleanly
        traceback.print_exc()
        return 3
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
