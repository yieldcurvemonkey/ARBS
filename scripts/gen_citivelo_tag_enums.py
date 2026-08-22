#!/usr/bin/env python
r"""Generate ``Query/CitiVelocity/tag_enums/`` from the committed Citi Velocity catalog.

    python scripts/gen_citivelo_tag_enums.py            # write
    python scripts/gen_citivelo_tag_enums.py --check    # fail if stale, write nothing

``--check`` is what ``tests/test_citivelo_tag_enums.py`` runs, so a catalog refresh
that is not followed by a regeneration fails the fast gate instead of silently
serving tags that no longer match the catalog. The staleness signal is a **hash of
the source JSON artefacts**, not a hand-maintained version number: a number a human
has to remember to bump gets bumped at the wrong moment, and the failure is silent
when it does.

What is generated, and why from ``expand()``
--------------------------------------------
One module per ``RATES.*`` family, containing a tree of
:class:`~Query.CitiVelocity.tag_enums._base.TagNamespace` classes whose leaves are
:class:`~Query.CitiVelocity.tag_enums._base.CitiVeloTag` enums. The universe is
:meth:`~MDP.CitiVelocityExcel.catalog.CitiVeloCatalog.expand` over every family -
the catalog's own path-consistent rule - rather than the flat ``leaves`` list in
``rates_catalog.json``, which is truncated above the tag level for ``VOL``,
``INFLATION`` and ``REPO``. That comparison is measured in the ``_base`` docstring.

Two invariants this script refuses to violate
---------------------------------------------
* **Name mangling must be injective inside every node.** Dots become underscores,
  so ``A.B_C`` and ``A_B.C`` would collide. It raises naming both tags rather than
  letting the second silently overwrite the first - a lost tag is invisible, and
  the enum would look complete.
* **Every emitted value must be byte-identical to a catalog tag.** Checked here
  and asserted again from the other side in the tests, because a generator that
  validates only its own output is checking nothing.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import io
import pathlib
import sys
from typing import Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from MDP.CitiVelocityExcel.catalog import CATALOG_DIR, CitiVeloCatalog  # noqa: E402
from Query.CitiVelocity.tag_enums._base import (  # noqa: E402
    MAX_FLAT_MEMBERS,
    TAG_PREFIX,
    mangle,
)

OUT_DIR = _REPO_ROOT / "Query" / "CitiVelocity" / "tag_enums"

#: The catalog artefacts the tag universe is derived from. Hashed, in this order,
#: to produce the fingerprint that ``--check`` compares. ``bond_*`` files are NOT
#: here: bonds are deliberately outside the enum (see the ``_base`` docstring), so
#: a weekly bond refresh must not mark the generated tree stale.
SOURCE_ARTEFACTS: Tuple[str, ...] = ("dag_rates_deep.json", "shapes2.json")

#: Hard ceiling per family, well above the largest real one (``VOL``, 26,233).
#: Present so a malformed catalog cannot make this script emit a 500 MB file.
MAX_TAGS_PER_FAMILY = 200_000

_HEADER = '''\
# fmt: off
# ruff: noqa: E501
# flake8: noqa
r"""{family} tags, generated from the Citi Velocity catalog. DO NOT EDIT BY HAND.

Regenerate with::

    python scripts/gen_citivelo_tag_enums.py

{count:,} tags under ``RATES.{family}``, arranged {shape}.

