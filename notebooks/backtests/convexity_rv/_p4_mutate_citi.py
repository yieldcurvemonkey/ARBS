r"""Mutation harness for the Citi-framework suites.

A test suite that does not fail when you break the code it covers is measuring
nothing.  This plants one defect at a time in the four ``citi_*`` modules, runs
the scoped suites, and reports KILLED / SURVIVED / INVALID / ANCHOR-MISS.

Four lessons from this repo's history are built in, because each one has already
produced a harness that could not fail or a tree left holding a broken line:

* **Anchors are normalised to the file's own line ending.**  A ``\n`` anchor
  against a CRLF file matches nothing and prints "ANCHOR NOT FOUND", which reads
  almost like a pass.
* **Every mutant is ``compile()``d before pytest runs.**  A mutation that breaks
  syntax makes pytest's *collection error* score as a kill.
* **Exit codes are tested, never output text.**
* **The restore is registered with ``atexit`` AND a signal handler**, not only a
  ``finally``.  A ``finally`` does not run when the process is killed, and this
  package has twice been left holding a deliberately broken line after a
  background harness was stopped mid-mutation.

Usage:  python notebooks/backtests/convexity_rv/_p4_mutate_citi.py
"""
from __future__ import annotations

import atexit
import dataclasses
import os
import pathlib
import signal
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
PY = sys.executable
SUITES = [
    "tests/test_convexity_rv_citi_fv.py",
    "tests/test_convexity_rv_citi_screen.py",
    "tests/test_convexity_rv_citi_rule.py",
    "tests/test_convexity_rv_citi_engine.py",
]

#: The file currently holding a planted defect, and its original text.  Read by
#: the restore hooks below, which run on a normal exit, an exception, an
#: ``atexit``, SIGINT, SIGTERM and (on Windows) SIGBREAK.
_INFLIGHT: dict = {"path": None, "text": None}


def _restore(*_a) -> None:
    p, t = _INFLIGHT.get("path"), _INFLIGHT.get("text")
    if p is not None and t is not None:
        pathlib.Path(p).write_text(t, encoding="utf-8", newline="")
        _INFLIGHT["path"] = _INFLIGHT["text"] = None
        print(f"\n!! restored {p} on interrupt", flush=True)


atexit.register(_restore)
for _sig in ("SIGINT", "SIGTERM", "SIGBREAK"):
    s = getattr(signal, _sig, None)
    if s is not None:
        try:
            signal.signal(s, lambda *_a: (_restore(), sys.exit(130)))
        except (ValueError, OSError):                            # pragma: no cover
            pass


@dataclasses.dataclass
class Mutation:
    name: str
    path: str
    old: str
    new: str
    expect: str          # which assertion should catch it, for the report


FV = "RVUtils/ConvexityRV/citi_fv.py"
SC = "RVUtils/ConvexityRV/citi_screen.py"
RU = "RVUtils/ConvexityRV/citi_rule.py"
EN = "RVUtils/ConvexityRV/citi_engine.py"

