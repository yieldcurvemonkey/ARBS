r"""Mutation harness for the GV suites.

A test suite that does not fail when you break the code it covers is measuring
nothing.  This plants one defect at a time in the GV modules, runs the scoped
suites, and reports KILLED / SURVIVED / INVALID / ANCHOR-MISS.

Three lessons from this repo's history are built in, because each one has
already produced a harness that could not fail:

* **Anchors are normalised to the file's own line ending.**  A ``\n`` anchor
  against a CRLF file matches nothing and prints "ANCHOR NOT FOUND", which reads
  almost like a pass.
* **Every mutant is ``compile()``d before pytest runs.**  A mutation that breaks
  syntax makes pytest's *collection error* score as a kill.
* **Exit codes are tested, never output text.**

Usage:  python notebooks/backtests/convexity_rv/_p2_mutate_gv.py
"""
from __future__ import annotations

import dataclasses
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
PY = sys.executable
SUITES = [
    "tests/test_convexity_rv_gv_universe.py",
    "tests/test_convexity_rv_gv_sizing.py",
    "tests/test_convexity_rv_gv_signals.py",
    "tests/test_convexity_rv_gv_grid.py",
    "tests/test_convexity_rv_gv_engine.py",
    "tests/test_ccp_basis_query_tb.py",
]


@dataclasses.dataclass
class Mutation:
    name: str
    path: str
    old: str
    new: str
    expect: str          # which suite should catch it, for the report


