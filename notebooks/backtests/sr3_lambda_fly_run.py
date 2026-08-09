"""Run the copula-coordinate butterfly against the pre-registered bar.

    python notebooks/backtests/sr3_lambda_fly_run.py \
        --panel notebooks/data/sr3_zq_lambda/panel.csv \
        --placebo-panel notebooks/data/sr3_zq_lambda/panel_wrongcal.csv

The bar, the placebos and the kill criteria are fixed in
``docs/plans/2026-08-08-sr3-zq-lambda-preregistration.md`` and are quoted back verbatim at
the end. Nothing here is tuned after seeing a result.
"""
from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from sr3_lambda_fly_qdb import (  # noqa: E402
    CONTRACTS_PER_FLY,
    DEFAULT_TCOST_VOL_BP,
    USD_PER_BP_PER_CONTRACT,
    SignalConfig,
    make_lambda_fly_backtest,
    prepare_signal_frame,
)

# The pre-registered bar. Changing any of these makes the result exploratory.
BAR_MIN_TRADES = 25
BAR_MIN_CYCLES = 6
BAR_DSR_PROB = 0.5
FULL_TICK_MULTIPLE = 2.0


def closed_frame(bt) -> pd.DataFrame:
    log = getattr(bt.portfolio, "closed_positions_log", None) or []
    if not log:
        return pd.DataFrame()
    return pd.DataFrame(log)


def run_one(signal_frame, symbol, opt_mdp, *, config, contracts, tcost_vol_bp):
    bt, state = make_lambda_fly_backtest(
        signal_frame, symbol, opt_mdp,
        config=config, contracts=contracts, tcost_vol_bp=tcost_vol_bp,
    )
    bt.run()
    cl = closed_frame(bt)
    equity = pd.Series(bt.mtm_history).sort_index() if bt.mtm_history else pd.Series(dtype=float)
    return bt, state, cl, equity


def to_bp(usd, contracts: float) -> float:
    """USD -> bp of package premium. 1bp of a 1-lot fly is $25 (2500 x 0.01)."""
    return float(usd) / (USD_PER_BP_PER_CONTRACT * float(contracts))


def summarise(all_closed: pd.DataFrame, all_daily: pd.Series, *, contracts, tcost_vol_bp,
              n_cycles: int, n_trials: int, label: str, quiet: bool = False) -> dict:
    say = (lambda *a, **k: None) if quiet else print
    say(f"\n===== {label} =====")
    if all_closed.empty:
        say("  no closed trades")
        return {"label": label, "n_trades": 0}

    round_trip_usd = 2.0 * CONTRACTS_PER_FLY * contracts * tcost_vol_bp * USD_PER_BP_PER_CONTRACT
    gross_bp = all_closed["gross_realized_pnl"].map(lambda v: to_bp(v, contracts))
    net_bp = all_closed["realized_pnl"].map(lambda v: to_bp(v, contracts))
    net_full_bp = gross_bp - to_bp(round_trip_usd * FULL_TICK_MULTIPLE, contracts)

    n = len(all_closed)
    say(f"  trades {n}   round trip cost {to_bp(round_trip_usd, contracts):.2f}bp "
          f"(half tick)  /  {to_bp(round_trip_usd, contracts) * FULL_TICK_MULTIPLE:.2f}bp (full tick)")
    say(f"  gross bp/trade   mean {gross_bp.mean():+.3f}  median {gross_bp.median():+.3f}  "
          f"sd {gross_bp.std(ddof=1):.3f}")
    say(f"  net   bp/trade   mean {net_bp.mean():+.3f}  median {net_bp.median():+.3f}")
    say(f"  net@fulltick     mean {net_full_bp.mean():+.3f}  median {net_full_bp.median():+.3f}")

    daily = all_daily.sort_index() if len(all_daily) else pd.Series(dtype=float)
    sharpe = nw_t = float("nan")
    if len(daily) > 5 and daily.std(ddof=1) > 0:
        sharpe = float(daily.mean() / daily.std(ddof=1) * np.sqrt(252))
        try:
            from RVUtils.SFRRVLab.stats import nw_tstat
            nw_t = float(nw_tstat(daily.to_numpy()))
        except Exception:
            pass
    say(f"  daily $ P&L: n {len(daily)}  ann Sharpe {sharpe:+.2f}  NW t {nw_t:+.2f}")

    dsr = {}
    try:
        from BT.signals.deflated_sharpe import deflated_sharpe
        dsr = deflated_sharpe(net_bp.to_numpy(), n_trials=int(n_trials), annualisation=1.0)
        say(f"  DSR: sr {dsr.get('sr', float('nan')):+.3f}  "
              f"sr0 {dsr.get('sr0', float('nan')):+.3f}  prob {dsr.get('dsr_prob', float('nan')):.3f}  "
              f"(n_trials={n_trials})")
    except Exception as exc:  # noqa: BLE001
        say(f"  DSR unavailable: {exc}")

    # Break-even cost multiple: how many half-ticks the gross edge can pay for.
    be = float(gross_bp.mean() / to_bp(round_trip_usd, contracts)) if gross_bp.mean() > 0 else 0.0
    say(f"  break-even cost multiple: {be:.2f}x the half-tick round trip")
    say(f"  independent meeting cycles: {n_cycles}")

    return {
        "label": label, "n_trades": n,
        "gross_bp": float(gross_bp.mean()), "net_bp": float(net_bp.mean()),
        "net_full_bp": float(net_full_bp.mean()), "median_net_bp": float(net_bp.median()),
        "sharpe": sharpe, "nw_t": nw_t,
        "dsr_prob": float(dsr.get("dsr_prob", float("nan"))) if dsr else float("nan"),
        "breakeven_mult": be, "n_cycles": n_cycles,
    }


