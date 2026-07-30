"""Splice generated content into a hand-written report, between explicit markers.

So the findings document is ONE file — prose written by hand, tables generated from the
artifacts — rather than a narrative that refers vaguely to a pile of CSVs. The point of
the marker discipline is that regenerating can only ever touch the marked region: a
missing or malformed marker is an error, never an append, because silently appending
would leave the previous generation in place above the new one and a reader would have
no way to tell which numbers were current.
"""
from __future__ import annotations

import os


def markers(name: str) -> tuple[str, str]:
    return f"<!-- BEGIN {name} -->", f"<!-- END {name} -->"


class MarkerError(RuntimeError):
    """The target file's markers are missing, duplicated or out of order."""


def splice(text: str, name: str, body: str) -> str:
    """Return ``text`` with the region between ``name``'s markers replaced by ``body``.

    Raises rather than guessing. Every failure mode here silently produces a document
    with two generations of numbers in it, which is worse than not regenerating at all.
    """
    begin, end = markers(name)
    if text.count(begin) != 1 or text.count(end) != 1:
        raise MarkerError(
            f"expected exactly one {begin} and one {end}; found "
            f"{text.count(begin)} and {text.count(end)}")
    i, j = text.index(begin), text.index(end)
    if j < i:
        raise MarkerError(f"{end} appears before {begin}")
    return f"{text[:i]}{begin}\n\n{body.strip()}\n\n{text[j:]}"


def inject(path: str, name: str, body: str) -> str:
    """Splice ``body`` into the file at ``path`` in place. Returns the new text."""
    if not os.path.exists(path):
        raise MarkerError(f"target does not exist: {path}")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    out = splice(text, name, body)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(out)
    return out