Edits to this file are lost on the next regeneration, and
``tests/test_citivelo_tag_enums.py`` fails the moment it disagrees with the
catalog - so there is no window in which a hand edit merely looks like it worked.
"""

from __future__ import annotations

from Query.CitiVelocity.tag_enums._base import CitiVeloTag, TagNamespace

__all__ = ["{family}"]

'''


# ------------------------------------------------------------------ #
#                        the universe and the tree                   #
# ------------------------------------------------------------------ #


def fingerprint(catalog_dir: pathlib.Path = CATALOG_DIR) -> str:
    """SHA-256 over the source artefacts, in a fixed order, with their names.

    Names are hashed alongside the bytes so that swapping two artefacts' contents
    changes the fingerprint. Hashing bytes alone would not notice.

    Line endings are normalised first. This repo has ``core.autocrlf=true`` and no
    ``.gitattributes``, so the same committed JSON lands as CRLF on one checkout
    and LF on another; hashing raw bytes would make the fingerprint a property of
    *how you cloned*, and the drift test would fail on a machine where nothing is
    actually stale. That failure would be indistinguishable from a real one, which
    is what makes it worth a line of code.
    """
    h = hashlib.sha256()
    for name in SOURCE_ARTEFACTS:
        path = catalog_dir / name
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def universe(catalog: Optional[CitiVeloCatalog] = None) -> Dict[str, List[str]]:
    """``{family: sorted tags}`` for all 33 families.

    Sorted, not catalog-iteration order: the generated source has to be stable
    across runs or every regeneration produces a diff that is pure noise and
    nobody reads it.
    """
    cat = catalog or CitiVeloCatalog.default()
    out: Dict[str, List[str]] = {}
    for family in cat.families():
        tags = cat.expand(f"{TAG_PREFIX}{family}", max_tags=MAX_TAGS_PER_FAMILY)
        bad = [t for t in tags if not t.startswith(f"{TAG_PREFIX}{family}")]
        if bad:
            raise ValueError(f"expand({family!r}) returned tags outside the family: {bad[:3]}")
        out[family] = sorted(tags)
    return out


class Node:
    """One node of the emitted tree: either a leaf enum or a namespace."""

    def __init__(self, path: str, tags: Sequence[str], depth: int):
        self.path = path
        self.tags = list(tags)
        self.depth = depth
        self.children: List["Node"] = []

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def count_classes(self) -> int:
        return 1 + sum(c.count_classes() for c in self.children)

    def max_leaf(self) -> int:
        if self.is_leaf:
            return len(self.tags)
        return max(c.max_leaf() for c in self.children)


def build_tree(path: str, tags: Sequence[str], *, threshold: int, depth: int = 0) -> Node:
    """Split on the next segment until every leaf holds ``threshold`` tags or fewer.

    A node stops splitting when it is small enough, when splitting would not
    actually divide it (one child), or at depth 8 - the last is a guard, not an
    expectation: the deepest real family is 6 segments.
    """
    node = Node(path, tags, depth)
    if len(tags) <= threshold or depth >= 8:
        return node

    seg_index = path.count(".") + 1
    groups: "collections.OrderedDict[str, List[str]]" = collections.OrderedDict()
    for tag in tags:
        parts = tag.split(".")
        if len(parts) <= seg_index:
            # A tag that terminates exactly at this node. It cannot become a
            # child namespace (there is no segment left), so the node keeps it
            # and stays a leaf. Asserted not to happen in practice by
            # `assert_no_prefix_tags`, but handled rather than assumed.
            return node
        groups.setdefault(parts[seg_index], []).append(tag)

    if len(groups) <= 1:
        return node

    node.children = [
        build_tree(f"{path}.{seg}", sub, threshold=threshold, depth=depth + 1)
        for seg, sub in groups.items()
    ]
    node.tags = []
    return node


def assert_no_prefix_tags(tags: Sequence[str]) -> None:
    """No tag may be a strict dotted prefix of another.

    If one were, the tree could not represent both: the shorter tag would need to
    be simultaneously a namespace and a member. Checked rather than hoped for.
    """
    seen = set(tags)
    offenders = []
    for tag in tags:
        head = tag
        while "." in head:
            head = head.rsplit(".", 1)[0]
            if head in seen:
                offenders.append((head, tag))
                break
    if offenders:
        raise ValueError(
            f"{len(offenders)} tag(s) are a dotted prefix of another tag, which the "
            f"namespace tree cannot represent: {offenders[:3]}"
        )


# ------------------------------------------------------------------ #
#                              emission                              #
# ------------------------------------------------------------------ #


def _member_names(node_path: str, tags: Sequence[str]) -> List[Tuple[str, str]]:
    """``(identifier, tag)`` for a leaf, raising on a mangling collision."""
    head = node_path + "."
    pairs: List[Tuple[str, str]] = []
    seen: Dict[str, str] = {}
    for tag in tags:
        if tag == node_path:
            suffix = ""
        elif tag.startswith(head):
            suffix = tag[len(head) :]
        else:
            raise ValueError(f"{tag!r} is not under {node_path!r}.")
        name = mangle(suffix)
        if name in seen:
            raise ValueError(
                f"Name collision under {node_path!r}: {seen[name]!r} and {tag!r} both mangle "
                f"to {name!r}. Dots become underscores, so this is possible whenever a segment "
                "already contains one. Fix the mangling rule rather than dropping a tag - a "
                "silently dropped tag makes the enum look complete when it is not."
            )
        seen[name] = tag
        pairs.append((name, tag))
    return pairs


def _emit_node(buf: io.StringIO, node: Node, class_name: str, indent: int) -> None:
    pad = " " * indent
    inner = " " * (indent + 4)
    if node.is_leaf:
        buf.write(f"{pad}class {class_name}(CitiVeloTag):\n")
        buf.write(f'{inner}"""{len(node.tags):,} tags under ``{node.path}``."""\n\n')
        buf.write(f'{inner}__node__ = "{node.path}"\n\n')
        for name, tag in _member_names(node.path, node.tags):
            buf.write(f'{inner}{name} = "{tag}"\n')
        buf.write("\n")
        return

    buf.write(f"{pad}class {class_name}(TagNamespace):\n")
    total = sum(len(c.tags) or 0 for c in node.children) or len(node.tags)
    n_tags = _count_tags(node)
    buf.write(
        f'{inner}"""{n_tags:,} tags under ``{node.path}``, in '
        f'{len(node.children)} group(s)."""\n\n'
    )
    buf.write(f'{inner}__node__ = "{node.path}"\n\n')
    for child in node.children:
        seg = child.path.rsplit(".", 1)[-1]
        _emit_node(buf, child, mangle(seg), indent + 4)