def run_panel(panel: pd.DataFrame, opt_mdp, *, config, contracts, tcost_vol_bp,
              shuffle_seed=None, label="", n_trials=1, quiet=False):
    sf = prepare_signal_frame(panel, config, shuffle_seed=shuffle_seed)
    closed, equities = [], []
    opened = 0
    for symbol in sorted(sf.symbol.unique()):
        try:
            bt, state, cl, eq = run_one(sf, symbol, opt_mdp, config=config,
                                        contracts=contracts, tcost_vol_bp=tcost_vol_bp)
        except Exception as exc:  # noqa: BLE001
            print(f"  {symbol}: run failed: {type(exc).__name__}: {exc}")
            continue
        opened += state.n_opened
        if not cl.empty:
            cl = cl.copy()
            cl["symbol"] = symbol
            closed.append(cl)
        if len(eq):
            equities.append(eq)
    all_closed = pd.concat(closed, ignore_index=True) if closed else pd.DataFrame()
    # Diff EACH contract's curve before summing. bt.mtm_history is CUMULATIVE equity, and the
    # contracts span different date ranges, so summing the levels makes a contract's final
    # cumulative P&L vanish from the total on the first date after it ends -- one fabricated
    # spike per expiry, straight into the daily Sharpe.
    if equities:
        dailies = [eq.sort_index().diff().dropna() for eq in equities if len(eq) > 1]
        all_daily = (
            pd.concat(dailies).groupby(level=0).sum().sort_index() if dailies else pd.Series(dtype=float)
        )
    else:
        all_daily = pd.Series(dtype=float)
    if opened != len(all_closed) and not quiet:
        print(f"  RECONCILIATION: {opened} entries signalled, {len(all_closed)} positions closed. "
              f"The engine silently drops a leg with no quote, so the gap is trades that never "
              f"opened -- not a P&L that is missing them.")
    # Independent draws are distinct FOMC MEETINGS that resolved while a trade was on --
    # not sessions, and not label strings, because SFRU26 and SFRZ26 share sep26/oct26 under
    # different meeting_labels values and counting those separately overstates independence.
    cycles = 0
    if not all_closed.empty and "meeting_labels" in sf.columns:
        held = set()
        opened_days = pd.to_datetime(all_closed["opened_at"]).dt.tz_localize(None).dt.normalize()
        sf_idx = sf.assign(_d=pd.to_datetime(sf["as_of"]).dt.normalize()).set_index(["symbol", "_d"])
        for sym, day in zip(all_closed.get("symbol", []), opened_days):
            try:
                labels = sf_idx.loc[(sym, day), "meeting_labels"]
            except KeyError:
                continue
            if isinstance(labels, pd.Series):
                labels = labels.iloc[0]
            if isinstance(labels, str):
                held.update(x for x in labels.split(",") if x)
        cycles = len(held)
    return summarise(all_closed, all_daily, contracts=contracts, tcost_vol_bp=tcost_vol_bp,
                     n_cycles=cycles, n_trials=n_trials, label=label, quiet=quiet), all_closed, sf


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="notebooks/data/sr3_zq_lambda/panel.csv")
    ap.add_argument("--placebo-panel", default="")
    ap.add_argument("--contracts", type=float, default=1.0)
    ap.add_argument("--tcost-vol-bp", type=float, default=DEFAULT_TCOST_VOL_BP)
    ap.add_argument("--z-threshold", type=float, default=1.0)
    ap.add_argument("--shuffle-seeds", type=int, default=20)
    ap.add_argument("--z-window", type=int, default=60)
    ap.add_argument("--z-min-obs", type=int, default=30)
    ap.add_argument("--max-fwd-resid-bp", type=float, default=1.0)
    ap.add_argument("--max-atom-spread", type=float, default=0.60)
    ap.add_argument(
        "--exploratory",
        action="store_true",
        help=(
            "Label the run EXPLORATORY. Use whenever any gate differs from the "
            "pre-registration; the verdict then carries the label and cannot read ALIVE"
        ),
    )
    args = ap.parse_args()

    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    opt_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    config = SignalConfig(
        z_threshold=args.z_threshold,
        z_window=args.z_window,
        z_min_obs=args.z_min_obs,
        max_fwd_resid_bp=args.max_fwd_resid_bp,
        max_atom_spread=args.max_atom_spread,
    )
    default = SignalConfig()
    exploratory = bool(args.exploratory) or config != default
    if exploratory:
        print("\n*** EXPLORATORY RUN: gates differ from the pre-registration. This cannot "
              "read ALIVE and its configurations count toward n_trials. ***")
    panel = pd.read_csv(args.panel)

    # n_trials for the DSR: the real search this result came out of. One live configuration
    # plus every shuffle and placebo run, counted honestly rather than set to 1.
    n_trials = 1 + args.shuffle_seeds + (1 if args.placebo_panel else 0)

    # Diagnose a no-signal run before reporting a verdict on it: "the signal never fired
    # because there was not enough admissible data to standardise it" and "the signal fired
    # and lost money" are different findings and must not share a label.
    probe = prepare_signal_frame(panel, config)
    n_adm = int(probe["admissible"].sum())
    n_z = int(probe["lambda_z"].notna().sum())
    n_fire = int((probe["lambda_z"].abs() >= config.z_threshold).sum())
    print(f"\nsignal availability: {len(probe)} rows, {n_adm} admissible, {n_z} with a z-score, "
          f"{n_fire} beyond |z| >= {config.z_threshold}")
    if n_z == 0:
        print(f"  NO Z-SCORE ANYWHERE. The trailing window needs {config.z_min_obs} admissible "
              f"observations and the largest contract supplies "
              f"{int(probe.groupby('symbol')['admissible'].sum().max())}. This is a "
              f"DATA-SUFFICIENCY outcome, not evidence about the edge.")

    live, live_closed, live_sf = run_panel(
        panel, opt_mdp, config=config, contracts=args.contracts,
        tcost_vol_bp=args.tcost_vol_bp, label="LIVE", n_trials=n_trials,
    )

    print("\n===== PLACEBO 1: shuffled lambda (same dates, same costs, no information) =====")
    shuffled = []
    for seed in range(args.shuffle_seeds):
        res, _, _ = run_panel(panel, opt_mdp, config=config, contracts=args.contracts,
                              tcost_vol_bp=args.tcost_vol_bp, shuffle_seed=seed,
                              label=f"shuffle {seed}", n_trials=n_trials, quiet=True)
        if res.get("n_trades"):
            shuffled.append(res)
    if shuffled:
        g = np.array([r["gross_bp"] for r in shuffled], dtype=float)
        print(f"\n  shuffled gross bp/trade: mean {g.mean():+.3f}  p90 {np.percentile(g, 90):+.3f}  "
              f"max {g.max():+.3f}   LIVE {live.get('gross_bp', float('nan')):+.3f}")
        beat = float((g < live.get("gross_bp", float("nan"))).mean())
        print(f"  live beats {100 * beat:.0f}% of shuffles "
              f"({'PASS' if beat >= 0.90 else 'FAIL: kill criterion 2'})")

    if args.placebo_panel and os.path.exists(args.placebo_panel):
        print("\n===== PLACEBO 2: wrong FOMC calendar =====")
        pl = pd.read_csv(args.placebo_panel)
        res, _, _ = run_panel(pl, opt_mdp, config=config, contracts=args.contracts,
                              tcost_vol_bp=args.tcost_vol_bp, label="WRONG CALENDAR",
                              n_trials=n_trials)
        if res.get("n_trades") and float(live.get("gross_bp") or 0.0) > 0.0:
            retained = res["gross_bp"] / live["gross_bp"] if live["gross_bp"] else float("nan")
            print(f"\n  wrong-calendar retains {100 * retained:.0f}% of the live gross edge "
                  f"({'PASS' if retained <= 0.50 else 'FAIL: kill criterion 1 -- this is cell '
                     'geometry, not lattice probability'})")

    # Confound check: does z survive alongside dte and meeting count?
    if not live_closed.empty:
        print("\n===== CONFOUND: per-trade net on z, dte, n_meetings =====")
        merged = live_closed.copy()
        merged["opened_at"] = pd.to_datetime(merged["opened_at"]).dt.tz_localize(None).dt.normalize()
        sf = live_sf.copy()
        sf["as_of"] = pd.to_datetime(sf["as_of"]).dt.normalize()
        merged = merged.merge(
            sf[["symbol", "as_of", "lambda_z", "time_to_expiry", "n_meetings"]],
            left_on=["symbol", "opened_at"], right_on=["symbol", "as_of"], how="left",
        )
        y = merged["realized_pnl"].map(lambda v: to_bp(v, args.contracts)).to_numpy(dtype=float)
        for cols in (["lambda_z"], ["lambda_z", "time_to_expiry", "n_meetings"]):
            X = merged[cols].to_numpy(dtype=float)
            good = np.isfinite(y) & np.isfinite(X).all(axis=1)
            if good.sum() < len(cols) + 5:
                print(f"  {cols}: too few complete rows ({int(good.sum())})")
                continue
            A = np.column_stack([np.ones(good.sum()), X[good]])
            beta, *_ = np.linalg.lstsq(A, y[good], rcond=None)
            resid = y[good] - A @ beta
            dof = max(good.sum() - A.shape[1], 1)
            se = np.sqrt(np.diag(np.linalg.inv(A.T @ A)) * (resid @ resid) / dof)
            print(f"  {cols}: beta_z {beta[1]:+.4f} (t {beta[1] / se[1]:+.2f}), n={int(good.sum())}")

    print("\n===== VERDICT against the pre-registered bar =====")
    checks = [
        (f"1. trades >= {BAR_MIN_TRADES}", live.get("n_trades", 0) >= BAR_MIN_TRADES,
         f"{live.get('n_trades', 0)}"),
        ("2. net bp/trade > 0 at the half tick", live.get("net_bp", float("nan")) > 0,
         f"{live.get('net_bp', float('nan')):+.3f}"),
        ("3. net bp/trade > 0 at the full tick", live.get("net_full_bp", float("nan")) > 0,
         f"{live.get('net_full_bp', float('nan')):+.3f}"),
        (f"4. DSR prob > {BAR_DSR_PROB}", live.get("dsr_prob", float("nan")) > BAR_DSR_PROB,
         f"{live.get('dsr_prob', float('nan')):.3f}"),
        ("5. median net >= 0", live.get("median_net_bp", float("nan")) >= 0,
         f"{live.get('median_net_bp', float('nan')):+.3f}"),
        (f"6. independent cycles >= {BAR_MIN_CYCLES}", live.get("n_cycles", 0) >= BAR_MIN_CYCLES,
         f"{live.get('n_cycles', 0)}"),
    ]
    for name, ok, val in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:<42} {val}")
    first_five = all(ok for _, ok, _ in checks[:5])
    if live.get("n_trades", 0) == 0:
        # "The signal never fired for want of data" and "the signal fired and lost money" are
        # different findings. Reporting the first as DEAD would claim evidence that was never
        # gathered, which is the failure mode this whole programme is guarding against.
        verdict = "NO SIGNAL -- the strategy never traded. " + (
            "Not enough admissible sessions to standardise lambda; this is a data-sufficiency "
            "result and says nothing about the edge."
            if n_z == 0 else
            "lambda never left its trailing distribution by the entry threshold."
        )
    elif all(ok for _, ok, _ in checks):
        verdict = "ALIVE"
    elif first_five:
        verdict = "MONITOR (clears the economics, fails the sample-size bar)"
    else:
        verdict = "DEAD"
    if exploratory and verdict == "ALIVE":
        verdict = "EXPLORATORY-ONLY (gates differ from the pre-registration)"
    print(f"\n  VERDICT: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
