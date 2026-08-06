r"""The harvested Citi Velocity ``RATES.*`` catalog, and generation from it.

The catalog is a **grammar, not a tag list.** Walking the Function Builder to
every leaf was attempted and abandoned on evidence:

* ``RATES.XCCY_OIS_SWAP`` is ``ccy1 -> ccy2 -> SPOT -> tenor -> {BASE_LEG,
  SPREAD_LEG} -> BASIS_SPREAD``, one leaf per node - roughly 20,000 UI selections
  at ~8s each to enumerate a grammar that is just *tenor x leg*;
* ``RATES.VOL`` is ~23,000 tags for USD alone and ~250,000 across 11 currencies,
  which is ~9 hours of validation at 15 tags per ~2s call.

What a notebook actually does is ask for *one* series. So this module stores
structure plus per-branch grammar, generates the tag you want, and validation
happens on demand through ``CVTSHIST``.

Two rules that took a wrong turn to find
----------------------------------------
**Grammar must be per-branch, never pooled per level.** Pooling ``RATES.VOL``'s
level-4 vocabulary gives ``[1M, 1Y, 3M, 6M, BLACK, NORMAL, NORMALABSOLUTE,
FWDPREMIUM, NORMALSKEW]`` - expiries and vol conventions mixed, because each
measure has its own shape. Generating from the pooled vocabulary produced 2,163
VOL tags of which **zero** were valid.

**Generation must be path-consistent, not level-consistent.** Storing "the
vocabulary at each level" and sampling one entry per level produces combinations
that exist on no real path - e.g. ``OTM_RFR`` at level 0 with ``BLACK``/``DAILY``
below, which only exist under ``ATM``. That scored 17% on VOL while scoring 100%
on ``XCCY_OIS_SWAP`` purely because the latter is homogeneous. The correct rule is
recursive and keeps every tag on a recorded path::

    tags(N) = for each option O of N:
                 if N/O was recorded  -> seg(O) + "." + tags(N/O)
                 else                 -> seg(O) + "." + tags(first recorded child)

Unexpanded siblings inherit the shape of the sibling that was expanded. Final
validation of 1,546 path-consistent tags scored 94% shape-correct.

Depth varies *within* a family and even between conventions of one measure:
``ATM.NORMAL`` carries a ``DAILY|ANNUAL`` basis level while ``ATM.BLACK``,
``ATM.PREMIUM`` and ``ATM.FWDPREMIUM`` go straight to expiry.
"""

from __future__ import annotations

import fnmatch
import functools
import json
import pathlib
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from MDP.CitiVelocityExcel.errors import CatalogError

__all__ = [
    "CitiVeloCatalog",
    "BondRef",
    "CATALOG_DIR",
    "TENOR_RE",
    "RFR_VOL_BRANCHES",
    "DEPRECATED_VOL_BRANCHES",
]

CATALOG_DIR = pathlib.Path(__file__).resolve().parent / "catalog"

#: ``1D 1W 2W 1M ... 40Y`` and the odd ``21M``/``15M``. Used to tell a tenor level
#: from a vocabulary level when reading a branch's options.
TENOR_RE = re.compile(r"^\d+[DWMY]$")

#: Every ``_RFR`` vol branch is 100% shape-correct with zero failures.
RFR_VOL_BRANCHES: Tuple[str, ...] = ("ATM_RFR", "OTM_RFR", "REALIZED_RFR", "VOL_RATIO_RFR")

#: Their legacy twins account for ALL of VOL's shape failures and return no data.
#: Builders default to the ``_RFR`` branches; these are opt-in only.
DEPRECATED_VOL_BRANCHES: Tuple[str, ...] = ("ATM", "OTM", "REALIZED", "VOL_RATIO")

_DEFAULT_LOCK = threading.Lock()
_DEFAULT: Optional["CitiVeloCatalog"] = None


@dataclass(frozen=True)
class BondRef:
    """One row of the ``CVCURVEBOND`` universe."""

    isin: str
    description: str
    maturity: Optional[str]
    country: str
    currency: str
    asset_type: str

    @property
    def universe_key(self) -> str:
        return f"{self.country}.{self.currency}.{self.asset_type}"


def _seg_after(parent: str, child: str) -> str:
    """The segment(s) ``child`` adds to ``parent``."""
    if child.startswith(parent + "."):
        return child[len(parent) + 1 :]
    return child


