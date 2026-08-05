r"""Prove the grammar -> generate -> bulk-validate loop.

Walking XCCY_OIS_SWAP to its leaves is ~20,000 UI selections at ~8s. Generating
from the grammar and validating through CVTSHIST is 15 tags per ~2s call - about
400x cheaper - and CVTSHIST is the authority anyway, since it is the path we fetch
on.

Runs exhaustively over the priority families small enough to finish now.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cv_probe import Prober  # noqa: E402
from grammar import build_grammar, enumerate_family, load_tree  # noqa: E402

SCRATCH = pathlib.Path(__file__).parent
CKPT = SCRATCH / "grammar_validation.json"

FAMILIES = [
    "RATES.REPO", "RATES.MIDCURVES", "RATES.SPREAD_OPTIONS",
    "RATES.INVOICESPREAD", "RATES.OIS_INVOICESPREAD", "RATES.VOL",
]
CONTROLS = ["RATES.OIS.USD_SOFR.PAR.10Y", "RATES.TSY.TSY.OTR.10Y.YIELD"]


def main():
    g = build_grammar(load_tree())
    plan = {f: enumerate_family(g, f) for f in FAMILIES}
    for f, t in plan.items():
        print(f"  {f:<28}{len(t):>7,} candidates")
    total = sum(len(t) for t in plan.values())
    print(f"  {'TOTAL':<28}{total:>7,}\n")

    p = Prober(CKPT, batch=15)
    try:
        ctl = p.probe_tshist(CONTROLS)
        bad = [t for t in CONTROLS if ctl[t]["status"] != "valid"]
        if bad:
            print("CONTROLS FAILED -> validator untrustworthy:", bad)
            return 1
        print("controls pass -> validator trustworthy\n")

        summary = {}
        for fam, tags in plan.items():
            res = p.probe_tshist(tags)
            ok = [t for t in tags if res[t]["status"] == "valid"]
            empty = [t for t in tags if res[t]["status"] == "empty"]
            summary[fam] = {"candidates": len(tags), "valid": len(ok),
                            "empty": len(empty), "tags": ok}
            print(f"{fam:<28} {len(ok):>6,}/{len(tags):<6,} valid "
                  f"({len(ok)/max(1,len(tags))*100:5.1f}%)  empty={len(empty)}", flush=True)
            if ok:
                print(f"    e.g. {ok[0]}  sample={res[ok[0]].get('sample')}", flush=True)
    finally:
        p.close()

    (SCRATCH / "verified_tags.json").write_text(json.dumps(summary, indent=1))
    tot_ok = sum(v["valid"] for v in summary.values())
    print(f"\nverified fetchable: {tot_ok:,} / {total:,}")
    print(f"written -> verified_tags.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
