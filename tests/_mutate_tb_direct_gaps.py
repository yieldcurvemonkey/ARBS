"""Prove the two newly-covered direct-mode guarantees are actually covered.

Both were sold in the docstrings and tested nowhere, and a verifier showed each one
surviving a mutation with the whole file green. This re-runs those exact mutations
against the new tests.

Run: python tests/_mutate_tb_direct_gaps.py
"""
from __future__ import annotations

import io
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
TESTS = REPO / "tests" / "test_tb_direct_citivelo.py"
PY = sys.executable

QUOTES = REPO / "MDP" / "CitiVelocityExcel" / "quotes.py"
PRICER = REPO / "MDP" / "CitiVelocityExcel" / "pricer.py"

CRLF = "\r\n"
LF = "\n"


def _read(path):
    """Return ``(normalised_text, was_crlf)``.

    Two failure modes to avoid at once, and I hit both getting here.

    Reading in text mode TRANSLATES line endings, so writing the file back "unchanged"
    rewrote every line in a file the script was supposed to leave alone -- it showed up
    as two modified files with an empty content diff. Reading with ``newline=""`` fixes
    that but breaks matching, because the patterns below are written with plain newlines
    and would never match a CRLF file: every mutation silently becomes FIND-MISSING,
    which reads like a clean run rather than a broken harness.

    So: preserve on read, normalise for matching, and restore the original ending on
    write.
    """
    raw = io.open(path, encoding="utf-8", newline="").read()
    return raw.replace(CRLF, LF), (CRLF in raw)


def _write(path, text, crlf):
    io.open(path, "w", encoding="utf-8", newline="").write(
        text.replace(LF, CRLF) if crlf else text
    )


MUTATIONS = [
    (
        QUOTES,
        "a direct read banks into the DEFAULT cache root",
        "            reasons.update(client.last_failures())",
        "            from MDP.CitiVelocityExcel.cache import CitiVeloTagCache as _TC\n"
        "            _bank = _TC()\n"
        "            for _t, _s in got.items():\n"
        "                try:\n"
        "                    _bank.write(_t, freq_token, _s, price_point=point_token)\n"
        "                except Exception:\n"
        "                    pass\n"
        "            reasons.update(client.last_failures())",
        "test_direct_writes_nothing_to_the_DEFAULT_cache_root_either",
    ),
    (
        PRICER,
        "the absence memo is honoured even under a direct read",
        "        if not self.direct:\n"
        "            # See __init__: the absence memo is a silent fallback under a direct\n"
        "            # read, so a direct pricer re-asks the wire every time.\n"
        "            wanted = [t for t in wanted if t not in self._missing]",
        "        if True:\n"
        "            wanted = [t for t in wanted if t not in self._missing]",
        "test_direct_switches_off_the_pricers_absence_memo",
    ),
]


def run(nodeid: str) -> bool:
    """True when the test PASSES."""
    p = subprocess.run(
        [PY, "-m", "pytest", f"{TESTS}::{nodeid}", "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    return p.returncode == 0


def main() -> int:
    originals = {path: _read(path) for path, *_ in MUTATIONS}
    rows, escaped = [], 0
    try:
        for path, label, find, repl, nodeid in MUTATIONS:
            src, crlf = originals[path]
            if find not in src:
                rows.append((label, "FIND-MISSING"))
                escaped += 1
                continue
            _write(path, src.replace(find, repl, 1), crlf)
            passed = run(nodeid)
            _write(path, src, crlf)
            rows.append((label, "ESCAPED" if passed else "caught"))
            if passed:
                escaped += 1
    finally:
        for path, (src, crlf) in originals.items():
            _write(path, src, crlf)

    width = max(len(r[0]) for r in rows)
    print()
    for label, res in rows:
        print(f"{label.ljust(width)}  {res}")
    print(f"\n{len(rows) - escaped}/{len(rows)} caught")
    if escaped:
        print("ESCAPED mutations are untested claims. Fix the test, not the verdict.")
    return 1 if escaped else 0


if __name__ == "__main__":
    sys.exit(main())
