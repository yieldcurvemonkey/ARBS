r"""Derive a per-family GRAMMAR from the harvested DAG, and enumerate from it.

Why not keep walking: RATES.XCCY_OIS_SWAP is ccy1 -> ccy2 -> SPOT -> tenor -> leg,
one leaf per node - ~20,000 UI selections at ~8s each to enumerate a grammar that
is just "tenor x {BASE_LEG, SPREAD_LEG}". The walk should learn the SHAPE; the
enumeration should then be generated and validated in bulk through CVTSHIST
(15 tags per call), which is orders of magnitude cheaper.

Edges actually observed in the walk are preferred over the full cross product, so
we do not invent parent/child combinations that never existed (e.g. currency pairs
that are not quoted).
"""

from __future__ import annotations

import collections
import itertools
import json
import pathlib

SCRATCH = pathlib.Path(__file__).parent


def load_tree() -> dict:
    tree = {}
    for f in ("dag_rates.json", "dag_rates_deep.json"):
        p = SCRATCH / f
        if p.exists():
            tree.update(json.loads(p.read_text())["tree"])
    return tree


def seg_after(parent: str, child: str) -> str | None:
    """The single new segment child adds to parent."""
    if not child.startswith(parent + "."):
        return None
    return child[len(parent) + 1:].split(".")[0]


def build_grammar(tree: dict) -> dict:
    """family -> {level -> sorted vocabulary}, plus observed parent->child edges."""
    vocab = collections.defaultdict(lambda: collections.defaultdict(set))
    edges = collections.defaultdict(set)
    for key, node in tree.items():
        parts = key.split(" / ")
        if len(parts) < 2:
            continue
        fam, parent = parts[1], parts[-1]
        for child in node.get("children", []) or []:
            s = seg_after(parent, child)
            if s:
                vocab[fam][len(parts)].add(s)
                edges[parent].add(child)
    return {
        "vocab": {f: {str(d): sorted(v) for d, v in lv.items()} for f, lv in vocab.items()},
        "edges": {k: sorted(v) for k, v in edges.items()},
    }


def enumerate_family(g: dict, fam: str, max_tags: int | None = None) -> list[str]:
    """Expand a family: walk observed edges as deep as they go, then take the
    cross product of the remaining level vocabularies."""
    vocab = {int(d): v for d, v in g["vocab"].get(fam, {}).items()}
    edges = g["edges"]
    if not vocab:
        return []
    frontier = [fam]
    depth = 2
    out: list[str] = []
    while depth in vocab:
        nxt = []
        for node in frontier:
            known = edges.get(node)
            if known:
                nxt.extend(known)
            else:
                nxt.extend(f"{node}.{s}" for s in vocab[depth])
        frontier = nxt
        depth += 1
        if max_tags and len(frontier) > max_tags:
            frontier = frontier[:max_tags]
    return sorted(set(frontier))


def main():
    tree = load_tree()
    g = build_grammar(tree)
    (SCRATCH / "rates_grammar.json").write_text(json.dumps(g, indent=1))

    fams = sorted(g["vocab"])
    print(f"grammar for {len(fams)} families -> rates_grammar.json\n")
    print(f"{'FAMILY':<26}{'levels':>7}{'vocab sizes':>28}{'enumerated':>12}")
    total = 0
    sizes = {}
    for f in fams:
        lv = {int(d): v for d, v in g["vocab"][f].items()}
        tags = enumerate_family(g, f)
        sizes[f] = len(tags)
        total += len(tags)
        vs = "x".join(str(len(lv[d])) for d in sorted(lv))
        print(f"{f.replace('RATES.',''):<26}{len(lv):>7}{vs:>28}{len(tags):>12,}")
    print(f"\ntotal enumerated candidates: {total:,}")
    json.dump(sizes, open(SCRATCH / "grammar_sizes.json", "w"), indent=1)


if __name__ == "__main__":
    main()