MUTATIONS = [
    # ---- citi_fv: the fair value ---------------------------------------
    Mutation("fv-combo-back-wing-sign", FV,
             "            - float(w10) * panel[c2].astype(float)).rename(\"fly_pct\")",
             "            + float(w10) * panel[c2].astype(float)).rename(\"fly_pct\")",
             "fv: the declared algebra"),
    Mutation("fv-fly-constraint-broken", FV,
             "            else [(float(w), 1.0 - float(w)) for w in W2_GRID])",
             "            else [(float(w), float(w)) for w in W2_GRID])",
             "fv: w2 + w10 == 1"),
    Mutation("fv-refit-sees-the-future", FV,
             "        hist = panel.iloc[:pos].tail(int(window_bd))",
             "        hist = panel.tail(int(window_bd))",
             "fv: the fitted path cannot see the future"),
    Mutation("fv-in-force-skips-the-roll-date", FV,
             "            mask = (idx >= r) & (idx < rolls[i + 1])",
             "            mask = (idx > r) & (idx < rolls[i + 1])",
             "fv: in force from the roll until the next"),
    Mutation("fv-free-renormalisation-sign", FV,
             "        return FairValueFit(float(a), float(b5), float(-b2 / b5),\n"
             "                            float(-b10 / b5), r2, int(len(j)), k)",
             "        return FairValueFit(float(a), float(b5), float(b2 / b5),\n"
             "                            float(b10 / b5), r2, int(len(j)), k)",
             "fv: free fit recovers its own weights"),
    Mutation("fv-beta-units-not-per-bp", FV,
             "        return self.b / 100.0",
             "        return self.b",
             "fv: beta is bp of CA per bp of fly"),
    Mutation("fv-ticket-belly-sign", FV,
             "    n5 = -float(belly_dv01) / (a5 * 100.0)",
             "    n5 = float(belly_dv01) / (a5 * 100.0)",
             "fv: the printed ticket's signs"),
    Mutation("fv-min-obs-guard-disabled", FV,
             "        j = pd.concat([pd.Series(y).rename(\"y\"), x.rename(\"x\")], axis=1).dropna()\n"
             "        if len(j) < min_obs:\n            continue",
             "        j = pd.concat([pd.Series(y).rename(\"y\"), x.rename(\"x\")], axis=1).dropna()\n"
             "        if False:\n            continue",
             "fv: a short window returns None"),
    Mutation("fv-degenerate-belly-not-refused", FV,
             "        if abs(b5) < 1e-9:\n            return None",
             "        if False:\n            return None",
             "fv: a constant y refuses rather than exploding"),

    # ---- citi_screen: the Figure-20 screen ------------------------------
    Mutation("screen-model-level-scale", SC,
             "    return (pd.Series(nvol_bp).astype(float) ** 2\n"
             "            * pd.Series(w).astype(float) / 2e4)",
             "    return (pd.Series(nvol_bp).astype(float) ** 2\n"
             "            * pd.Series(w).astype(float) / 1e4)",
             "screen: Ho-Lee second-moment form"),
    Mutation("screen-roll-is-a-whole-year", SC,
             "            * pd.Series(t1_mean).astype(float) / 1e4) * 0.25",
             "            * pd.Series(t1_mean).astype(float) / 1e4) * 1.00",
             "screen: the roll is ONE QUARTER of the decay"),
    Mutation("screen-implied-clips-instead-of-refusing", SC,
             "    return np.sqrt(v.where(v > 0))",
             "    return np.sqrt(v.clip(lower=0.0))",
             "screen: a negative CA has no implied vol"),
    Mutation("screen-z-is-centred", SC,
             "    mu = x.rolling(window, min_periods=mp).mean()\n"
             "    sd = x.rolling(window, min_periods=mp).std(ddof=1)",
             "    mu = x.rolling(window, min_periods=mp, center=True).mean()\n"
             "    sd = x.rolling(window, min_periods=mp, center=True).std(ddof=1)",
             "screen: the z is causal"),
    Mutation("screen-realized-keeps-roll-returns", SC,
             "        d = d.where(~pd.Series(is_roll).reindex(d.index).fillna(False)\n"
             "                    .astype(bool))",
             "        d = d.where(pd.Series(True, index=d.index))",
             "screen: roll returns are excluded"),
    Mutation("screen-identity-max-is-nan-poisoned", SC,
             "    err_vs = float(np.nanmax(diff_vs.to_numpy()))",
             "    err_vs = float(diff_vs.to_numpy().max())",
             "screen: a missing mark is skipped, not a failure"),
    Mutation("screen-nearer-colour-wraps", SC,
             "    return SCREEN_STRUCTURES[i - 1] if i > 0 else None",
             "    return SCREEN_STRUCTURES[i - 1]",
             "screen: the front pack has no nearer neighbour"),

    # ---- citi_rule: the rule itself -------------------------------------
    Mutation("rule-signal-is-spliced-too", RU,
             "    splice_signal: bool = False",
             "    splice_signal: bool = True",
             "rule: signal raw, P&L spliced"),
    Mutation("rule-pnl-is-not-spliced", RU,
             "    splice_pnl: bool = True",
             "    splice_pnl: bool = False",
             "rule: the P&L series IS spliced"),
    Mutation("rule-hedge-sign-flipped", RU,
             "    return (cfg.side * (d - beta_series * dcombo) * cfg.ca_dv01).astype(float)",
             "    return (cfg.side * (d + beta_series * dcombo) * cfg.ca_dv01).astype(float)",
             "rule: the declared P&L identity"),
    Mutation("rule-pnl-includes-the-entry-mark", RU,
             "    return seg.iloc[1:].astype(float)",
             "    return seg.astype(float)",
             "rule: P&L accrues on (entry_fill, exit_fill]"),
    Mutation("rule-entry-fills-same-day", RU,
             "            fill = _fill(idx, t, cfg.exec_lag_bd)\n"
             "            if fill is None:\n                continue",
             "            fill = _fill(idx, t, 0)\n"
             "            if fill is None:\n                continue",
             "rule: fills lag decisions by one mark"),
    Mutation("rule-target-and-stop-swapped", RU,
             "        if cum >= cfg.target_usd:\n"
             "            reason = \"target\"\n"
             "        elif cum <= cfg.stop_usd:\n"
             "            reason = \"stop\"",
             "        if cum <= cfg.stop_usd:\n"
             "            reason = \"target\"\n"
             "        elif cum >= cfg.target_usd:\n"
             "            reason = \"stop\"",
             "rule: a reachable target closes the trade"),
    Mutation("rule-screen-picks-the-narrowest", RU,
             "            best = max(cands, key=lambda l: float(ctx[l].rank_metric.get(t, -np.inf)))",
             "            best = min(cands, key=lambda l: float(ctx[l].rank_metric.get(t, -np.inf)))",
             "rule: the screen picks the widest"),
    Mutation("rule-nan-confirms-a-condition", RU,
             "        conds = pd.DataFrame({k: v.fillna(False).astype(bool)",
             "        conds = pd.DataFrame({k: v.fillna(True).astype(bool)",
             "rule: a missing input refuses"),
    Mutation("rule-frozen-hedge-books-restrikes", RU,
             "                0 if cfg.hedge in (\"fitted_frozen\", \"unhedged\")\n"
             "                else int(((rs > open_ep.entry_fill) & (rs <= fill)).sum()))",
             "                int(((rs > open_ep.entry_fill) & (rs <= fill)).sum()))",
             "rule: frozen and unhedged never re-strike"),
    Mutation("rule-fly-cost-ignores-the-weights", RU,
             "        legs = belly * (1.0 + float(ep.w2_entry) + float(ep.w10_entry))",
             "        legs = belly",
             "rule: the fly costs its three legs"),
    Mutation("rule-restrike-is-free", RU,
             "        total += LEG_RT_BP * legs * (1 + int(ep.n_restrikes))",
             "        total += LEG_RT_BP * legs",
             "rule: a re-strike is a further round trip"),
    Mutation("rule-n-eff-takes-the-bigger-clock", RU,
             "        n_eff = (float(min(n_eff_hold, len(r.episodes)))",
             "        n_eff = (float(max(n_eff_hold, len(r.episodes)))",
             "rule: n_eff is the smaller clock"),
    Mutation("rule-book-is-long-only", RU,
             "    side: int = -1",
             "    side: int = +1",
             "rule: the book is short only"),
    Mutation("rule-primary-universe-includes-the-noise", RU,
             "PRIMARY_UNIVERSE: Tuple[str, ...] = (\"GREENS\", \"BLUES\", \"GOLDS\")",
             "PRIMARY_UNIVERSE: Tuple[str, ...] = (\"WHITES\", \"GREENS\", \"BLUES\", \"GOLDS\")",
             "rule: the declared selection universe"),
    Mutation("rule-declared-cells-drop-the-secondary", RU,
             "    for h in (\"fitted_refit\", \"citi_2017\"):",
             "    for h in ():",
             "rule: declared count == 23"),

    # ---- citi_engine: the wiring ----------------------------------------
    Mutation("engine-fly-bpv-doubled", EN,
             "                \"bpv\": float(seg.leg_dv01_signed)},",
             "                \"bpv\": 2.0 * float(seg.leg_dv01_signed)},",
             "engine: the fitted fly is 1x, not 2x"),
    Mutation("engine-risk-weight-order", EN,
             "        return [float(self.w2), 1.0, float(self.w10)]",
             "        return [1.0, float(self.w2), float(self.w10)]",
             "engine: the belly is the middle leg"),
    Mutation("engine-futures-direction-flipped", EN,
             "    direction = float(-spec.side)          # short the CA => BUY the futures",
             "    direction = float(spec.side)          # short the CA => BUY the futures",
             "engine: direction rides the risk weight"),
    Mutation("engine-matched-swap-sign", EN,
             "        structure_kwargs={\"bpv\": float(-spec.side * spec.ca_dv01)},",
             "        structure_kwargs={\"bpv\": float(spec.side * spec.ca_dv01)},",
             "engine: selling the CA PAYS the matched swap"),
    Mutation("engine-abs-beta", EN,
             "            leg_dv01_signed=-float(side) * float(beta) * float(ca_dv01)))",
             "            leg_dv01_signed=abs(float(side) * float(beta) * float(ca_dv01))))",
             "engine: a negative beta flips the hedge"),
    Mutation("engine-shared-fly-tag", EN,
             "        return f\"{self.tag}#f{i}\"",
             "        return self.tag",
             "engine: each fly incarnation has its own tag"),
    Mutation("engine-assert-ran-skips-the-closed-count", EN,
             "    assert len(closed) >= n_min, (",
             "    assert len(closed) >= 0, (",
             "engine: an unwind that never matched its tag"),
    Mutation("engine-assert-ran-accepts-a-zero-curve", EN,
             "    assert float(eq.abs().max()) > 0.0, (",
             "    assert float(eq.abs().max()) >= 0.0, (",
             "engine: an identically zero curve is a failure"),
]


