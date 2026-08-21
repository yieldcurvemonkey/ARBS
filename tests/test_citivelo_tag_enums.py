r"""The generated Citi Velocity tag enums, and the guards that keep them honest.

These run against the COMMITTED generated tree in
``Query/CitiVelocity/tag_enums/`` and the COMMITTED catalog artefacts it was
derived from. Nothing here is a fixture: the assertion is that the two agree, so
a catalog refresh that is not followed by a regeneration fails here rather than
silently leaving the enum describing a catalog that no longer exists.

What each group is defending against
------------------------------------
**``str()`` semantics.** A tag's whole job is to be a string. Under a plain
``(str, Enum)`` mixin, ``str(member)`` returns the *member name* on some Python
versions and the *value* on others - the 3.11 enum change moved it - so a member
that works on one interpreter produces a bad tag on another, and the failure
surfaces as "this tag has no data". :class:`enum.StrEnum` pins it, and
:func:`test_a_member_is_its_tag_in_every_formatting_context` asserts it in five
contexts rather than trusting the type's documentation.

**Byte-identity with the catalog.** A generator that validates only its own
output is checking nothing, so the comparison runs from the catalog side:
``expand()`` is recomputed here and the emitted values must equal it as a set,
per family, exactly. Not a sample - a lost tag is invisible and would leave the
enum looking complete.

**Mangling injectivity.** Dots become underscores, so ``A.B_C`` and ``A_B.C``
would collide and the second would silently win. Asserted per leaf as
"member count equals tag count", which catches a collision, an ``Enum`` value
alias, and a duplicate in the source all at once.

**Coercion into the query.** A ``StrEnum`` member compares and hashes as its own
value, so nothing *breaks* without coercion - which is exactly why it needs a
test. What it changes is display and identity: a DataFrame column labelled with a
member renders as ``<PAR_10Y: 'RATES...'>`` and any ``type(x) is str`` check
downstream takes the other branch. ``__post_init__`` normalises, and these tests
pin it for the top-level tag, the ``structure_kwargs`` copy and per-leg specs.

**Laziness.** 67,425 members cost about 1.6 s to construct. The package must not
pay that on import, and touching one family must not drag in the rest.

No Excel, no COM, no network. The one place the enum reaches into ``MDP`` is
:meth:`CitiVeloTag.verification`, which reads committed JSON.
"""

from __future__ import annotations

import dataclasses
import importlib
import pathlib
import subprocess
import sys
import textwrap

import pytest

from MDP.CitiVelocityExcel.catalog import (
    DEPRECATED_VOL_BRANCHES as MDP_DEPRECATED_VOL_BRANCHES,
)
from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog
from Query.CitiVelocity import CitiVeloQuery, CitiVeloStructure
from Query.CitiVelocity.tag_enums import (
    CATALOG_FINGERPRINT,
    COUNTS,
    FAMILIES,
    TOTAL,
    CitiVeloTag,
    CitiVeloTags,
    TagNamespace,
)
from Query.CitiVelocity.tag_enums._base import DEPRECATED_VOL_BRANCHES, mangle

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GEN = _REPO_ROOT / "scripts" / "gen_citivelo_tag_enums.py"

#: One well-known tag per shape the tree can produce: a namespace root with an
#: enum leaf directly under it, and a four-deep one.
SOFR_10Y = "RATES.OIS.USD_SOFR.PAR.10Y"
VOL_RFR = "RATES.VOL.USD.ATM_RFR.BLACK.1Y.10Y"
VOL_LEGACY = "RATES.VOL.USD.ATM.BLACK.1Y.10Y"


@pytest.fixture(scope="module")
def cat() -> CitiVeloCatalog:
    return CitiVeloCatalog.default()


@pytest.fixture(scope="module")
def emitted() -> dict:
    """``{family: set of emitted tags}``. Loads every family, so module-scoped."""
    return {f: set(getattr(CitiVeloTags, f).tags()) for f in FAMILIES}


# ------------------------------------------------------------------ #
#                          str() semantics                           #
# ------------------------------------------------------------------ #