def _count_tags(node: Node) -> int:
    if node.is_leaf:
        return len(node.tags)
    return sum(_count_tags(c) for c in node.children)


def render_family(family: str, tags: Sequence[str], *, threshold: int) -> Tuple[str, Node]:
    """The full source of one family module, plus its tree (for the manifest)."""
    root = build_tree(f"{TAG_PREFIX}{family}", tags, threshold=threshold)
    shape = (
        "as one flat enum"
        if root.is_leaf
        else f"as {root.count_classes()} nested classes (largest leaf: {root.max_leaf():,})"
    )
    buf = io.StringIO()
    buf.write(_HEADER.format(family=family, count=len(tags), shape=shape))
    _emit_node(buf, root, family, 0)
    return buf.getvalue(), root


_INIT_HEADER = '''\
r"""Every Citi Velocity ``RATES.*`` tag the committed catalog can name, as enums.

GENERATED by ``scripts/gen_citivelo_tag_enums.py``. DO NOT EDIT BY HAND - see
:mod:`Query.CitiVelocity.tag_enums._base` for the design, the measured provenance
of the tag universe, and what this enum deliberately does not cover.

{total:,} tags across {n_families} families. Two equivalent entry points::

    from Query.CitiVelocity import CitiVeloQuery
    CitiVeloQuery(tag=CitiVeloQuery.Tags.OIS.USD_SOFR.PAR_10Y)

    from Query.CitiVelocity.tag_enums import OIS
    CitiVeloQuery(tag=OIS.USD_SOFR.PAR_10Y)

Nothing is imported until it is touched
---------------------------------------
Constructing all {total:,} enum members costs about {cost} and most callers want
one family. So the family modules are loaded on first attribute access, through
PEP 562 ``__getattr__`` here and a metaclass ``__getattr__`` on :class:`CitiVeloTags`.
The ``TYPE_CHECKING`` block below is what keeps that invisible to a language
server: the names are declared statically for completion, and never imported at
run time unless asked for.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, List, Tuple

from Query.CitiVelocity.tag_enums._base import (
    DEPRECATED_VOL_BRANCHES,
    MAX_FLAT_MEMBERS,
    TAG_PREFIX,
    CitiVeloTag,
    TagNamespace,
    family_of,
    mangle,
)
from Query.CitiVelocity.tag_enums._manifest import (
    CATALOG_FINGERPRINT,
    COUNTS,
    FAMILIES,
    GENERATED_FROM,
    TOTAL,
)

'''


