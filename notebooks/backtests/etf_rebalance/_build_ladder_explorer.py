"""Inline the ladder dataset into the explorer page.

The Artifact CSP blocks every external request, so the data cannot be fetched at
runtime -- it has to travel inside the document. This substitutes the JSON into the
``__PAYLOAD__`` placeholder of ``ladder_explorer.html`` and writes the standalone page.

``<`` is escaped even though the payload is numeric: a literal ``</script>`` anywhere
inside a script element ends it, and the difference between "this data happens to
contain no angle brackets today" and "it cannot break the page" is one replace call.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "ladder_explorer.html")
DATA = os.path.join(HERE, "_data", "ladder_explorer.json")
OUT = os.path.join(HERE, "ladder_explorer.build.html")


def main() -> int:
    tpl = open(SRC, encoding="utf-8").read()
    if "__PAYLOAD__" not in tpl:
        print("template has no __PAYLOAD__ placeholder", file=sys.stderr)
        return 1
    payload = open(DATA, encoding="utf-8").read()
    payload = payload.replace("<", "\\u003c")

    html = tpl.replace("__PAYLOAD__", payload)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(html)

    mb = os.path.getsize(OUT) / 1e6
    print(f"wrote {OUT}  {mb:.2f} MB")
    if mb > 15.0:
        print(f"WARNING: {mb:.1f} MB is close to the 16 MB artifact ceiling", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