def test_a_member_is_its_tag_in_every_formatting_context():
    """The one property everything downstream rests on.

    ``classify_tag(str(explicit))`` in the pricer, the tag cache's parquet
    filename, and a pandas column label all reach for the string form. Five
    contexts because they do not all route through ``__str__``: ``%`` and
    ``format`` go via ``__format__``, and ``join`` uses the raw ``str`` value.
    """
    member = CitiVeloTags.OIS.USD_SOFR.PAR_10Y
    assert str(member) == SOFR_10Y
    assert f"{member}" == SOFR_10Y
    assert "%s" % member == SOFR_10Y
    assert format(member) == SOFR_10Y
    assert "".join([member]) == SOFR_10Y


def test_a_member_is_a_str_and_interchangeable_with_one():
    member = CitiVeloTags.OIS.USD_SOFR.PAR_10Y
    assert isinstance(member, str)
    assert member == SOFR_10Y
    assert hash(member) == hash(SOFR_10Y)
    assert {member: 1}[SOFR_10Y] == 1
    assert member.value == SOFR_10Y


def test_a_member_survives_a_pickle_round_trip():
    """``TimeseriesBuilder`` fans work out over joblib, which pickles arguments."""
    import pickle

    member = CitiVeloTags.OIS.USD_SOFR.PAR_10Y
    assert pickle.loads(pickle.dumps(member)) is member


# ------------------------------------------------------------------ #
#              byte-identity with the harvested catalog              #
# ------------------------------------------------------------------ #


def test_every_family_matches_the_catalogs_own_expansion_exactly(cat, emitted):
    """Recomputed from the catalog side, per family, as a set. Not a sample."""
    for family in FAMILIES:
        truth = set(cat.expand(f"RATES.{family}", max_tags=200_000))
        assert emitted[family] == truth, (
            f"{family}: {len(truth - emitted[family])} missing, "
            f"{len(emitted[family] - truth)} not in the catalog"
        )


def test_the_manifest_counts_match_what_is_emitted(emitted):
    assert set(COUNTS) == set(FAMILIES)
    for family in FAMILIES:
        assert COUNTS[family] == len(emitted[family]), family
    assert TOTAL == sum(COUNTS.values()) == sum(len(v) for v in emitted.values())


def test_the_families_are_the_thirty_three_the_catalog_records(cat):
    assert sorted(FAMILIES) == sorted(cat.families())
    assert len(FAMILIES) == 33


def test_every_tag_resolves_back_to_a_member_with_a_byte_identical_value(emitted):
    """The inverse of the one-way name mangling, over the whole universe.

    A caller holding a tag out of a log or a config file must be able to get the
    typed member back without guessing how its name was spelled.
    """
    for family in FAMILIES:
        for tag in emitted[family]:
            member = CitiVeloTags.find(tag)
            assert isinstance(member, CitiVeloTag)
            assert member.value == tag
            assert str(member) == tag


# ------------------------------------------------------------------ #
#                        mangling injectivity                        #
# ------------------------------------------------------------------ #


def _leaves(node):
    if isinstance(node, type) and issubclass(node, CitiVeloTag):
        yield node
        return
    for _, child in node._child_nodes():
        yield from _leaves(child)


def test_no_leaf_lost_a_tag_to_a_name_collision_or_an_enum_alias():
    """Member count must equal distinct-value count in every leaf.

    Catches three failures with one assertion: a mangling collision (two tags,
    one name), an ``Enum`` value alias (two names, one value - the second becomes
    an alias and vanishes from iteration), and a duplicated source line.
    """
    checked = 0
    for family in FAMILIES:
        for leaf in _leaves(getattr(CitiVeloTags, family)):
            values = {m.value for m in leaf}
            assert len(leaf.__members__) == len(list(leaf)) == len(values), leaf.node()
            checked += 1
    assert checked == 468, f"expected 468 leaf enums, walked {checked}"


def test_mangling_prefixes_a_leading_digit_rather_than_dropping_the_tag():
    """``3S1S_BASIS`` is not a Python identifier; ``N3S1S_BASIS`` is."""
    assert mangle("PAR.10Y") == "PAR_10Y"
    assert mangle("3S1S_BASIS") == "N3S1S_BASIS"
    assert mangle("") == "ROOT"
    member = CitiVeloTags.find("RATES.BASIS_SWAPS.3S1S_BASIS.AUD.10Y")
    assert member.name.startswith("N3S1S") or "3S1S" in member.value


