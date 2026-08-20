"""Fold every non-ASCII character out of the explorer template.

The published page has no charset declaration of its own -- the artifact wrapper owns
``<head>`` -- so a raw UTF-8 byte in the source is at the mercy of whatever encoding the
host guesses. It guessed windows-1252 locally and rendered "10-20y" as "10 a EUR 20y".
Entities in markup and ``\\uXXXX`` escapes in script are encoding-independent, so the
page reads correctly whatever the host decides.
"""
from __future__ import annotations

import io
import sys

PATH = "ladder_explorer.html"

ENT = {
    "—": "&mdash;",
    "–": "&ndash;",
    "σ": "&sigma;",
    "·": "&middot;",
    "−": "&minus;",
    "±": "&plusmn;",
    "←": "&larr;",
    "→": "&rarr;",
}


def main() -> int:
    s = io.open(PATH, encoding="utf-8").read()
    marker = '<script type="application/json"'
    i = s.index(marker)
    head, tail = s[:i], s[i:]

    for k, v in ENT.items():
        head = head.replace(k, v)
    for k in ENT:
        tail = tail.replace(k, "\\u{:04x}".format(ord(k)))

    s = head + tail
    io.open(PATH, "w", encoding="utf-8", newline="").write(s)

    left = sorted({ch for ch in s if ord(ch) > 127})
    print("non-ASCII remaining:", [hex(ord(c)) for c in left] or "NONE")
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
