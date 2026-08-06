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

``--vol-compare``
-----------------
A second, separate mode that pulls a REAL swaption cube and reconciles the two
rateslib backends on it::

    <env>/python.exe MDP/CitiVelocityExcel/harvest/verify_live.py --vol-compare

It is the live counterpart of ``tests/test_citivelo_native_vol_cube.py``, which
can only ever prove the two backends agree on data this repo invented. Here they
are handed Citi's own quotes and Citi's own curve, and it reports three separate
things that are easy to conflate:

* whether each backend reproduces the **quoted vol** at every node (a
  transformation bug shows up here and nowhere else);
* whether the two agree on **price and vega** (an implementation bug);
* how our curve-implied ATM forward compares with **Citi's own published
  forward** (``RATES.OIS.<idx>.FWD.<expiry>.<tenor>``). Citi measures its strike
  offsets from its forward, not ours, and a gap there slides the whole smile
  along the strike axis without changing a single node vol.

Roughly 5 ``CV*`` calls on the default grid. It does not write to the cache.
"""

from __future__ import annotations

import argparse
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


#: The grid --vol-compare pulls. Small on purpose: 4x4x6 skew plus 16 ATM tags is
#: 112 tags, which CVTSHIST serves in 3 calls at the 44-tag chunk size.
VOL_EXPIRIES = ("1Y", "2Y", "5Y", "10Y")
VOL_TENORS = ("2Y", "5Y", "10Y", "30Y")
VOL_OFFSETS = (-100.0, -50.0, -25.0, 25.0, 50.0, 100.0)


def _rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def vol_compare(client, currency: str = "USD", citi_index: str = "USD_SOFR") -> int:
    """Reconcile both rateslib vol backends on a real Citi cube."""
    import numpy as np

    from MDP.CitiVelocityExcel import tags as T
    from MDP.CitiVelocityExcel.curves import build_rl_ois_curve, par_reprice_errors_bp
    from MDP.CitiVelocityExcel.vol import (
        RATESLIB_NATIVE_AVAILABLE,
        build_rl_native_swaption_cube,
        build_rl_vol_cube,
        compare_backends,
        fetch_cube,
    )

    _rule("V1. the curve the strikes are measured from")
    if not RATESLIB_NATIVE_AVAILABLE:
        print("  this rateslib has no IRSplineCube (needs >= 2.7.0) - nothing to compare.")
        return 4
    grid_tags = T.ois_par_grid(citi_index)
    grid = client.fetch_frame(grid_tags, "DAILY", period="1M")
    if grid.empty:
        print(f"  no par grid served for {citi_index}: {client.last_failures()}")
        return 5
    row = grid.iloc[-1]
    par_rates = {tag.rsplit(".", 1)[-1]: float(v) for tag, v in row.items() if pd.notna(v)}
    ref = grid.index[-1].date()
    rl_curve = build_rl_ois_curve(par_rates=par_rates, ref_date=ref, citi_index=citi_index)
    print(f"  {ref}: {len(par_rates)} tenors, max |reprice error| "
          f"{par_reprice_errors_bp(rl_curve).abs().max():.3e} bp")

    _rule("V2. the cube, from the live add-in")
    before = client.calls
    cube = fetch_cube(
        client=client,
        currency=currency,
        expiries=VOL_EXPIRIES,
        tenors=VOL_TENORS,
        offsets_bp=VOL_OFFSETS,
        period="1M",
        strict=False,
    )
    print(f"  {cube!r}")
    print(f"  {client.calls - before} CV* call(s) for "
          f"{len(cube.expiries()) * len(cube.tenors()) * len(cube.offsets())} nodes")
    if cube.as_of != ref:
        print(f"  NOTE: cube as_of {cube.as_of} != curve ref {ref}; the forward is from {ref}.")

    _rule("V3. do the backends reproduce CITI'S OWN quoted vols?")
    frame = compare_backends(cube=cube, rl_curve=rl_curve, citi_index=citi_index, notional=1e8)
    hand_err = (frame["hand_vol_bp"] - frame["citi_vol_bp"]).abs().max()
    nat_err = frame["citi_vol_err_bp"].abs().max()
    print(f"  nodes compared                   : {len(frame)}")
    print(f"  hand-built  max |vol - quote|    : {hand_err:.3e} bp")
    print(f"  native      max |vol - quote|    : {nat_err:.3e} bp")
    print("  -> " + ("both reproduce the wire exactly; no transformation is applied."
                     if max(hand_err, nat_err) < 1e-9
                     else "A BACKEND IS TRANSFORMING THE QUOTES. Do not price off it."))

    _rule("V4. do the two backends agree with EACH OTHER?")
    frame["vega_rel"] = frame["vega_diff"].abs() / frame["hand_vega"].abs().replace(0.0, np.nan)
    print(f"  max |forward difference|         : {frame['forward_diff_bp'].abs().max():.6f} bp")
    print(f"  max relative price difference    : {frame['price_rel'].max():.3e}")
    print(f"  max relative vega difference     : {frame['vega_rel'].max():.3e}")
    print(f"  largest absolute price gap       : {frame['price_diff'].abs().max():,.4f} "
          "currency units on 100m notional")
    # A max with no location is a weak report - name the nodes, because a gap
    # concentrated in one corner is a different bug from one spread evenly.
    for label, column in (("price", "price_rel"), ("vega", "vega_rel")):
        worst = frame.nlargest(3, column)
        print(f"\n  worst 3 by relative {label} difference:")
        for _, r in worst.iterrows():
            print(f"    {r['expiry']:>3}x{r['tenor']:<3} {r['offset_bp']:>+6.0f}bp  "
                  f"vol {r['citi_vol_bp']:7.3f}  hand {r['hand_' + label]:>16,.4f}  "
                  f"native {r['native_' + label]:>16,.4f}  rel {r[column]:.3e}")
    out = _REPO_ROOT / "MDP" / "CitiVelocityExcel" / "harvest" / "vol_compare_live.parquet"
    frame.to_parquet(out)
    print(f"\n  full frame written to {out.relative_to(_REPO_ROOT)} ({len(frame)} rows)")

    _rule("V5. the real smile, and what it costs")
    native = build_rl_native_swaption_cube(cube=cube, rl_curve=rl_curve, citi_index=citi_index)
    hand = build_rl_vol_cube(cube=cube, rl_curve=rl_curve, citi_index=citi_index)
    for expiry, tenor in (("1Y", "10Y"), ("5Y", "10Y")):
        forward = native.forward(expiry, tenor)
        print(f"\n  {expiry}x{tenor}  forward {forward * 100:.4f}%  "
              f"(hand {hand.forward(expiry, tenor) * 100:.4f}%)")
        print(f"    {'offset':>8}{'Citi bp':>10}{'native bp':>11}"
              f"{'payer PV':>16}{'vega/bp':>12}")
        for off in cube.offsets():
            strike = forward + off / 1e4
            print(f"    {off:>+8.0f}{cube.vol(expiry, tenor, off):>10.4f}"
                  f"{native.normal_vol(expiry, tenor, offset_bp=off):>11.4f}"
                  f"{native.price(expiry, tenor, strike):>16,.0f}"
                  f"{native.vega(expiry, tenor, strike):>12,.0f}")

    _rule("V6. our ATM forward against CITI'S OWN published forward")
    # This is the one number the cube cannot check itself. Citi measures its
    # strike offsets from ITS forward; we measure them from the forward our
    # curve implies. A disagreement slides the whole smile along the strike axis
    # and nothing inside the cube reveals it - but RATES.OIS.<idx>.FWD.<e>.<t>
    # publishes Citi's, so it does not have to stay unknown.
    points = [(e, t) for e in ("1Y", "5Y") for t in ("2Y", "10Y", "30Y")]
    fwd_tags = {T.ois_fwd(citi_index, e, t): (e, t) for e, t in points}
    quoted_fwd = client.fetch_frame(list(fwd_tags), "DAILY", period="1M")
    print(f"    {'point':>10}{'Citi FWD':>12}{'ours':>12}{'gap bp':>10}")
    gaps = []
    for tag, (expiry, tenor) in fwd_tags.items():
        if tag not in quoted_fwd.columns or quoted_fwd[tag].dropna().empty:
            print(f"    {expiry + 'x' + tenor:>10}{'no data':>12}")
            continue
        citi = float(quoted_fwd[tag].dropna().iloc[-1])
        ours = native.forward(expiry, tenor) * 100.0
        gaps.append(abs(citi - ours) * 100.0)
        print(f"    {expiry + 'x' + tenor:>10}{citi:>12.5f}{ours:>12.5f}{(ours - citi) * 100:>10.3f}")
    if gaps:
        worst = max(gaps)
        print(f"\n  worst forward gap: {worst:.3f} bp")
        print("  -> " + (
            "the strike axis is anchored where Citi anchors it."
            if worst < 1.0 else
            f"the smile is shifted ~{worst:.1f}bp along the strike axis. Node vols still "
            "round-trip (they are keyed by offset) but a STRIKE-quoted price is off by "
            "the skew slope times this gap."
        ))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--vol-compare",
        action="store_true",
        help="reconcile the two rateslib vol backends on a real cube instead of "
             "running the eight wire checks",
    )
    parser.add_argument("--currency", default="USD", help="vol currency for --vol-compare")
    parser.add_argument("--index", default="USD_SOFR", help="Citi OIS index for --vol-compare")
    args = parser.parse_args()

    if args.vol_compare:
        _rule("connect")
        try:
            client = CitiVelocityExcelClient.connect(attempts=1, readiness_timeout=120.0)
        except Exception as exc:  # noqa: BLE001 - the report IS the exception
            print(f"FAILED: {type(exc).__name__}: {exc}")
            return 1
        print("connected")
        try:
            code = vol_compare(client, currency=args.currency, citi_index=args.index)
            _rule("done")
            print(f"total CV* calls: {client.calls}")
            return code
        except Exception:  # noqa: BLE001 - print and still tear down cleanly
            traceback.print_exc()
            return 3
        finally:
            client.close()

    return _wire_checks()


def _wire_checks() -> int:
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