MUTATIONS = [
    Mutation("fly-convention-halved",
             "RVUtils/ConvexityRV/gv_universe.py",
             "        out = (2.0 * b - f - k) * 100.0",
             "        out = (b - 0.5 * (f + k)) * 100.0",
             "universe: FLY RATE tie-out"),
    Mutation("fly-package-dv01-halved",
             "RVUtils/ConvexityRV/gv_universe.py",
             "        return [-d, 2.0 * d, -d]",
             "        return [-d, d, -d]",
             "universe: package DV01 / cost"),
    Mutation("blackout-single-clock",
             "RVUtils/ConvexityRV/gv_universe.py",
             "    for d in set(ca_roll_dates(idx)) | set(leg_roll_dates(idx)):",
             "    for d in set(ca_roll_dates(idx)):",
             "universe: blackout covers both clocks"),
    Mutation("time-weight-hull-convention",
             "RVUtils/ConvexityRV/gv_universe.py",
             "def time_weight_series(dates: Sequence, label: str,\n"
             "                       convention: str = \"citi\") -> pd.Series:",
             "def time_weight_series(dates: Sequence, label: str,\n"
             "                       convention: str = \"hull\") -> pd.Series:",
             "universe: mean of squares"),
    Mutation("noise-model-wrong-coefficient",
             "RVUtils/ConvexityRV/gv_sizing.py",
             "    tau = var_d * (1.0 + 2.0 * ac1)",
             "    tau = var_d * (1.0 + ac1)",
             "sizing: recovers planted variances"),
    Mutation("ca-vega-scale-10x",
             "RVUtils/ConvexityRV/gv_sizing.py",
             "            * pd.Series(w).astype(float) / 1e4)",
             "            * pd.Series(w).astype(float) / 1e3)",
             "sizing: vega = finite difference"),
    Mutation("variance-price-scale",
             "RVUtils/ConvexityRV/gv_sizing.py",
             "    return 2e4 * pd.Series(ca_bp).astype(float) / pd.Series(w).astype(float)",
             "    return 1e4 * pd.Series(ca_bp).astype(float) / pd.Series(w).astype(float)",
             "sizing: holee round trip"),
    Mutation("levels-beta-uses-changes",
             "RVUtils/ConvexityRV/gv_sizing.py",
             "    return _roll_ols(pd.Series(ca), pd.Series(leg), window, mp)",
             "    return _roll_ols(pd.Series(ca).diff(), pd.Series(leg).diff(), window, mp)",
             "sizing: level vs change sign"),
    Mutation("vega-gate-disabled",
             "RVUtils/ConvexityRV/gv_sizing.py",
             "        ok = ((t.abs() >= VOL_BETA_T_MIN)\n"
             "              & (pr2 >= VOL_BETA_PARTIAL_R2_MIN))",
             "        ok = pd.Series(True, index=t.index)",
             "sizing: gate refuses noise"),
    Mutation("vega-uses-uncontrolled-fit",
             "RVUtils/ConvexityRV/gv_sizing.py",
             "        vb, t, pr2 = rolling_vol_beta_controlled(\n"
             "            inp.leg, inp.nvol, inp.level, inp.slope, window=inp.window)",
             "        vb, t, pr2 = rolling_vol_beta(inp.leg, inp.nvol,\n"
             "                                      window=inp.window)",
             "sizing: controlled fit strips the level channel"),
    Mutation("ca-theta-sign-flip",
             "RVUtils/ConvexityRV/gv_sizing.py",
             "    return -(s ** 2) * pd.Series(t1_mean).astype(float) / 1e4",
             "    return (s ** 2) * pd.Series(t1_mean).astype(float) / 1e4",
             "sizing: theta = finite difference, and is negative"),
    Mutation("carry-decomposition-drops-the-side",
             "RVUtils/ConvexityRV/gv_sizing.py",
             "    carry = float(side) * float(th.sum()) * float(ca_dv01)",
             "    carry = float(th.sum()) * float(ca_dv01)",
             "sizing: short CA earns the decay"),
    Mutation("entry-fills-same-day",
             "RVUtils/ConvexityRV/gv_signals.py",
             "    t0 = fill_date(idx, ep.entry, exec_lag_bd)",
             "    t0 = fill_date(idx, ep.entry, 0)",
             "signals: t+1 kills the harvest"),
    Mutation("episodes-ignore-segments",
             "RVUtils/ConvexityRV/gv_signals.py",
             "        win = frame.loc[a:b]",
             "        win = frame",
             "signals: no episode straddles a roll"),
    Mutation("hedge-cost-ignores-leg-count",
             "RVUtils/ConvexityRV/gv_signals.py",
             "        total += LEG_RT_BP * leg_cost_dv01(leg_id, abs(ep.beta_entry) * ca)",
             "        total += LEG_RT_BP * abs(ep.beta_entry) * ca",
             "signals: fly costs 4x"),
    Mutation("beta-restruck-intra-episode",
             "RVUtils/ConvexityRV/gv_signals.py",
             "        d = d - ep.beta_entry * leg_raw.reindex(ca_raw.index).loc[t0:t1].diff()",
             "        d = d - 1.0 * leg_raw.reindex(ca_raw.index).loc[t0:t1].diff()",
             "signals: frozen beta"),
    Mutation("declared-cells-drop-a-family",
             "RVUtils/ConvexityRV/gv_grid.py",
             "    for s in PRIMARY_STRUCTURES:\n"
             "        for sz in VARBASIS_SIZINGS:",
             "    for s in PRIMARY_STRUCTURES[:0]:\n"
             "        for sz in VARBASIS_SIZINGS:",
             "grid: declared count == 298"),
    Mutation("engine-fly-bpv-not-doubled",
             "RVUtils/ConvexityRV/gv_engine.py",
             '                    "bpv": 2.0 * float(L.leg_dv01_signed)},',
             '                    "bpv": float(L.leg_dv01_signed)},',
             "engine: fly bpv is 2x the quoted leg DV01"),
    Mutation("engine-futures-direction-flipped",
             "RVUtils/ConvexityRV/gv_engine.py",
             "    direction = float(-spec.side)",
             "    direction = float(spec.side)",
             "engine: direction rides the risk weight"),
    Mutation("engine-abs-beta",
             "RVUtils/ConvexityRV/gv_engine.py",
             "                    leg_dv01_signed=-float(side) * float(beta_entry) * ca_dv01)",
             "                    leg_dv01_signed=abs(float(side) * float(beta_entry) * ca_dv01))",
             "engine: a negative beta flips the leg"),
    Mutation("engine-matched-leg-uses-front-rank",
             "RVUtils/ConvexityRV/gv_engine.py",
             '        k = {"immF": 1, "imm2": 2}.get(spec.start) or matched_imm_rank(structure)',
             '        k = {"immF": 1, "imm2": 2}.get(spec.start) or 1',
             "engine: matched leg uses the structure's rank"),
    Mutation("roll-splice-backward-adjusted",
             "RVUtils/ConvexityRV/gv_sizing.py",
             "    return (s - jumps.cumsum()).rename",
             "    return (s - jumps[::-1].cumsum()[::-1]).rename",
             "engine: roll splice is causal"),
    Mutation("chbasis-forward-fills-a-missing-date",
             "TB/IRClearingHouseBasisTB.py",
             "        if d not in df.index:\n"
             "            return None                       # missing, NOT forward filled",
             "        if d not in df.index:\n"
             "            d = df.index[df.index <= d].max() if (df.index <= d).any() else d\n"
             "        if d not in df.index:\n"
             "            return None",
             "ccp: a missing date is not forward filled"),
    Mutation("chbasis-refetches-per-query",
             "TB/IRClearingHouseBasisTB.py",
             "            if key in panels or key in failures:\n                continue",
             "            if False:\n                continue",
             "ccp: one MDP call per instrument"),
    Mutation("chbasis-instrument-key-splits-on-value",
             "Query/IRClearingHouseBasis/IRClearingHouseBasisQuery.py",
             "        return (self.ccy.upper(), self.index.upper(), self.tenor.lower(),\n"
             "                self.clearing_house_a.upper(), self.clearing_house_b.upper(),\n"
             "                bool(self.allow_network))",
             "        return (self.ccy.upper(), self.index.upper(), self.tenor.lower(),\n"
             "                self.clearing_house_a.upper(), self.clearing_house_b.upper(),\n"
             "                bool(self.allow_network), self.value)",
             "ccp: instrument key ignores the value"),
    Mutation("chbasis-units-always-bp",
             "Query/IRClearingHouseBasis/IRClearingHouseBasisQuery.py",
             '    return "bp" if IRClearingHouseBasisValue(value) is \\\n'
             "        IRClearingHouseBasisValue.BASIS_BPS else \"decimal\"",
             '    return "bp"',
             "ccp: bp vs decimal are named"),
    Mutation("chbasis-network-on-by-default",
             "Query/IRClearingHouseBasis/IRClearingHouseBasisQuery.py",
             "    allow_network: bool = False",
             "    allow_network: bool = True",
             "ccp: network is opt-in"),
]


