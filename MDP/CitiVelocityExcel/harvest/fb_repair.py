r"""Re-harvest the nodes that failed during the main walk.

All 5 failures were the sub-types under RATES.SWAP_LIBOR.HUF - a transient UIA
failure on one currency, not a structural gap. Retries each from a clean descent.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import fb_harvest2 as H  # noqa: E402

OUT = pathlib.Path(__file__).parent / "dag_rates.json"


def main():
    doc = json.loads(OUT.read_text())
    tree = doc["tree"]
    broken = [k for k, v in tree.items() if v.get("error")]
    if not broken:
        print("nothing to repair")
        return 0
    print(f"repairing {len(broken)} nodes", flush=True)

    br = H.Browser(H.HWND)
    fixed = failed = 0
    for key in broken:
        path = key.split(" / ")
        for attempt in range(3):
            br.current = []                      # force a full re-descent
            kids = br.select_path(path)
            if isinstance(kids, dict) or kids is None:
                continue
            tree[key] = {"depth": len(path) - 1, "n": len(kids), "children": kids}
            print(f"  OK  {path[-1]}  n={len(kids)}", flush=True)
            fixed += 1
            break
        else:
            print(f"  FAIL {path[-1]} (still unreachable)", flush=True)
            failed += 1
        OUT.write_text(json.dumps(doc, indent=1))

    OUT.write_text(json.dumps(doc, indent=1))
    print(f"\nfixed={fixed} still_failed={failed}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