def test_every_member_name_is_a_valid_python_identifier():
    for family in FAMILIES:
        for leaf in _leaves(getattr(CitiVeloTags, family)):
            for name in leaf.__members__:
                assert name.isidentifier(), f"{leaf.node()}.{name}"


# ------------------------------------------------------------------ #
#                          the drift guard                           #
# ------------------------------------------------------------------ #


def test_the_committed_tree_is_what_the_generator_would_emit_today():
    """``--check`` recomputes everything and diffs it against the committed files.

    This is the guard the whole design rests on: the enum's correctness is a
    claim about the catalog, and a claim about a file on disk goes stale the
    moment someone refreshes that file. Run as a subprocess so a failure reports
    the generator's own message, which names the stale files.
    """
    result = subprocess.run(
        [sys.executable, str(_GEN), "--check"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_the_manifest_fingerprint_matches_the_catalog_artefacts_on_disk():
    """The same check from the other side, without shelling out.

    Derived from the inputs rather than hand-maintained on purpose: a version
    number a human has to remember to bump is bumped at the wrong moment, and
    nothing says so when it is not.
    """
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    try:
        gen = importlib.import_module("gen_citivelo_tag_enums")
    finally:
        sys.path.pop(0)
    assert gen.fingerprint() == CATALOG_FINGERPRINT
    assert len(CATALOG_FINGERPRINT) == 64


# ------------------------------------------------------------------ #
#                         the shared protocol                        #
# ------------------------------------------------------------------ #


def test_a_namespace_and_an_enum_answer_the_same_five_questions():
    """The variable-depth tree is only tolerable because of this symmetry."""
    namespace = CitiVeloTags.OIS
    leaf = CitiVeloTags.OIS.USD_SOFR
    assert issubclass(namespace, TagNamespace)
    assert issubclass(leaf, CitiVeloTag)
    for node in (namespace, leaf):
        assert node.node().startswith("RATES.")
        assert isinstance(node.children(), tuple) and node.children()
        assert isinstance(node.tags(), tuple) and node.tags()
        assert node.find(SOFR_10Y).value == SOFR_10Y
        assert node.search("*PAR.10Y", limit=5)


def test_a_namespaces_tags_are_the_union_of_its_leaves():
    assert set(CitiVeloTags.OIS.tags()) == {
        tag for leaf in _leaves(CitiVeloTags.OIS) for tag in leaf.tags()
    }


def test_a_leaf_miss_always_carries_examples_even_when_nothing_is_similar():
    """"Not found" with no suggestion is the least useful thing this could say.

    ``99Y`` appears in no tag anywhere, so the near-miss search returns nothing
    and the message must fall back to what the node does hold.
    """
    with pytest.raises(KeyError) as exc:
        CitiVeloTags.OIS.find("RATES.OIS.USD_SOFR.PAR.99Y")
    message = str(exc.value)
    assert "99Y" in message
    assert "Recorded here" in message
    assert "RATES.OIS.USD_SOFR." in message


def test_a_leaf_miss_names_the_closest_tags_when_there_are_any():
    with pytest.raises(KeyError) as exc:
        CitiVeloTags.OIS.find("RATES.OIS.USD_SOFR.NOT_A_SUBTYPE.10Y")
    assert "Closest recorded" in str(exc.value)


def test_a_namespace_miss_names_the_branches_rather_than_walking_below_them():
    """Searching below ``RATES.VOL`` would build 26,233 members for a worse answer."""
    with pytest.raises(KeyError) as exc:
        CitiVeloTags.VOL.find("RATES.VOL.USD.NOT_A_BRANCH.BLACK.1Y.10Y")
    message = str(exc.value)
    assert "Branches here" in message
    assert "ATM_RFR" in message


def test_find_refuses_a_tag_from_another_family():
    with pytest.raises(KeyError):
        CitiVeloTags.OIS.find(VOL_RFR)


def test_a_namespace_cannot_be_instantiated():
    """It carries no state; constructing one would suggest it did."""
    with pytest.raises(TypeError, match="namespace, not a value"):
        CitiVeloTags.OIS()
    with pytest.raises(TypeError, match="namespace, not a value"):
        CitiVeloTags()


def test_a_member_knows_its_family_segments_and_tenor():
    member = CitiVeloTags.OIS.USD_SOFR.PAR_10Y
    assert member.family == "OIS"
    assert member.segments == ("USD_SOFR", "PAR", "10Y")
    assert member.tenor == "10Y"


def test_verification_delegates_to_the_catalog_and_is_honest_about_unverified():
    """``unverified`` is the majority answer and is not a failure."""
    assert CitiVeloTags.find(SOFR_10Y).verification() in {
        "valid",
        "empty",
        "shape_ok",
        "failed",
        "unverified",
    }


# ------------------------------------------------------------------ #
#                      the deprecated VOL branches                   #
# ------------------------------------------------------------------ #


def test_the_deprecated_vol_branch_list_matches_the_catalogs():
    """Duplicated to keep ``Query`` free of an ``MDP`` import; pinned equal here."""
    assert DEPRECATED_VOL_BRANCHES == MDP_DEPRECATED_VOL_BRANCHES


def test_the_legacy_vol_branches_are_kept_but_flagged():
    """Kept because they are real recorded structure; flagged because they serve
    no data, and reaching for ``ATM`` when you meant ``ATM_RFR`` yields an empty
    series rather than an error."""
    legacy = CitiVeloTags.find(VOL_LEGACY)
    live = CitiVeloTags.find(VOL_RFR)
    assert legacy.deprecated is True
    assert live.deprecated is False
    assert "ATM" in CitiVeloTags.VOL.USD.children()
    assert "ATM_RFR" in CitiVeloTags.VOL.USD.children()


def test_nothing_outside_vol_is_marked_deprecated():
    assert CitiVeloTags.OIS.USD_SOFR.PAR_10Y.deprecated is False


# ------------------------------------------------------------------ #
#                             laziness                               #
# ------------------------------------------------------------------ #


def test_importing_the_package_imports_no_family_module_and_no_mdp():
    """Run in a subprocess: once a family is loaded in-process it stays loaded.

    Two claims at once. Constructing all 67,425 members costs about 1.6 s, so the
    package must not pay it on import; and the ``Query`` layer must not drag in
    ``MDP`` merely to name a tag, because the catalog's JSON artefacts are ~1.6 MB
    a caller who only wanted a string should not load.
    """
    code = textwrap.dedent(
        """
        import sys
        import Query.CitiVelocity.tag_enums as te
        families = [m for m in sys.modules if m.startswith("Query.CitiVelocity.tag_enums.")
                    and not m.rsplit(".", 1)[-1].startswith("_")]
        mdp = [m for m in sys.modules if m == "MDP" or m.startswith("MDP.")]
        print(repr((families, mdp, te.TOTAL)))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=str(_REPO_ROOT), capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    families, mdp, total = eval(result.stdout.strip())  # noqa: S307 - our own literal
    assert families == [], f"family modules imported eagerly: {families}"
    assert mdp == [], f"MDP imported by the Query-layer tag enums: {mdp}"
    assert total == TOTAL


def test_touching_one_family_imports_only_that_family():
    code = textwrap.dedent(
        """
        import sys
        from Query.CitiVelocity.tag_enums import CitiVeloTags
        CitiVeloTags.TSY
        loaded = sorted(m.rsplit(".", 1)[-1] for m in sys.modules
                        if m.startswith("Query.CitiVelocity.tag_enums.")
                        and not m.rsplit(".", 1)[-1].startswith("_"))
        print(repr(loaded))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=str(_REPO_ROOT), capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert eval(result.stdout.strip()) == ["tsy"]  # noqa: S307 - our own literal


def test_every_family_is_reachable_by_attribute_and_listed_by_dir():
    listing = dir(CitiVeloTags)
    for family in FAMILIES:
        assert family in listing
        assert getattr(CitiVeloTags, family).node() == f"RATES.{family}"


def test_an_unknown_family_raises_naming_the_real_ones():
    with pytest.raises(AttributeError, match="OIS"):
        CitiVeloTags.NOT_A_FAMILY
    with pytest.raises(KeyError, match="OIS"):
        CitiVeloTags.family("NOT_A_FAMILY")


def test_family_accepts_a_full_tag_as_well_as_a_name():
    assert CitiVeloTags.family("OIS") is CitiVeloTags.family(SOFR_10Y)


# ------------------------------------------------------------------ #
#                      coercion into CitiVeloQuery                   #
# ------------------------------------------------------------------ #


def test_a_query_built_from_a_member_holds_a_plain_str():
    query = CitiVeloQuery(tag=CitiVeloQuery.Tags.OIS.USD_SOFR.PAR_10Y)
    assert type(query.tag) is str
    assert type(query.structure_kwargs["tag"]) is str
    assert query.tag == SOFR_10Y
    assert all(type(t) is str for t in query.leg_tag_hints())
    assert all(type(t) is str for t in query.market_request["tags"])


def test_a_member_and_its_string_build_the_same_query():
    """Equality by construction rather than by luck - the point of coercing."""
    from_member = CitiVeloQuery(tag=CitiVeloQuery.Tags.OIS.USD_SOFR.PAR_10Y)
    from_string = CitiVeloQuery(tag=SOFR_10Y)
    assert from_member == from_string
    assert from_member.col_name() == from_string.col_name()
    assert from_member.structure_kwargs == from_string.structure_kwargs


def test_leg_specs_inside_structure_kwargs_are_coerced_too():
    """A SPREAD's legs are where the enum gets reached for most."""
    query = CitiVeloQuery(
        structure=CitiVeloStructure.SPREAD,
        structure_kwargs={
            "legs": [
                {"tag": CitiVeloTags.OIS.USD_SOFR.PAR_10Y},
                {"tag": CitiVeloTags.OIS.USD_FEDFUND.PAR_10Y},
            ]
        },
        name="SOFR-FF 10y",
    )
    assert [type(leg["tag"]) for leg in query.structure_kwargs["legs"]] == [str, str]
    assert query.leg_tag_hints() == (
        "RATES.OIS.USD_SOFR.PAR.10Y",
        "RATES.OIS.USD_FEDFUND.PAR.10Y",
    )


def test_coercion_does_not_mutate_the_callers_own_leg_dicts():
    """``structure_kwargs`` is the caller's object; normalising must copy."""
    legs = [{"tag": CitiVeloTags.OIS.USD_SOFR.PAR_10Y}]
    CitiVeloQuery(structure=CitiVeloStructure.SPREAD, structure_kwargs={"legs": legs})
    assert isinstance(legs[0]["tag"], CitiVeloTag)


def test_tags_is_a_classvar_and_not_a_dataclass_field():
    """Without ``ClassVar`` every query would gain a ``Tags`` constructor argument."""
    names = {f.name for f in dataclasses.fields(CitiVeloQuery)}
    assert "Tags" not in names
    assert CitiVeloQuery.Tags is CitiVeloTags


def test_a_raw_string_tag_is_still_accepted_unchanged():
    """The enum is a discovery surface, never a gate: a tag newer than the
    committed catalog must not be blocked."""
    newer_than_the_catalog = "RATES.OIS.USD_SOFR.SOMETHING_NEW.10Y"
    query = CitiVeloQuery(tag=newer_than_the_catalog)
    assert query.tag == newer_than_the_catalog
    with pytest.raises(KeyError):
        CitiVeloTags.find(newer_than_the_catalog)


def test_a_foreign_enum_member_is_refused_rather_than_stringified():
    """``str()`` of a foreign ``(str, Enum)`` member is ``'ClassName.MEMBER'``.

    The pricer's resolver does an unconditional ``classify_tag(str(explicit))``,
    and that classifier accepts anything as ``RAW`` without raising. So without
    this guard the bad argument reaches the add-in, comes back empty, and the
    error blames Citi. Refusing here names the type instead.
    """
    import enum

    class Legacy(str, enum.Enum):
        TEN_YEAR = SOFR_10Y

    assert str(Legacy.TEN_YEAR) != SOFR_10Y, "premise: a plain mixin does not stringify to its value"
    with pytest.raises(TypeError, match="not a Citi Velocity tag"):
        CitiVeloQuery(tag=Legacy.TEN_YEAR)


# ------------------------------------------------------------------ #
#                  the universe, pinned against drift                #
# ------------------------------------------------------------------ #


def test_the_universe_is_the_expansion_and_not_the_stale_flat_leaf_list():
    """Pins the decision that was measured, against a plausible "correction".

    ``rates_catalog.json``'s ``leaves`` list is an orphan - nothing in the repo
    reads it - and it is an older expansion hard-capped at five segments. 790 of
    its entries are strict dotted PREFIXES of real tags: ``RATES.VOL.AUD.ATM.BLACK``
    with no expiry and no tenor. Every one of them still *looks* like a tag and
    classifies as ``RAW`` without error, so regenerating from it would bake in
    fiction that fails only at the wire, while losing 42,601 real tags.

    Three assertions, one per way that could be undone: the headline count, a
    deepened tag being present, and its truncated prefix being absent.
    """
    assert TOTAL == 67_425
    # `RATES.VOL.AUD.ATM.BLACK` is verbatim one of the 263 VOL entries in the flat
    # leaf list. It is not a tag: AUD's ATM.BLACK carries a 15-point tenor axis
    # below it, and USD's carries a full expiry x tenor grid.
    truncated_prefix = "RATES.VOL.AUD.ATM.BLACK"
    every_vol_tag = set(CitiVeloTags.VOL.tags())
    assert truncated_prefix not in every_vol_tag
    assert CitiVeloTags.find(f"{truncated_prefix}.10Y").value == f"{truncated_prefix}.10Y"
    assert CitiVeloTags.find(VOL_RFR).value == VOL_RFR  # USD goes two levels deeper still
    with pytest.raises(KeyError):
        CitiVeloTags.find(truncated_prefix)


def test_the_fingerprint_covers_exactly_the_artefacts_the_expansion_reads():
    """``expand()`` reads ``dag_rates_deep.json`` and ``shapes2.json``, nothing else.

    Hashing a superset would make an unrelated refresh (the weekly bond sweep)
    mark the tree stale; hashing a subset would let a real change through.
    """
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    try:
        gen = importlib.import_module("gen_citivelo_tag_enums")
    finally:
        sys.path.pop(0)
    assert gen.SOURCE_ARTEFACTS == ("dag_rates_deep.json", "shapes2.json")
    assert "rates_catalog" not in pathlib.Path(gen.__file__).read_text(encoding="utf-8").replace(
        "rates_catalog.json``, which is truncated", ""
    ).replace("rates_catalog.json", "")


def test_no_tag_is_a_dotted_prefix_of_another(emitted):
    """The namespace tree cannot represent both, and a truncated tag is the
    exact defect that rejecting the flat leaf list avoided."""
    every = {tag for tags in emitted.values() for tag in tags}
    for tag in every:
        head = tag
        while "." in head:
            head = head.rsplit(".", 1)[0]
            assert head not in every, f"{head!r} is a prefix of {tag!r}"


# ------------------------------------------------------------------ #
#                    what the surface warns you about                #
# ------------------------------------------------------------------ #


def test_a_tag_reports_its_kind_and_whether_a_model_can_reprice_it():
    """``RAW`` is the honest answer for most of this universe.

    ``RAW`` legs carry ``CitiVeloUnit.RATIO``, so the structure layer's
    same-unit guard cannot tell two unrelated ``RAW`` families apart - a SPREAD
    across them nets and returns a number. Completion makes that combination two
    keystrokes away, so the surface has to be able to say so.
    """
    from Query.CitiVelocity._CitiVeloLeg import CitiVeloKind

    par = CitiVeloTags.OIS.USD_SOFR.PAR_10Y
    assert par.kind() is CitiVeloKind.OIS_PAR
    assert par.is_repriceable is True

    swap_internal = CitiVeloTags.SWAP_INTERNAL.tags()[0]
    raw = CitiVeloTags.find(swap_internal)
    assert raw.kind() is CitiVeloKind.RAW
    assert raw.is_repriceable is False


def test_verification_is_probe_residue_and_the_docstring_says_so():
    """Pinned so the near-vacuity is on the record rather than assumed away.

    A user filtering on ``.verification() != "failed"`` keeps essentially
    everything; that is a property of the overlay, not of the tags.
    """
    sample = list(CitiVeloTags.OIS.USD_SOFR)[:200]
    verdicts = {member.verification() for member in sample}
    assert verdicts <= {"valid", "empty", "shape_ok", "failed", "unverified"}
    assert "unverified" in verdicts
    assert "not a gate" in (CitiVeloTag.verification.__doc__ or "")