def _normalise(text: str, sample: str) -> str:
    """Match the anchor to the FILE's line ending, not the harness's."""
    return text.replace("\n", "\r\n") if "\r\n" in sample else text


def run_suites() -> int:
    env = dict(os.environ, ARBS_SUPABASE_ENABLED="0")
    p = subprocess.run([PY, "-m", "pytest", *SUITES, "-q", "-x",
                        "-p", "no:randomly", "--no-header"],
                       cwd=REPO, env=env, capture_output=True, text=True)
    return p.returncode


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    base = run_suites()
    if base != 0:
        print(f"BASELINE IS RED (exit {base}) -- fix before mutating")
        sys.exit(1)
    print("baseline: green\n")

    results = []
    matched = 0
    for m in MUTATIONS:
        f = REPO / m.path
        original = f.read_text(encoding="utf-8", newline="")
        old = _normalise(m.old, original)
        new = _normalise(m.new, original)
        n_hits = original.count(old)
        if n_hits != 1:
            results.append((m.name, f"ANCHOR-MISS ({n_hits} hits)", m.expect))
            print(f"{m.name:34s} ANCHOR-MISS ({n_hits} hits)")
            continue
        matched += 1
        mutant = original.replace(old, new)
        try:
            compile(mutant, str(f), "exec")
        except SyntaxError as exc:
            results.append((m.name, f"INVALID ({exc.msg})", m.expect))
            print(f"{m.name:34s} INVALID -- mutant does not compile")
            continue
        f.write_text(mutant, encoding="utf-8", newline="")
        try:
            rc = run_suites()
        finally:
            f.write_text(original, encoding="utf-8", newline="")
        verdict = "KILLED" if rc != 0 else "SURVIVED"
        results.append((m.name, verdict, m.expect))
        print(f"{m.name:34s} {verdict:9s} ({m.expect})")

    # a finally: does not survive SIGTERM -- verify the tree is clean either way
    after = run_suites()
    killed = sum(1 for _, v, _ in results if v == "KILLED")
    print(f"\nanchors matched {matched}/{len(MUTATIONS)}")
    print(f"killed {killed}/{matched}")
    print(f"restored tree re-runs {'GREEN' if after == 0 else 'RED'} (exit {after})")
    if after != 0:
        sys.exit(2)
    if killed != matched:
        sys.exit(3)


if __name__ == "__main__":
    main()
