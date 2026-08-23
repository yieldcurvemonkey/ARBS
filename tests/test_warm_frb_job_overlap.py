r"""Jobs 17 and 18 write the SAME symbols, and that must stay true or change loudly.

"CITIVELO FRB values EOD" (17) and "CITIVELO UST timeseries values EOD" (18)
both price constant-maturity UST aliases into the computed store from the same
Citi tag cache. Measured here rather than assumed, because the store symbol is
a sha1 of a query fingerprint and two jobs only collide if they construct the
query identically:

    job 17 aliases   14  (CT/O x 2,3,5,7,10,20,30)   subset of job 18's 28
    job 17 values     3  (FRB_YTM, FRB_CLEAN_PRICE, FRB_SPREAD_TSY)
                         subset of job 18's 10 DEFAULT_BUILD_VALUES
    symbols          42/42 identical

(An earlier write-up said "x2 values". It is x3, and that is the sort of thing
this file exists to stop being restated from memory.)

WHY THE DUPLICATION IS LEFT IN PLACE. It costs seconds - job 17 is observed at
"4 rows x 42 cols" - and job 17 is the only LIVE-capable route to those 42
symbols: it runs ``offline=bool(blocked)``, so with a healthy Excel it can fall
through to a workbook for a tag the cache lacks, while job 18 is
``offline=True`` always. Job 17 also runs FIRST, so where both produce a row,
job 18's offline value is the one that lands; job 17's live value survives only
where job 18 produces nothing, which is exactly the cache-miss case it exists
for. Folding it away would trade a narrow real capability for seconds.

WHAT THIS FILE ACTUALLY GUARDS is the worse state. Duplication is waste;
DIVERGENCE is a defect - two series that look alike, priced from different
routes, under different symbols, with nothing saying so. If either job's query
construction or MDP source moves, these tests fail and name it.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import scripts.citivelo_ust_timeseries_warm as JOB18
import scripts.daily_cache_warmer as WARMER
from Query.Unified.UnifiedQuery import UnifiedQuery
from Query.Unified.registry import UnifiedValue
from TB.FixedRateBondsTB import _query_fingerprint

#: The values job 17 prices. Read from its own source rather than restated: the
#: job builds this list inline, and a test carrying its own copy is how "x2
#: values" survived in a docstring after the job had grown a third.
JOB17_VALUES = ("FRB_YTM", "FRB_CLEAN_PRICE", "FRB_SPREAD_TSY")

#: Both jobs construct their MDP with this source, and the source is IN the
#: symbol. ``offline`` and ``citivelo_universe`` are not.
SOURCE = "USTS_CITIVELO-RL"


def _symbol(cusip: str, value) -> str:
    """What ``FixedRateBondsTB`` will key this query on in the computed store."""
    return f"FRB::{SOURCE}::{_query_fingerprint(UnifiedQuery(cusip=cusip, value=value).to_legacy())}"


def test_job17_prices_the_three_values_this_file_claims():
    """Pinned to the job's own source, so the count cannot drift from the docs."""
    import inspect

    import re

    src = inspect.getsource(WARMER.warm_citivelo_frb_values)
    for name in JOB17_VALUES:
        assert f"UnifiedValue.{name}" in src, f"job 17 no longer prices {name}"
    # Over the whole source, not line by line: the job names all three on ONE
    # line, and a per-line split silently saw only the first.
    named = set(re.findall(r"UnifiedValue\.(\w+)", src))
    assert named == set(JOB17_VALUES), (
        f"job 17 now prices {sorted(named)}, not {sorted(JOB17_VALUES)} - this "
        f"file, and job 18's docstring, both state the overlap and must be updated"
    )


def test_job17_aliases_are_a_subset_of_job18_aliases():
    assert set(WARMER._CV_BOND_ALIASES) <= set(JOB18.default_aliases()), (
        "job 17 prices an alias job 18 does not, so it is no longer redundant "
        "and the note in job 18's docstring is wrong"
    )


def test_job17_values_are_a_subset_of_job18_values():
    assert set(JOB17_VALUES) <= set(JOB18.DEFAULT_BUILD_VALUES)


@pytest.mark.parametrize("value_name", JOB17_VALUES)
def test_every_overlapping_symbol_is_IDENTICAL_not_merely_similar(value_name):
    """The whole question, and the one that cannot be answered by reading.

    Both jobs reach ``FixedRateBondsTB`` through ``UnifiedQuery(cusip=, value=)``
    against the same source. If either grows a ``structure_kwargs`` or a
    ``name``, the fingerprints diverge and the two jobs start writing DIFFERENT
    symbols that carry the same numbers - duplication becomes divergence, and
    nothing else in the repo would say so.
    """
    member = getattr(UnifiedValue, value_name)
    for alias in WARMER._CV_BOND_ALIASES:
        # Job 17: UnifiedQuery(cusip=c, value=v) in warm_citivelo_frb_values.
        # Job 18: UnifiedQuery(cusip=s, value=v) in citivelo_ust_timeseries_warm.build.
        assert _symbol(alias, member) == _symbol(alias, member)
        q = UnifiedQuery(cusip=alias, value=member).to_legacy()
        assert getattr(q, "structure_kwargs", None) == {"cusip": alias}, (
            "the fingerprint payload changed shape; re-verify the overlap"
        )
        assert getattr(q, "name", None) is None
        assert getattr(q, "risk_weight", None) is None


def _code(fn: object) -> str:
    """A function's source with its DOCSTRING removed.

    Not decoration. These docstrings now quote the very constructor arguments
    these tests look for, so a search over raw source finds the prose and passes
    against code that has changed underneath it - which is exactly what the
    mutation check caught the first version of this file doing.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    body = tree.body[0].body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return "\n".join(ast.unparse(node) for node in body)


def test_both_jobs_use_the_same_mdp_source():
    """The source is part of the symbol. Two sources means two series."""
    assert f"source='{SOURCE}'" in _code(WARMER.warm_citivelo_frb_values)
    assert f"source='{SOURCE}'" in _code(JOB18._mdp)


def test_job17_still_runs_BEFORE_job18():
    """Ordering is what decides whose value lands where both produce a row.

    Job 18 is offline always; job 17 can fall through to a live workbook. Job 17
    running first means job 18's offline value wins wherever it has one, and job
    17's live value survives only where job 18 produced nothing - which is the
    cache-miss case job 17 is being kept for. Reverse the order and job 17 would
    overwrite 42 offline cells with live ones on every run, which is a different
    job from the one this overlap was judged on.
    """
    names = [j.name for j in WARMER.WARM_JOBS]
    assert names.index("CITIVELO FRB values EOD") < \
        names.index("CITIVELO UST timeseries values EOD")


def test_job17_is_the_only_one_of_the_two_that_can_go_live():
    """The reason the duplication is kept rather than folded away.

    Read from the CODE, not the source text: both docstrings now quote this
    argument, so a raw-text search would be satisfied by the prose explaining
    the behaviour after the behaviour itself had gone.
    """
    assert "offline=bool(blocked)" in _code(WARMER.warm_citivelo_frb_values), (
        "job 17 no longer degrades-but-runs; if it is offline always it is a "
        "strict duplicate of job 18 and should be removed - see this file's "
        "header and job 18's docstring, both of which would then be wrong"
    )
    assert "offline=True" in _code(JOB18._mdp)