class CitiVeloCatalog:
    """Loads the harvested catalog and answers structural questions about it.

    >>> cat = CitiVeloCatalog.default()
    >>> "OIS" in cat.families()
    True
    >>> cat.options("RATES.OIS.USD_SOFR")
    ['BFLY', 'CURVES', 'FWD', 'PAR', 'ROLL_CARRY', 'SWAP_SPREAD']
    >>> "10Y" in cat.tenors("RATES.OIS.USD_SOFR.PAR")
    True

    Loading is lazy per artefact: the DAG walk alone is 1.6 MB, and a caller that
    only wants bond ISINs should not pay for it.
    """

    def __init__(self, catalog_dir: Optional[pathlib.Path] = None):
        self.dir = pathlib.Path(catalog_dir) if catalog_dir is not None else CATALOG_DIR
        if not self.dir.is_dir():
            raise CatalogError(f"Citi Velocity catalog directory not found: {self.dir}")
        self._children: Optional[Dict[str, List[str]]] = None
        self._leaves: Optional[Set[str]] = None
        self._grammar: Optional[Dict[str, Any]] = None
        self._verified: Optional[Dict[str, str]] = None
        self._bonds: Optional[List[BondRef]] = None
        self._bond_tags: Optional[Set[str]] = None
        self._suffix_memo: Dict[str, List[str]] = {}

    # -- construction ---------------------------------------------------

    @classmethod
    def default(cls) -> "CitiVeloCatalog":
        """Process-wide singleton over the committed catalog."""
        global _DEFAULT
        if _DEFAULT is None:
            with _DEFAULT_LOCK:
                if _DEFAULT is None:
                    _DEFAULT = cls()
        return _DEFAULT

    def _load_json(self, name: str) -> Any:
        path = self.dir / name
        if not path.is_file():
            raise CatalogError(f"Missing catalog artefact: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    # -- the node tree --------------------------------------------------

    def _ensure_tree(self) -> None:
        if self._children is not None:
            return
        children: Dict[str, List[str]] = {}
        leaves: Set[str] = set()

        def absorb(raw: Mapping[str, Any], child_key: str) -> None:
            for key, node in raw.items():
                dotted = key.split(" / ")[-1]
                kids = node.get(child_key) or []
                if kids:
                    merged = children.setdefault(dotted, [])
                    for kid in kids:
                        if kid not in merged:
                            merged.append(kid)
                if node.get("leaf"):
                    leaves.add(dotted)

        # The breadth-first depth-capped walk of all 33 families ...
        absorb(self._load_json("dag_rates_deep.json")["tree"], "children")
        # ... plus the deeper per-branch shape probes for VOL / INFLATION /
        # XCCY_OIS_SWAP, which is where the depth actually varies per branch.
        absorb(self._load_json("shapes2.json"), "options")

        for node, kids in children.items():
            children[node] = sorted(kids)
        self._children = children
        self._leaves = leaves

    @property
    def nodes(self) -> Sequence[str]:
        """Every node the walk recorded children for."""
        self._ensure_tree()
        assert self._children is not None
        return list(self._children.keys())

    def families(self) -> List[str]:
        """The 33 ``RATES.*`` family names, without the ``RATES.`` prefix."""
        self._ensure_tree()
        assert self._children is not None
        return sorted(_seg_after("RATES", c) for c in self._children.get("RATES", []))

    def is_known(self, node: str) -> bool:
        self._ensure_tree()
        assert self._children is not None and self._leaves is not None
        return node in self._children or node in self._leaves

    def is_leaf(self, node: str) -> bool:
        self._ensure_tree()
        assert self._children is not None
        return not self._children.get(node)

    def children(self, node: str) -> List[str]:
        """Full dotted children of ``node`` (empty when it was not expanded)."""
        self._ensure_tree()
        assert self._children is not None
        return list(self._children.get(node, []))

    def options(self, node: str) -> List[str]:
        """The child SEGMENTS of ``node`` - its vocabulary at that branch."""
        return [_seg_after(node, c) for c in self.children(node)]

    def tenors(self, node: str) -> List[str]:
        """Child segments of ``node`` that look like tenors, in tenor order."""
        return sort_tenors([o for o in self.options(node) if TENOR_RE.match(o)])

    def describe(self, node: str) -> Dict[str, Any]:
        """Structural summary of one node: depth, children, whether it is a leaf."""
        self._ensure_tree()
        return {
            "node": node,
            "known": self.is_known(node),
            "depth": node.count("."),
            "n_children": len(self.children(node)),
            "options": self.options(node),
            "leaf": self.is_leaf(node),
            "verification": self.verification(node),
        }

    def search(self, pattern: str, *, limit: int = 200) -> List[str]:
        """Nodes matching a glob (``RATES.VOL.*.ATM_RFR``) or a regex.

        A pattern containing glob metacharacters is treated as a glob; anything
        else is treated as a case-insensitive substring, and a pattern wrapped in
        ``/.../`` is treated as a regex.
        """
        self._ensure_tree()
        assert self._children is not None and self._leaves is not None
        universe = sorted(set(self._children) | set(self._leaves))
        text = str(pattern)
        if text.startswith("/") and text.endswith("/") and len(text) > 2:
            rx = re.compile(text[1:-1], re.IGNORECASE)
            hits = [n for n in universe if rx.search(n)]
        elif any(ch in text for ch in "*?["):
            hits = [n for n in universe if fnmatch.fnmatch(n, text)]
        else:
            needle = text.upper()
            hits = [n for n in universe if needle in n.upper()]
        return hits[: int(limit)]

    # -- path-consistent generation -------------------------------------

    def _suffixes(self, node: str, *, depth: int = 0) -> List[str]:
        """Well-formed suffixes below ``node``, following recorded paths only."""
        if depth > 24:
            raise CatalogError(f"Catalog expansion exceeded depth 24 at {node!r}; the tree is malformed.")
        memo = self._suffix_memo.get(node)
        if memo is not None:
            return memo

        kids = self.children(node)
        if not kids:
            self._suffix_memo[node] = [""]
            return [""]

        recorded = [k for k in kids if self.children(k)]
        template = recorded[0] if recorded else None

        out: List[str] = []
        for kid in kids:
            seg = _seg_after(node, kid)
            sub = kid if self.children(kid) else template
            if sub is None:
                out.append(seg)
                continue
            for tail in self._suffixes(sub, depth=depth + 1):
                out.append(f"{seg}.{tail}" if tail else seg)
        self._suffix_memo[node] = out
        return out

    def expand(self, node: str, *, max_tags: int = 50_000) -> List[str]:
        """Every path-consistent tag under ``node``.

        Raises
        ------
        CatalogError
            When the expansion exceeds ``max_tags``. It raises rather than
            truncating: a silently-capped enumeration reads as "that is all there
            is", which is exactly the mistake that made a 17%-valid VOL sample
            look like a catalog.
        """
        if not self.is_known(node):
            raise CatalogError(
                f"{node!r} is not in the harvested catalog. Use search() to find the right node, "
                "or pass the tag straight through - any RATES.* string is accepted by the client."
            )
        suffixes = self._suffixes(node)
        if len(suffixes) > int(max_tags):
            raise CatalogError(
                f"Expanding {node!r} yields {len(suffixes):,} tags, above max_tags={max_tags:,}. "
                "Narrow the node (e.g. expand one currency at a time) or raise max_tags "
                "deliberately - this is not truncated silently."
            )
        return sorted({f"{node}.{s}" if s else node for s in suffixes})

    def count_expansion(self, node: str) -> int:
        """How many tags :meth:`expand` would produce, without building them."""
        if not self.is_known(node):
            raise CatalogError(f"{node!r} is not in the harvested catalog.")
        return len(self._suffixes(node))

    # -- verification overlay -------------------------------------------

    def _ensure_verified(self) -> None:
        if self._verified is not None:
            return
        verified: Dict[str, str] = {}

        # 1,546 path-consistent tags probed through CVTSHIST; 94% shape-correct.
        try:
            shape3 = self._load_json("shape3_results.json")
            for tag in shape3.get("tags", []):
                verified[tag] = "shape_ok"
        except CatalogError:
            pass

        # Per-tag CVTSHIST verdicts from the ASW cross-currency sweep.
        try:
            for tag, row in self._load_json("asw_ccy.json").items():
                status = str(row.get("status", "")).strip()
                if status:
                    verified[tag] = status
        except CatalogError:
            pass

        self._verified = verified

    def verification(self, tag: str) -> str:
        """``valid`` | ``empty`` | ``shape_ok`` | ``failed`` | ``unverified``.

        ``unverified`` is an honest answer, not a failure: the catalog records
        structure for far more tags than were ever probed, and generating a tag
        the add-in has not been asked for is the normal case. Use
        :meth:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient.validate`
        to settle it against the live add-in.
        """
        self._ensure_verified()
        assert self._verified is not None
        if tag in self._verified:
            return self._verified[tag]
        if self.bond_tag_is_validated(tag):
            return "valid"
        return "unverified"

    def unverified_families(self) -> List[str]:
        """Families whose SHAPE has never been confirmed against ``CVTSHIST``.

        ``RATES.SWAP_LIBOR`` is the important one: 46 currencies, and its shape is
        recorded in the DAG walk but has NOT been confirmed to serve data. Non-RFR
        and EM currency coverage depends on it.
        """
        self._ensure_verified()
        assert self._verified is not None
        probed = {t.split(".")[1] for t in self._verified if t.count(".") >= 1}
        return sorted(f for f in self.families() if f not in probed)

    # -- bonds ----------------------------------------------------------

    def _ensure_bonds(self) -> None:
        if self._bonds is not None:
            return
        rows: List[BondRef] = []
        raw = self._load_json("bond_isins.json")
        for key, entries in raw.items():
            parts = key.split(".")
            country = parts[0] if parts else ""
            currency = parts[1] if len(parts) > 1 else ""
            asset_type = parts[2] if len(parts) > 2 else ""
            for entry in entries:
                rows.append(
                    BondRef(
                        isin=str(entry.get("isin", "")).strip(),
                        description=str(entry.get("desc", "")).strip(),
                        maturity=(str(entry["maturity"]).strip() if entry.get("maturity") else None),
                        country=country,
                        currency=currency,
                        asset_type=asset_type,
                    )
                )
        self._bonds = rows

        tags: Set[str] = set()
        for name in ("bond_tags_validated.json", "bond_tags_validated2.json"):
            try:
                payload = self._load_json(name)
            except CatalogError:
                continue
            tags.update(payload.get("valid_tags", []) or [])
        self._bond_tags = tags

    def bonds(
        self,
        *,
        country: Optional[str] = None,
        currency: Optional[str] = None,
        asset_type: Optional[str] = None,
    ) -> List[BondRef]:
        """The ``CVCURVEBOND`` universe, optionally filtered.

        2,162 distinct ISINs over 18 countries and three asset types -
        ``GOVT``, ``AGENCY``, ``COVERED``. ``CORP``, ``MUNI``, ``SUPRA``, ``SSA``,
        ``TIPS``, ``INFL``, ``ILB``, ``SOVEREIGN`` and ``QUASI`` all return
        nothing, as do ``CAN`` and ``AUS`` entirely.
        """
        self._ensure_bonds()
        assert self._bonds is not None
        out = self._bonds
        if country:
            out = [b for b in out if b.country == str(country).upper()]
        if currency:
            out = [b for b in out if b.currency == str(currency).upper()]
        if asset_type:
            out = [b for b in out if b.asset_type == str(asset_type).upper()]
        return list(out)

    def bond_universe_keys(self) -> List[str]:
        self._ensure_bonds()
        assert self._bonds is not None
        return sorted({b.universe_key for b in self._bonds})

    def bond_tag_is_validated(self, tag: str) -> bool:
        """True when this exact ``RATES.BOND.<ISIN>.<value>`` tag was probed valid."""
        if not tag.startswith("RATES.BOND."):
            return False
        self._ensure_bonds()
        assert self._bond_tags is not None
        return tag in self._bond_tags

    def bond_isin_lookup(self, isin: str) -> Optional[BondRef]:
        self._ensure_bonds()
        assert self._bonds is not None
        needle = str(isin).strip().upper()
        for b in self._bonds:
            if b.isin.upper() == needle:
                return b
        return None

    # -- grammar --------------------------------------------------------

    def grammar(self) -> Dict[str, Any]:
        """The per-family level vocabulary and observed parent->child edges.

        Kept for introspection and for cross-checking a generated tag against
        what the walk actually saw. Do NOT generate from the level vocabulary:
        pooling it per level is exactly the mistake that produced 2,163 VOL tags
        of which zero were valid.
        """
        if self._grammar is None:
            self._grammar = self._load_json("rates_grammar.json")
        return self._grammar

    def family_vocabulary(self, family: str, level: int) -> List[str]:
        """The pooled vocabulary at one level of a family. See the warning above."""
        fam = family if family.startswith("RATES.") else f"RATES.{family}"
        vocab = self.grammar().get("vocab", {}).get(fam, {})
        return list(vocab.get(str(level), []))


# ------------------------------------------------------------------ #
#                          tenor utilities                           #
# ------------------------------------------------------------------ #

_UNIT_DAYS = {"D": 1.0, "W": 7.0, "M": 30.4375, "Y": 365.25}


def tenor_years(tenor: str) -> float:
    """Approximate year fraction of a Velocity tenor token, for sorting."""
    token = str(tenor).strip().upper()
    m = TENOR_RE.match(token)
    if not m:
        raise CatalogError(f"Not a Velocity tenor: {tenor!r}")
    return float(token[:-1]) * _UNIT_DAYS[token[-1]] / 365.25


def sort_tenors(tenors: Iterable[str]) -> List[str]:
    """Sort tenor tokens by maturity rather than lexically."""
    return sorted(tenors, key=tenor_years)