def render_init(families: Sequence[str], counts: Dict[str, int], cost: str) -> str:
    buf = io.StringIO()
    buf.write(_INIT_HEADER.format(total=sum(counts.values()), n_families=len(families), cost=cost))

    buf.write("if TYPE_CHECKING:  # pragma: no cover - completion only, never imported at run time\n")
    for family in families:
        buf.write(f"    from Query.CitiVelocity.tag_enums.{family.lower()} import {family} as {family}\n")
    buf.write("\n\n")

    buf.write("_MODULES = {\n")
    for family in families:
        buf.write(f'    "{family}": "{family.lower()}",\n')
    buf.write("}\n\n\n")

    buf.write(_INIT_BODY)
    return buf.getvalue()


_INIT_BODY = '''\
def _load(family: str) -> Any:
    """Import one family module and return its root node."""
    module = importlib.import_module(f"{__name__}.{_MODULES[family]}")
    return getattr(module, family)


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute access for the 33 family roots."""
    if name in _MODULES:
        value = _load(name)
        globals()[name] = value  # cache: this module's __getattr__ runs once per family
        return value
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}. Families: {', '.join(FAMILIES)}."
    )


def __dir__() -> List[str]:
    return sorted(set(globals()) | set(_MODULES) | set(__all__))


class _TagsMeta(type):
    """Gives :class:`CitiVeloTags` the same lazy attribute access as the module."""

    def __getattr__(cls, name: str) -> Any:
        if name in _MODULES:
            value = _load(name)
            setattr(cls, name, value)
            return value
        raise AttributeError(
            f"{cls.__name__} has no family {name!r}. Families: {', '.join(FAMILIES)}."
        )

    def __dir__(cls) -> List[str]:
        return sorted(set(type.__dir__(cls)) | set(_MODULES))

    def __iter__(cls):
        for family in FAMILIES:
            yield _load(family)

    def __len__(cls) -> int:
        return len(FAMILIES)


class CitiVeloTags(metaclass=_TagsMeta):
    """The whole tag tree, one attribute per ``RATES.*`` family.

    Re-exported as :attr:`Query.CitiVelocity.CitiVeloQuery.CitiVeloQuery.Tags`, so
    the enum is reachable from the query class a caller already imported::

        >>> from Query.CitiVelocity import CitiVeloQuery            # doctest: +SKIP
        >>> CitiVeloQuery(tag=CitiVeloQuery.Tags.OIS.USD_SOFR.PAR_10Y)   # doctest: +SKIP

    Every family attribute is either a :class:`TagNamespace` or a
    :class:`CitiVeloTag` enum, and both answer ``node()``, ``children()``,
    ``tags()``, ``search()`` and ``find()`` - so walking the tree never has to
    branch on which one it found.
    """

    if TYPE_CHECKING:  # pragma: no cover - completion only
{annotations}

    #: SHA-256 of the catalog artefacts these tags were generated from.
    FINGERPRINT = CATALOG_FINGERPRINT
    #: ``{family: tag count}``.
    COUNTS = COUNTS
    #: Every family name, in catalog order.
    FAMILIES = FAMILIES
    #: Total tags across every family.
    TOTAL = TOTAL

    def __init__(self) -> None:  # pragma: no cover - defensive
        raise TypeError("CitiVeloTags is a namespace, not a value. Reach through it: CitiVeloTags.OIS")

    # -- whole-tree helpers -------------------------------------------

    @staticmethod
    def family(name: str) -> Any:
        """The root node of one family, by name.

        >>> CitiVeloTags.family("OIS").node()        # doctest: +SKIP
        'RATES.OIS'
        """
        key = str(name).upper()
        if key.startswith(TAG_PREFIX):
            key = family_of(key)
        if key not in _MODULES:
            raise KeyError(f"{name!r} is not a Citi Velocity family. Families: {', '.join(FAMILIES)}.")
        return _load(key)

    @staticmethod
    def find(tag: str) -> CitiVeloTag:
        """Resolve any tag string to its member, loading only that family.

        The inverse of the one-way name mangling, and the reason the tree's
        variable depth never blocks anyone: you do not need to know how deep a tag
        sits, or how its name was spelled, to get the typed member back.

        >>> CitiVeloTags.find("RATES.OIS.USD_SOFR.PAR.10Y")      # doctest: +SKIP
        <PAR_10Y: 'RATES.OIS.USD_SOFR.PAR.10Y'>
        """
        return CitiVeloTags.family(family_of(str(tag))).find(str(tag))

    @staticmethod
    def search(pattern: str, *, family: str = "", limit: int = 200) -> List[CitiVeloTag]:
        """Members matching a glob, a ``/regex/`` or a substring.

        Scope it with ``family=`` when you can. Unscoped, this loads **every**
        family, which is the one operation in this package that is not cheap; the
        cost is stated rather than hidden because a search in a loop would
        otherwise look free.
        """
        if family:
            return CitiVeloTags.family(family).search(pattern, limit=limit)
        out: List[CitiVeloTag] = []
        for name in FAMILIES:
            out.extend(_load(name).search(pattern, limit=limit))
            if len(out) >= limit:
                break
        return out[:limit]

    @staticmethod
    def counts() -> Tuple[Tuple[str, int], ...]:
        """``(family, tag count)`` biggest first, without importing anything."""
        return tuple(sorted(COUNTS.items(), key=lambda kv: (-kv[1], kv[0])))


__all__ = [
    "CitiVeloTag",
    "CitiVeloTags",
    "TagNamespace",
    "CATALOG_FINGERPRINT",
    "COUNTS",
    "DEPRECATED_VOL_BRANCHES",
    "FAMILIES",
    "GENERATED_FROM",
    "MAX_FLAT_MEMBERS",
    "TAG_PREFIX",
    "TOTAL",
    "family_of",
    "mangle",
] + list(_MODULES)
'''


