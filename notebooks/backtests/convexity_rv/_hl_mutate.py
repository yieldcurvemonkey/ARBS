r"""Mutation harness for the ``<LABEL>_MODEL`` path in ``TB/IRSwapsTB.py``.

A test suite that does not fail when you break the code it covers is measuring
nothing. This plants one defect at a time on the load-bearing lines and reports
KILLED / SURVIVED / INVALID / ANCHOR-MISS.

The lessons this repo has already paid for are built in: anchors normalised to
the file's own line ending; every mutant ``compile()``d before pytest runs; exit
codes tested and never output text; and the restore registered with ``atexit``
AND a signal handler, because a ``finally`` does not run when the process is
killed and this package has twice been left holding a deliberately broken line.

Usage:  python notebooks/backtests/convexity_rv/_hl_mutate.py
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
SUITES = ["tests/test_irswaps_tb_holee_model.py"]
TB = "TB/IRSwapsTB.py"

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
    # ---- the cache-collision guard: the one bug that would be invisible ----
    Mutation("model-marker-dropped-from-the-fingerprint",
             '''    return {
        "cvx_model": "holee",
        "cvx_convention": str(convention),
        "cvx_vol_source": str(vol_source),
        "cvx_vol_tenor": str(vol_tenor),
        "cvx_vol_interp": str(vol_interp),
    }''',
             '''    return {
        "matched_frequency": "Q",
        "matched_leg2_frequency": "Q",
    }''',
             "model and observed queries must not share a fingerprint"),
    Mutation("vol-source-not-in-the-key",
             '''        "cvx_vol_source": str(vol_source),''',
             '''        "cvx_vol_source": "fixed",''',
             "changing the model must orphan, not serve"),

    # ---- suffix handling: the intraday-safety property --------------------
    Mutation("resolver-learns-the-suffix",
             '''def _cvx_ranks_for_label(label: str) -> Optional[List[int]]:
    r = _cvx_cm_rank(label)''',
             '''def _cvx_ranks_for_label(label: str) -> Optional[List[int]]:
    label = _cvx_model_base(label)[0]
    r = _cvx_cm_rank(label)''',
             "the RESOLVERS must stay suffix-blind"),
    Mutation("tag-does-not-strip-the-suffix",
             '''    base, _ = _cvx_model_base(label)
    if _cvx_is_imm(base) or _cvx_cm_rank(base):''',
             '''    base = str(label).strip().upper()
    if _cvx_is_imm(base) or _cvx_cm_rank(base):''',
             "the column tag must resolve on the base"),
    Mutation("bare-suffix-becomes-a-label",
             '''    if up.endswith(CVX_MODEL_SUFFIX) and len(up) > len(CVX_MODEL_SUFFIX):''',
             '''    if up.endswith(CVX_MODEL_SUFFIX):''',
             "`_MODEL` alone is not a structure"),

    # ---- the vol ----------------------------------------------------------
    Mutation("vol-snapped-instead-of-interpolated",
             '''        return float(_np.interp(float(t1_mean), xs, ys))''',
             '''        return float(ys[int(_np.argmin(_np.abs(xs - float(t1_mean))))])''',
             "the vol is interpolated linearly in expiry"),
    Mutation("skew-rows-read-as-atmf",
             '''    atm = panel[panel["offset_bp"] == 0.0].copy()''',
             '''    atm = panel.copy()''',
             "only the ATMF offset is the model vol"),
    Mutation("bad-vol-accepted",
             '''                    if not (sigma_bp == sigma_bp) or sigma_bp <= 0.0:''',
             '''                    if False:''',
             "a non-finite or non-positive vol is a failure"),

    # ---- the model --------------------------------------------------------
    Mutation("expired-contract-priced",
             '''                    if not t1s or min(t1s) <= 0.0:''',
             '''                    if not t1s:''',
             "T1 <= 0 is a failure, not a price"),
    Mutation("holee-scale",
             '''    return float(pack_ca_bp(float(sigma_bp), list(t1s), convention=convention))''',
             '''    return float(pack_ca_bp(float(sigma_bp), list(t1s), convention=convention)) * 2.0''',
             "the model is the Ho-Lee arithmetic"),
    Mutation("convention-ignored",
             '''    return float(pack_ca_bp(float(sigma_bp), list(t1s), convention=convention))''',
             '''    return float(pack_ca_bp(float(sigma_bp), list(t1s), convention="hull"))''',
             "citi and hull are different numbers"),
    Mutation("mean-t1-becomes-the-front",
             '''                    t1_mean = float(sum(t1s) / len(t1s))''',
             '''                    t1_mean = float(t1s[0])''',
             "the vol is read at the structure's MEAN expiry"),
    Mutation("expiry-months-parsed-as-years",
             '''_CVX_EXPIRY_UNIT_YEARS = {"D": 1.0 / 365.0, "W": 7.0 / 365.0, "M": 1.0 / 12.0,
                          "Y": 1.0}''',
             '''_CVX_EXPIRY_UNIT_YEARS = {"D": 1.0 / 365.0, "W": 7.0 / 365.0, "M": 1.0,
                          "Y": 1.0}''',
             "18M is 1.5 years"),

    # ---- wiring -----------------------------------------------------------
    Mutation("unresolvable-label-returns-empty",
             '''            if not (_cvx_is_imm(base) or _cvx_ranks_for_label(base)):
                raise ValueError(''',
             '''            if False:
                raise ValueError(''',
             "an unknown base raises rather than vanishing"),
    Mutation("intraday-accepts-a-model-label",
             '''        _model_labels = [i for i in items if _cvx_model_base(i)[1]]
        if _model_labels:''',
             '''        _model_labels = []
        if _model_labels:''',
             "the intraday path refuses a model label"),
    Mutation("model-frames-dropped-on-a-model-only-request",
             '''        if not plain_items:
            if not out_frames_cached:
                return pd.DataFrame()
            return pd.concat(out_frames_cached, axis=1).sort_index(kind="mergesort")''',
             '''        if not plain_items:
            return pd.DataFrame()''',
             "a model-only request returns its frames"),
    Mutation("model-values-never-written",
             '''            if pending:
                with self.batched():''',
             '''            if False:
                with self.batched():''',
             "the second call is served from cache"),
    Mutation("ignore-cache-still-reads",
             '''                if ignore_cache:
                    misses.append((label, base, colname, dts))
                    continue''',
             '''                if False:
                    misses.append((label, base, colname, dts))
                    continue''',
             "ignore_cache recomputes"),
    Mutation("cached-reader-accepts-a-string",
             '''            try:
                return float(rec[colname])
            except (TypeError, ValueError):
                return None''',
             '''            try:
                return float(rec[colname])
            except (TypeError, ValueError):
                return 0.0''',
             "an unparseable cached record is a miss"),
]


def _normalise(text: str, sample: str) -> str:
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
