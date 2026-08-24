"""Mutate a digit in the findings block and confirm the number audit FAILS.

The audit is a build gate, so it needs the same treatment every other guard here
gets: change the thing it checks and watch it fire. The executed notebook is
copied, one figure in its findings markdown is altered, the audit is run against
the copy, and the copy is deleted. The real notebook is never touched.
"""
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PY = sys.executable
NB = HERE / "fed_detachment_rv.ipynb"
TMP = HERE / "_audit_mutation_check.ipynb"

#: (figure as it appears in the prose, what to change it to). Each must be a
#: figure the tie-out cell prints, so a change breaks the match.
MUTATIONS = [
    ("**0.8864**", "**0.8865**"),          # the headline rotation p
    ("**0.2185**", "**0.2186**"),          # the observed best Sharpe
    ("**2600**", "**2601**"),              # the poisoned-row count
    ("**4.02772**", "**4.02773**"),        # the curve-store known answer
    ("**47.2%**", "**47.3%**"),            # a percentage
    # The BLIND CLASS the first version of the audit could not see at all: a
    # figure carrying a unit. Without one of these the harness passes while
    # never exercising the half of the regex that was wrong.
    ("+1.891bp", "+1.892bp"),              # the pre-registered result
    ("+6.783bp", "+6.784bp"),              # the FedLock SR3 winner
    ("7.105e-15", "7.106e-15"),            # the engine tie-out tolerance
]

#: Deliberately NOT in the list, and worth knowing why. Mutating ``**24.4bp**``
#: to ``**24.5bp**`` does NOT fail the audit, because the engine tie-out table
#: happens to print a trade P&L of ``-24.5`` and the audit matches by SUBSTRING.
#: That is the first of the four limits the audit documents, demonstrated rather
#: than asserted: a mutant that collides with an unrelated number elsewhere in
#: the output is invisible to it. Choose mutants that do not collide -- every
#: entry above was checked against the executed outputs first.



def run_audit(path: pathlib.Path) -> int:
    r = subprocess.run([PY, str(HERE / "_audit_fed_detachment_numbers.py"), str(path)],
                       capture_output=True, text=True)
    return r.returncode


def main() -> int:
    if not NB.exists():
        print(f"{NB} missing -- run run_fed_detachment.py first")
        return 1
    base = run_audit(NB)
    print(f"unmutated notebook: audit rc={base} ({'PASS' if base == 0 else 'FAIL'})")
    if base != 0:
        print("the audit already fails; fix that before mutation-testing it")
        return 1

    ok = True
    try:
        for old, new in MUTATIONS:
            nb = json.loads(NB.read_text(encoding="utf-8"))
            hits = 0
            for c in nb["cells"]:
                if c["cell_type"] != "markdown":
                    continue
                src = "".join(c["source"])
                if "What was measured" not in src or old not in src:
                    continue
                c["source"] = src.replace(old, new, 1).splitlines(keepends=True)
                hits += 1
                break
            if not hits:
                print(f"  PATTERN NOT FOUND {old!r} -- the audit cannot be tested on it")
                ok = False
                continue
            TMP.write_text(json.dumps(nb), encoding="utf-8")
            rc = run_audit(TMP)
            good = rc != 0
            ok &= good
            print(f"  {old} -> {new}: audit rc={rc} "
                  f"{'GUARD IS REAL (it failed)' if good else '*** VACUOUS: still passes ***'}")
    finally:
        TMP.unlink(missing_ok=True)

    print(f"\n{'all mutations caught' if ok else 'SOME MUTATIONS SLIPPED THROUGH'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
