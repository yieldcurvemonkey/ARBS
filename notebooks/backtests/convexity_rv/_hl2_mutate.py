r"""Mutation harness for ``_MODEL2`` -- the model module AND its wiring.

Same contract as ``_hl_mutate.py`` and the same hard-won details: anchors
normalised to the file's own line ending; every mutant ``compile()``d before
pytest runs; exit codes tested and never output text; and the restore registered
with ``atexit`` AND a signal handler, because a ``finally`` does not run when
the process is killed and this package has twice been left holding a
deliberately broken line.

Two files are mutated, because the defect surface spans both: the arithmetic in
``RVUtils/ConvexityRV/hw1f_sofr.py`` and the wiring in ``TB/IRSwapsTB.py``. One
of these mutants -- ``vol-mapping-drops-the-tail`` -- is a defect that was
actually shipped into the first draft and survived every 1Y-tail test.

Usage:  python notebooks/backtests/convexity_rv/_hl2_mutate.py
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
    "tests/test_convexity_rv_hw1f_sofr.py",
    "tests/test_irswaps_tb_model2.py",
    "tests/test_irswaps_tb_holee_model.py",
]
TB = "TB/IRSwapsTB.py"
HW = "RVUtils/ConvexityRV/hw1f_sofr.py"

_INFLIGHT: dict = {"path": None, "text": None}


def _restore(*_a) -> None:
    p, t = _INFLIGHT.get("path"), _INFLIGHT.get("text")
    if p is not None and t is not None:
        pathlib.Path(p).write_text(t, encoding="utf-8", newline="")
        _INFLIGHT["path"] = _INFLIGHT["text"] = None
        print(f"\n!! restored {p} on interrupt", flush=True)


atexit.register(_restore)
for _s in ("SIGINT", "SIGTERM", "SIGBREAK"):
    _sig = getattr(signal, _s, None)
    if _sig is not None:
        try:
            signal.signal(_sig, lambda *_a: (_restore(), sys.exit(130)))
        except (ValueError, OSError):                            # pragma: no cover
            pass


@dataclasses.dataclass
class Mutation:
    name: str
    old: str
    new: str
    expect: str
    path: str = TB


MUTATIONS = [
    # ---- the arithmetic ---------------------------------------------------
    Mutation("jensen-sign-flipped",
             '''    return math.expm1(mu + 0.5 * v) / (tau * float(fwd_discount))''',
             '''    return math.expm1(mu - 0.5 * v) / (tau * float(fwd_discount))''',
             "Monte Carlo settles the sign the paper prints as minus",
             path=HW),
    Mutation("drift-term-dropped",
             '''    mu = drift_term(sigma, a, t1, t2)
    if payoff == "average":''',
             '''    mu = 0.0
    if payoff == "average":''',
             "the alpha drift is most of the adjustment", path=HW),
    Mutation("compounding-variance-dropped",
             '''    v = compounding_var(sigma, a, t1, t2)''',
             '''    v = 0.0''',
             "the accrual's own diffusion is part of it", path=HW),
    Mutation("drift-uses-t1-not-the-accrual-window",
             '''    phi2 = b1 * b1 * tau + 2.0 * b1 * e1 * _j1(a, tau) + e1 * e1 * _j2(a, tau)''',
             '''    phi2 = b1 * b1 * tau''',
             "quadrature reproduces the whole integrand", path=HW),
    Mutation("pre-t1-variance-dropped",
             '''    pre = bt * bt * (t1 if a == 0.0 else -math.expm1(-2.0 * a * t1) / (2.0 * a))''',
             '''    pre = 0.0''',
             "diffusion before the accrual counts", path=HW),
    Mutation("j2-series-coefficient-wrong",
             '''        return tau ** 3 * (1.0 / 3.0 - u / 4.0 + 7.0 * u * u / 60.0 - u ** 3 / 24.0)''',
             '''        return tau ** 3 * (1.0 / 3.0 - u / 4.0 + 7.0 * u * u / 6.0 - u ** 3 / 24.0)''',
             "the series is checked against quadrature, not assumed", path=HW),
    Mutation("j1-series-dropped-to-leading-order",
             '''        return tau ** 2 * (0.5 - u / 6.0 + u * u / 24.0 - u ** 3 / 120.0)''',
             '''        return tau ** 2 * 0.5''',
             "the series must match the closed form at the seam", path=HW),
    Mutation("b-factor-loses-its-expm1",
             '''    return -math.expm1(-a * t) / a''',
             '''    return (1.0 - math.exp(-a * t)) / a''',
             "expm1 is the difference at small a*t", path=HW),
    Mutation("vol-mapping-drops-the-tail",
             '''    return vol * math.sqrt(expiry / var_x) * tail / b_factor(a, tail)''',
             '''    return vol * math.sqrt(expiry / var_x) / b_factor(a, tail)''',
             "SHIPPED ONCE: 16x at a 3M tail, invisible at 1Y", path=HW),
    Mutation("vol-mapping-drops-the-expiry-factor",
             '''    return vol * math.sqrt(expiry / var_x) * tail / b_factor(a, tail)''',
             '''    return vol * tail / b_factor(a, tail)''',
             "the mapping must reprice the straddle", path=HW),
    Mutation("payoff-ignored",
             '''    if payoff == "term":
        bt, b1 = b_factor(a, tau), b_factor(a, t1)''',
             '''    if False:
        bt, b1 = b_factor(a, tau), b_factor(a, t1)''',
             "term, average and compounded are three numbers", path=HW),
    Mutation("pack-is-a-sum-not-a-mean",
             '''    return float(np.mean(vals))''',
             '''    return float(np.sum(vals))''',
             "a pack rate is the AVERAGE of its contracts", path=HW),

    # ---- the wiring -------------------------------------------------------
    Mutation("model2-suffix-not-registered",
             '''CVX_MODEL_SUFFIXES: Tuple[str, ...] = (CVX_MODEL_SUFFIX, CVX_MODEL2_SUFFIX)''',
             '''CVX_MODEL_SUFFIXES: Tuple[str, ...] = (CVX_MODEL_SUFFIX,)''',
             "_MODEL2 must not fall through as a plain label"),
    Mutation("every-model-label-is-ho-lee",
             '''    return None if suf is None else CVX_MODEL_KINDS[suf]''',
             '''    return None if suf is None else "holee"''',
             "the suffix picks the MODEL"),
    Mutation("mean-reversion-not-in-the-key",
             '''        "cvx_mean_reversion": f"{float(mean_reversion):.10g}",''',
             '''        "cvx_mean_reversion": "fixed",''',
             "two mean reversions are two models"),
    Mutation("model2-shares-holees-model-name",
             '''        "cvx_model": "hw1f_sofr",''',
             '''        "cvx_model": "holee",''',
             "the two models must not share a fingerprint"),
    Mutation("per-contract-vols-collapse-to-the-mean",
             '''                        vols_bp = [float(provider(as_of, t1)) for t1 in t1s]''',
             '''                        vols_bp = [float(provider(as_of, sum(t1s) / len(t1s)))
                                   for _ in t1s]''',
             "each contract is calibrated at its OWN expiry"),
    Mutation("t2-hard-coded-at-a-quarter",
             '''        t1s.append((imm_d - as_of).days / 365.0)
        t2s.append((nxt_d - as_of).days / 365.0)''',
             '''        t1s.append((imm_d - as_of).days / 365.0)
        t2s.append((imm_d - as_of).days / 365.0 + 0.25)''',
             "IMM to IMM is not 0.25 and the weight is quadratic in T2"),
    Mutation("vol-tail-ignored-by-the-wiring",
             '''        vol_tail = _cvx_expiry_years(vol_tenor)''',
             '''        vol_tail = 1.0''',
             "model_vol_tenor reaches the mapping"),
    Mutation("kind-not-validated",
             '''        if kind not in set(CVX_MODEL_KINDS.values()):''',
             '''        if False:''',
             "an unknown kind raises rather than pricing Ho-Lee"),
    Mutation("both-models-write-the-same-column",
             '''        suffix = CVX_MODEL_SUFFIX if kind == "holee" else CVX_MODEL2_SUFFIX''',
             '''        suffix = CVX_MODEL_SUFFIX''',
             "the column name carries the model"),
    Mutation("only-ho-lee-is-dispatched",
             '''        for _kind in ("holee", "hw1f_sofr"):''',
             '''        for _kind in ("holee",):''',
             "a _MODEL2 request returns its frames"),
    Mutation("injected-provider-shares-the-builtin-key",
             '''        _injected = vol_provider is not None
        if _injected:
            _named = str(vol_source) != _CVX_BUILTIN_VOL_SOURCE
            vol_source = f"injected:{vol_source}"''',
             '''        _injected = vol_provider is not None
        if _injected:
            _named = str(vol_source) != _CVX_BUILTIN_VOL_SOURCE''',
             "SHIPPED ONCE: a provider run overwrote the built-in model's rows"),
    Mutation("unnamed-provider-is-persisted-anyway",
             '''                    if _injected and not _named:
                        continue''',
             '''                    if False:
                        continue''',
             "two unnamed providers would share one key"),
    Mutation("mean-reversion-knob-not-plumbed",
             '''                mean_reversion=model2_mean_reversion,
                payoff=model2_payoff,''',
             '''                mean_reversion=CVX_MODEL2_MEAN_REVERSION,
                payoff=CVX_MODEL2_PAYOFF,''',
             "the caller's knobs reach the model"),
]


def _normalise(text: str, sample: str) -> str:
    return text.replace("\n", "\r\n") if "\r\n" in sample else text


def run_suites() -> int:
    env = dict(os.environ, ARBS_SUPABASE_ENABLED="0")
    p = subprocess.run([PY, "-m", "pytest", *SUITES, "-q", "-x",
                        "-p", "no:randomly", "-p", "no:cacheprovider",
                        "--no-header", "-W", "ignore"],
                       cwd=REPO, env=env, capture_output=True, text=True)
    return p.returncode


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    if run_suites() != 0:
        print("BASELINE IS RED -- fix before mutating")
        sys.exit(1)
    print("baseline: green\n")

    results, matched = [], 0
    for m in MUTATIONS:
        f = REPO / m.path
        original = f.read_text(encoding="utf-8", newline="")
        old = _normalise(m.old, original)
        new = _normalise(m.new, original)
        hits = original.count(old)
        if hits != 1:
            results.append((m.name, f"ANCHOR-MISS ({hits} hits)", m.expect))
            print(f"{m.name:44s} ANCHOR-MISS ({hits} hits)")
            continue
        matched += 1
        mutant = original.replace(old, new)
        try:
            compile(mutant, str(f), "exec")
        except SyntaxError as exc:
            results.append((m.name, f"INVALID ({exc.msg})", m.expect))
            print(f"{m.name:44s} INVALID -- does not compile")
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
        print(f"{m.name:44s} {verdict:9s} ({m.expect})")

    after = run_suites()
    killed = sum(1 for _, v, _ in results if v == "KILLED")
    print(f"\nanchors matched {matched}/{len(MUTATIONS)}")
    print(f"killed {killed}/{matched}")
    print(f"restored tree re-runs {'GREEN' if after == 0 else 'RED'} (exit {after})")
    for n, v, e in results:
        if v != "KILLED":
            print(f"  NOT KILLED: {n:44s} {v}  ({e})")
    if after != 0:
        sys.exit(2)
    if killed != matched:
        sys.exit(3)


if __name__ == "__main__":
    main()
