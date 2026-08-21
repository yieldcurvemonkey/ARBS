r"""Mutation check for ``tests/test_convexity_rv_shared_ca_path.py``.

A suite that does not fail when you break the code it covers is measuring
nothing. Three defects were fixed in the shared convexity-adjustment path; this
re-introduces each one and asserts the suite catches it.

Three failure modes this harness is written to avoid, all of them observed in
this codebase before:

* **CRLF.** Anchors written with ``\n`` match nothing in a CRLF checkout and the
  run reports "ANCHOR NOT FOUND", which reads almost like a pass. Every anchor is
  normalised to the file's own line ending and the **match count is printed**.
* **Syntax breaks score as kills.** A mutant that does not compile makes pytest
  fail at collection, which looks identical to a caught mutation. Every mutant is
  ``compile()``d first and a failure there is reported as INVALID, not as a kill.
* **Testing output text instead of exit codes.** The verdict is pytest's return
  code, never a grep of its stdout.

Run:
    C:/Users/chris/anaconda3/envs/stir/python.exe \
        notebooks/backtests/convexity_rv/_mutate_shared_ca_path.py
"""

from __future__ import annotations

import io
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
SUITE = "tests/test_convexity_rv_shared_ca_path.py"

VALUE = REPO / "Query" / "IRSwaps" / "IRSwapValue.py"
TB = REPO / "TB" / "IRSwapsTB.py"
UTILS = (REPO / "MDP" / "IRSwaps" / "SDR_INTRADAY" / "rl_curve_utils"
         / "stir_curve_building_utils.py")

#: (name, file, anchor, replacement, defect, expected occurrences)
MUTATIONS = [
    (
        "matched-swap frequency reverts to the usd_irs spec default",
        VALUE,
        'matched_frequency = kwargs.get("matched_frequency", "Q")',
        'matched_frequency = kwargs.get("matched_frequency", None)',
        "the annual/annual matched swap, worth -4.6 to -5.9 bp",
        1,
    ),
    (
        "futures leg goes back through the magnitude heuristic",
        VALUE,
        "                return float(getattr(fr, \"real\", fr))",
        "                _v = float(getattr(fr, \"real\", fr))\n"
        "                return _v * 100.0 if abs(_v) < 1.0 else _v",
        "the 100x corruption of every sub-1 % SR3 rate",
        1,
    ),
    (
        "the daily price fetch fills by default again",
        UTILS,
        "    fill: bool = False,",
        "    fill: bool = True,",
        "bfill look-ahead and ffill fabrication in the price panel",
        1,
    ),
    (
        "per-date failures are swallowed again",
        TB,
        '                        _note_failure(label, dts, f"{type(exc).__name__}: {exc}")',
        "                        pass",
        "a failing date indistinguishable from an absent one",
        # both per-date loops were fixed identically, so this anchor is shared
        2,
    ),
]


def _read(p: pathlib.Path) -> tuple[str, str]:
    """Return (text, newline) with the file's own line ending preserved."""
    raw = io.open(p, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in raw else "\n"
    return raw, nl


def _run_suite() -> int:
    """pytest's EXIT CODE. Never a grep of its stdout."""
    proc = subprocess.run(
        [PY, "-m", "pytest", SUITE, "-q", "--no-header", "-x"],
        cwd=str(REPO), capture_output=True, text=True,
        env={**__import__("os").environ, "ARBS_SUPABASE_ENABLED": "0"},
    )
    return proc.returncode


def main() -> int:
    print(f"repo   : {REPO}")
    print(f"suite  : {SUITE}\n")

    baseline = _run_suite()
    print(f"BASELINE exit={baseline}  -> {'green' if baseline == 0 else 'RED, fix before mutating'}")
    if baseline != 0:
        return 1

    results = []
    for name, path, anchor, repl, defect, want in MUTATIONS:
        text, nl = _read(path)
        a = anchor.replace("\n", nl)
        r = repl.replace("\n", nl)
        n = text.count(a)
        print(f"\n--- {name}")
        print(f"    file    : {path.relative_to(REPO)}")
        print(f"    anchor  : matched {n} occurrence(s), expected {want}")
        if n != want:
            results.append((name, "ANCHOR-MISS", f"matched {n}, expected {want}"))
            continue

        mutant = text.replace(a, r)
        try:
            compile(mutant, str(path), "exec")
        except SyntaxError as exc:
            results.append((name, "INVALID", f"mutant does not compile: {exc}"))
            continue

        io.open(path, "w", encoding="utf-8", newline="").write(mutant)
        try:
            code = _run_suite()
        finally:
            io.open(path, "w", encoding="utf-8", newline="").write(text)

        verdict = "KILLED" if code != 0 else "SURVIVED"
        print(f"    pytest  : exit={code} -> {verdict}")
        results.append((name, verdict, defect))

    print("\n" + "=" * 78)
    survived = [r for r in results if r[1] != "KILLED"]
    for name, verdict, note in results:
        print(f"{verdict:12} {name}\n{'':12} re-introduces: {note}")
    print("=" * 78)
    print(f"killed {len(results) - len(survived)}/{len(results)}")

    post = _run_suite()
    print(f"POST-RESTORE exit={post} -> {'clean' if post == 0 else 'FILES NOT RESTORED'}")
    return 0 if (not survived and post == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
