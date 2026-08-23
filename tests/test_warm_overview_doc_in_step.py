"""The overview doc must list the jobs the registry actually has, in order.

`docs/eod_warm_overview.html` is the map somebody reads at 08:00 to answer "did
last night work, and what was supposed to run". It drifted to eighteen jobs
while the registry moved to twenty-one, and nothing said so — a map that is
quietly wrong is worse than no map, because it is trusted.

This does not check the prose. It checks the two things that make the doc usable
as a map: that it lists every job, and that it lists them in EXECUTION ORDER,
which is load-bearing (a value job before its store warm falls through to live
Excel on an unattended task).
"""

import importlib.util
import os
import pathlib
import re
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "eod_warm_overview.html"

#: Titles are prose, not identifiers — "SR3 EOD settles (depth 20)" in the
#: registry is "SR3 EOD settles, depth 20" in the doc. Compare on a normalised
#: form rather than demanding the doc be written in code style.
_NOISE = re.compile(r"[^a-z0-9]+")

#: Tokens that carry no identity. 'CITIVELO' prefixes half the registry and the
#: doc drops it; '(store)' is the `kind` field wearing a suffix. Dropped as
#: TOKENS rather than substrings, because both sit at a string edge where a
#: " word "-style replace never matches.
_DROP = {"citivelo", "store", "the"}


def _key(title: str) -> str:
    tokens = _NOISE.sub(" ", str(title).lower()).split()
    return " ".join(token for token in tokens if token not in _DROP)


@pytest.fixture(scope="module")
def registry_names():
    spec = importlib.util.spec_from_file_location(
        "daily_cache_warmer_doc_check",
        str(REPO_ROOT / "scripts" / "daily_cache_warmer.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return [job.name for job in module.WARM_JOBS]


@pytest.fixture(scope="module")
def doc_blocks():
    if not DOC.exists():
        pytest.skip(f"{DOC} is not present")
    text = DOC.read_text(encoding="utf-8").replace("\r\n", "\n")
    blocks = re.findall(r'\n    <div class="job">.*?</span></div>', text, flags=re.S)
    titles = []
    for block in blocks:
        match = re.search(r"</span>([^<]+)</b>", block)
        titles.append(match.group(1).strip() if match else "")
    numbers = [int(n) for n in re.findall(r'<span class="n">(\d+)</span>', text)]
    return titles, numbers, text


def test_the_doc_lists_every_job(registry_names, doc_blocks):
    titles, _numbers, _text = doc_blocks
    assert len(titles) == len(registry_names), (
        f"doc lists {len(titles)} jobs, the registry has {len(registry_names)}"
    )


def test_the_doc_lists_them_in_execution_order(registry_names, doc_blocks):
    """Order is the load-bearing part: a store warm must precede its readers."""
    titles, _numbers, _text = doc_blocks
    mismatches = [
        f"  {i}: registry {reg!r} vs doc {doc!r}"
        for i, (reg, doc) in enumerate(zip(registry_names, titles), 1)
        if _key(reg) != _key(doc)
    ]
    assert not mismatches, "doc and registry disagree:\n" + "\n".join(mismatches)


def test_the_numbering_is_sequential(doc_blocks):
    """A hand-maintained number is how the doc drifted; this is the guard."""
    _titles, numbers, _text = doc_blocks
    assert numbers == list(range(1, len(numbers) + 1)), numbers


def test_the_headline_count_is_not_stale(registry_names, doc_blocks):
    """The count in the masthead is what a reader trusts before scrolling."""
    _titles, _numbers, text = doc_blocks
    assert f"{len(registry_names)} jobs" in text, (
        f"the masthead does not say '{len(registry_names)} jobs'"
    )


def test_the_check_can_fail(registry_names, doc_blocks):
    """A doc check that cannot fail is exactly the problem it exists to solve."""
    titles, _numbers, _text = doc_blocks
    assert _key(registry_names[0]) != _key(titles[-1]), (
        "the normalisation is so lossy that unrelated titles compare equal"
    )