_MANIFEST = '''\
r"""What the generated tag tree was built from. DO NOT EDIT BY HAND.

:data:`CATALOG_FINGERPRINT` is a SHA-256 over the catalog artefacts listed in
:data:`GENERATED_FROM`. ``tests/test_citivelo_tag_enums.py`` recomputes it, so a
catalog refresh that is not followed by ``python scripts/gen_citivelo_tag_enums.py``
fails the fast gate rather than silently leaving the enum describing a catalog
that no longer exists.

The fingerprint is derived from the inputs on purpose. A hand-maintained version
number is bumped by whoever remembers, which is exactly the moment they do not.
"""

from __future__ import annotations

from typing import Dict, Tuple

__all__ = ["CATALOG_FINGERPRINT", "COUNTS", "FAMILIES", "GENERATED_FROM", "TOTAL", "THRESHOLD"]

#: SHA-256 over ``GENERATED_FROM``, in that order, names included.
CATALOG_FINGERPRINT = "{fingerprint}"

#: The catalog artefacts hashed into the fingerprint.
GENERATED_FROM: Tuple[str, ...] = {sources!r}

#: The split threshold in force when this tree was emitted.
THRESHOLD = {threshold}

#: Every family, in catalog order.
FAMILIES: Tuple[str, ...] = (
{families}
)

#: ``{{family: tag count}}``. Available without importing any family module.
COUNTS: Dict[str, int] = {{
{counts}
}}

#: Total tags across every family.
TOTAL = {total}
'''