def _normalise(text: str, sample: str) -> str:
    """Match the anchor to the FILE's line ending, not the harness's."""
    return text.replace("\n", "\r\n") if "\r\n" in sample else text


def run_suites() -> int:
    env = dict(os.environ, ARBS_SUPABASE_ENABLED="0")
    p = subprocess.run([PY, "-m", "pytest", *SUITES, "-q", "-x",
                        "-p", "no:randomly", "-p", "no:cacheprovider",
                        "--no-header"],
                       cwd=REPO, env=env, capture_output=True, text=True)
    return p.returncode


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    base = run_suites()
    if base != 0:
        print(f"BASELINE IS RED (exit {base}) -- fix before mutating")
        sys.exit(1)
    print("baseline: green\n")

    results, matched = [], 0
    for m in MUTATIONS:
        f = REPO / m.path
        original = f.read_text(encoding="utf-8", newline="")
        old = _normalise(m.old, original)
        new = _normalise(m.new, original)
        n_hits = original.count(old)
        if n_hits != 1:
            results.append((m.name, f"ANCHOR-MISS ({n_hits} hits)", m.expect))
            print(f"{m.name:42s} ANCHOR-MISS ({n_hits} hits)")
            continue
        matched += 1
        mutant = original.replace(old, new)
        try:
            compile(mutant, str(f), "exec")
        except SyntaxError as exc:
            results.append((m.name, f"INVALID ({exc.msg})", m.expect))
            print(f"{m.name:42s} INVALID -- mutant does not compile")
            continue
        _INFLIGHT["path"], _INFLIGHT["text"] = str(f), original
        f.write_text(mutant, encoding="utf-8", newline="")
        try:
            rc = run_suites()
        finally:
            f.write_text(original, encoding="utf-8", newline="")
            _INFLIGHT["path"] = _INFLIGHT["text"] = None
        verdict = "KILLED" if rc != 0 else "SURVIVED"
        results.append((m.name, verdict, m.expect))
        print(f"{m.name:42s} {verdict:9s} ({m.expect})")

    after = run_suites()
    killed = sum(1 for _, v, _ in results if v == "KILLED")
    print(f"\nanchors matched {matched}/{len(MUTATIONS)}")
    print(f"killed {killed}/{matched}")
    print(f"restored tree re-runs {'GREEN' if after == 0 else 'RED'} (exit {after})")
    for n, v, e in results:
        if v != "KILLED":
            print(f"  NOT KILLED: {n:40s} {v}  ({e})")
    if after != 0:
        sys.exit(2)
    if killed != matched:
        sys.exit(3)


if __name__ == "__main__":
    main()