def render_manifest(
    families: Sequence[str], counts: Dict[str, int], *, fp: str, threshold: int
) -> str:
    return _MANIFEST.format(
        fingerprint=fp,
        sources=SOURCE_ARTEFACTS,
        threshold=threshold,
        families="\n".join(f'    "{f}",' for f in families),
        counts="\n".join(f'    "{f}": {counts[f]},' for f in families),
        total=sum(counts.values()),
    )


# ------------------------------------------------------------------ #
#                                main                                #
# ------------------------------------------------------------------ #


def generate(*, threshold: int = MAX_FLAT_MEMBERS) -> Dict[pathlib.Path, str]:
    """Every file the package should contain, as ``{path: source}``."""
    tags_by_family = universe()
    families = sorted(tags_by_family)
    counts = {f: len(tags_by_family[f]) for f in families}
    assert_no_prefix_tags([t for f in families for t in tags_by_family[f]])

    files: Dict[pathlib.Path, str] = {}
    classes = 0
    largest = 0
    for family in families:
        source, root = render_family(family, tags_by_family[family], threshold=threshold)
        files[OUT_DIR / f"{family.lower()}.py"] = source
        classes += root.count_classes()
        largest = max(largest, root.max_leaf())

    fp = fingerprint()
    files[OUT_DIR / "_manifest.py"] = render_manifest(
        families, counts, fp=fp, threshold=threshold
    )

    total = sum(counts.values())
    cost = f"{total / 42_000:.1f} s" if total > 1000 else "no time at all"
    init = render_init(families, counts, cost)
    annotations = "\n".join(f"        {f}: type[{f}]" for f in families)
    files[OUT_DIR / "__init__.py"] = init.replace("{annotations}", annotations)

    print(
        f"{total:,} tags | {len(families)} families | {classes:,} classes | "
        f"largest leaf {largest:,} | fingerprint {fp[:12]}",
        file=sys.stderr,
    )
    return files


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the committed tree differs from what would be generated. Writes nothing.",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=MAX_FLAT_MEMBERS,
        help=f"Split a node above this many tags (default {MAX_FLAT_MEMBERS}).",
    )
    args = parser.parse_args(argv)

    files = generate(threshold=args.threshold)

    if args.check:
        stale: List[str] = []
        for path, source in sorted(files.items()):
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current != source:
                stale.append(path.name if current is not None else f"{path.name} (missing)")
        extra = sorted(
            p.name
            for p in OUT_DIR.glob("*.py")
            if p not in files and p.name != "_base.py"
        )
        if stale or extra:
            print(
                "Generated tag enums are STALE.\n"
                + (f"  differ/missing: {', '.join(stale)}\n" if stale else "")
                + (f"  orphaned      : {', '.join(extra)}\n" if extra else "")
                + "Run: python scripts/gen_citivelo_tag_enums.py",
                file=sys.stderr,
            )
            return 1
        print("Generated tag enums are up to date.", file=sys.stderr)
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(OUT_DIR.glob("*.py")):
        if path not in files and path.name != "_base.py":
            path.unlink()
    written = 0
    for path, source in sorted(files.items()):
        if path.is_file() and path.read_text(encoding="utf-8") == source:
            continue
        path.write_text(source, encoding="utf-8", newline="\n")
        written += 1
    print(f"wrote {written} file(s) to {OUT_DIR}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
