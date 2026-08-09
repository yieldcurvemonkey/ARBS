# CME MBO Suite — Phase 1 (Foundation + Store) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `RVUtils/MBO` replay any product on any day in the 64 GB GLBX MDP3 archive on `D:\`, and land the results in a resumable, versioned parquet event store that the analytics phases read.

**Architecture:** A `ProductSpec` registry supplies units and ticks; a symbology dispatcher decodes each root's grammar; `build_price_grid` bands the price ladder so the busiest Treasury contract replays; a build CLI walks `(product, date)` units in a process pool and writes one parquet per `(product, date, kind)` with one row group per symbol. Analytics never open a DBN file.

**Tech Stack:** Python 3.13, numpy 2.2, pandas 2.3, pyarrow 21, numba 0.61, databento 0.83, pytest 9.

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-08-08-cme-mbo-analytics-suite-design.md`.
- Worktree: `C:\Users\chris\clee\ARBS-mbos`, branch `feat/cme-mbo-analytics-suite`. **Every git command names its tree:** `git -C C:/Users/chris/clee/ARBS-mbos ...`.
- Run python and pytest with the environment interpreter **directly**: `C:/Users/chris/anaconda3/envs/stir/python.exe`. Never `conda run` for anything that may run concurrently — parallel `conda run` invocations collide on a temp file and exit 0 with empty output, which reads as a pass.
- Fast gate must stay clean: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests -m "not slow and not network and not db"`.
- Anything that reads `D:\` is marked `@pytest.mark.slow` and skipped when the path is absent.
- The store root is `D:/mbo_store`, overridable by `ARBS_MBO_STORE`. Never inside a worktree.
- Prices stay on the integer 1e-9 DBN scale (`PRICE_SCALE = 1_000_000_000`) everywhere internally.
- `ENGINE_VERSION` is a module constant in `RVUtils/MBO/store/manifest.py`. Bump it in the same commit as any change to replay or store semantics.
- The existing 30 tests in `tests/test_mbo_book.py` are a regression gate. Only `test_price_grid_rejects_an_outlier_that_would_blow_the_ladder` may change, and Task 3 says exactly how and why.

---

### Task 1: ProductSpec registry

**Files:**
- Create: `RVUtils/MBO/products.py`
- Test: `tests/test_mbo_products.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ProductSpec` (frozen dataclass), `PRODUCTS: dict[str, ProductSpec]`, `spec_for(root: str) -> ProductSpec`, `root_of(symbol: str) -> str | None`, `check_tick(root: str, kind: str, observed_tick: float) -> Fraction`.

- [ ] **Step 1: Write the failing test**

```python
"""Known-answer tests for the product registry.

The registry is the single place that knows a contract's units.  Every number
here comes from the CME contract specification for that product; the tests
exist so that a later edit cannot quietly change one.
"""
from __future__ import annotations

from fractions import Fraction

import pytest

from RVUtils.MBO.products import PRODUCTS, check_tick, root_of, spec_for


def test_every_registered_root_is_self_consistent():
    for root, spec in PRODUCTS.items():
        assert spec.root == root
        assert spec.outright_tick > 0
        assert spec.usd_per_tick > 0
        assert spec.grammar in ("sr3", "ust")
        assert spec.quote in ("index_points", "points_32nds")


def test_sr3_is_a_rate_contract_with_an_intrinsic_bp_value():
    s = spec_for("SR3")
    assert s.outright_tick == Fraction(1, 200)          # 0.005 index points
    assert s.usd_per_tick == pytest.approx(12.50)
    assert s.usd_per_bp_per_lot == pytest.approx(25.0)


def test_treasury_products_have_no_intrinsic_bp_value():
    """A price contract's bp needs a CTD DV01, so the registry must not invent one."""
    for root in ("ZT", "ZF", "ZN", "TN", "ZB", "UB"):
        assert spec_for(root).usd_per_bp_per_lot is None


def test_root_of_finds_the_root_in_every_symbol_form():
    assert root_of("SR3Z6") == "SR3"
    assert root_of("SR3:BF Z6-H7-M7") == "SR3"
    assert root_of("SR3Z6-SR3H7") == "SR3"
    assert root_of("ZNU6") == "ZN"
    assert root_of("ZNU6-ZNZ6") == "ZN"
    assert root_of("ZN:BF M6-U6-Z6") == "ZN"
    assert root_of("TNU6-MTNU6") == "TN"
    assert root_of("WOBBLE") is None


def test_root_of_prefers_the_longest_matching_root():
    """TN and ZN both end in N; a shortest-match rule would mis-root one of them."""
    assert root_of("TNZ6") == "TN"
    assert root_of("ZNZ6") == "ZN"


def test_check_tick_accepts_the_specified_tick():
    assert check_tick("SR3", "OUTRIGHT", 0.005) == Fraction(1, 200)


def test_check_tick_raises_on_disagreement_rather_than_guessing():
    with pytest.raises(ValueError, match="tick disagreement"):
        check_tick("SR3", "OUTRIGHT", 0.5)


def test_check_tick_accepts_an_integer_multiple_of_the_spec_tick():
    """A quiet instrument may only ever print on a coarser grid than it may quote."""
    assert check_tick("SR3", "OUTRIGHT", 0.010) == Fraction(1, 200)


def test_unknown_root_raises():
    with pytest.raises(KeyError):
        spec_for("WOBBLE")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_products.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'RVUtils.MBO.products'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Per-product units, ticks and match algorithm -- the one place that knows them.

Everything in ``metrics.py`` was hard-wired to SR3.  A Treasury future is a
*price* contract: it has a tick and a dollar value per tick, and no basis-point
value at all until a CTD DV01 says what a basis point of yield is worth.  Making
that absence explicit (``usd_per_bp_per_lot = None``) is the point of this
module -- a silent 100x is the failure mode it exists to prevent.

Tick values are exact ``Fraction``s rather than floats.  A thirty-second is
1/32 and a quarter of a thirty-second is 1/128; writing those as 0.03125 and
0.0078125 happens to be exact in binary, but SR3's 0.005 is not, and one
convention for all of them is worth more than the two that happen to work.
"""
from __future__ import annotations

import dataclasses
from fractions import Fraction
from typing import Dict, Mapping, Optional

__all__ = ["PRODUCTS", "ProductSpec", "check_tick", "root_of", "spec_for"]


@dataclasses.dataclass(frozen=True)
class ProductSpec:
    """What a contract's prices mean."""

    root: str
    grammar: str                       # "sr3" | "ust"
    quote: str                         # "index_points" | "points_32nds"
    contract_unit: float
    outright_tick: Fraction
    usd_per_tick: float
    spread_tick: Mapping[str, Fraction]
    match_algo: str                    # gates the queue model in Phase 3
    usd_per_bp_per_lot: Optional[float]
    outright_tick_front: Optional[Fraction] = None

    @property
    def usd_per_point(self) -> float:
        return self.usd_per_tick / float(self.outright_tick)

    def tick_for(self, kind: str) -> Fraction:
        if kind == "OUTRIGHT":
            return self.outright_tick
        return self.spread_tick.get(kind, self.outright_tick)


def _ust(root: str, unit: float, tick: Fraction, usd_per_tick: float,
         spread_tick: Fraction, front_tick: Optional[Fraction] = None) -> ProductSpec:
    return ProductSpec(
        root=root, grammar="ust", quote="points_32nds", contract_unit=unit,
        outright_tick=tick, usd_per_tick=usd_per_tick,
        spread_tick={"CALENDAR": spread_tick, "BUTTERFLY": spread_tick,
                     "INTERCOMMODITY": spread_tick},
        match_algo="FIFO", usd_per_bp_per_lot=None, outright_tick_front=front_tick,
    )


PRODUCTS: Dict[str, ProductSpec] = {
    "SR3": ProductSpec(
        root="SR3", grammar="sr3", quote="index_points", contract_unit=1_000_000.0,
        outright_tick=Fraction(1, 200), usd_per_tick=12.50,
        spread_tick={k: Fraction(1, 2) for k in
                     ("CALENDAR", "BUTTERFLY", "CONDOR", "DOUBLE_FLY",
                      "BUNDLE_SPREAD", "BUNDLE_FLY")},
        match_algo="FIFO", usd_per_bp_per_lot=25.0,
        outright_tick_front=Fraction(1, 400),
    ),
    "ZT": _ust("ZT", 200_000.0, Fraction(1, 256), 7.8125, Fraction(1, 256)),
    "ZF": _ust("ZF", 100_000.0, Fraction(1, 128), 7.8125, Fraction(1, 128)),
    "ZN": _ust("ZN", 100_000.0, Fraction(1, 64), 15.625, Fraction(1, 128)),
    "TN": _ust("TN", 100_000.0, Fraction(1, 64), 15.625, Fraction(1, 128)),
    "ZB": _ust("ZB", 100_000.0, Fraction(1, 32), 31.25, Fraction(1, 128)),
    "UB": _ust("UB", 100_000.0, Fraction(1, 32), 31.25, Fraction(1, 128)),
}

#: Longest first, so that ``TNZ6`` does not match a shorter root that is a
#: suffix of it.
_ROOTS_BY_LENGTH = sorted(PRODUCTS, key=len, reverse=True)


def spec_for(root: str) -> ProductSpec:
    return PRODUCTS[root]


def root_of(symbol: str) -> Optional[str]:
    """The product root a raw exchange symbol belongs to, or None."""
    s = symbol.strip()
    head = s.split(":", 1)[0].split("-", 1)[0].strip()
    for root in _ROOTS_BY_LENGTH:
        if head.startswith(root):
            return root
    for root in _ROOTS_BY_LENGTH:
        if s.startswith(root):
            return root
    return None


def check_tick(root: str, kind: str, observed_tick: float,
               rel_tol: float = 1e-9) -> Fraction:
    """Cross-check the tick a spec declares against the one prices imply.

    The symbol string and the printed prices are independent signals.  A quiet
    instrument may print only on a coarser grid than it is allowed to quote on,
    so an integer multiple of the spec tick is accepted; anything else means one
    of the two signals is wrong, and guessing between them is how a 100x error
    gets in without looking like one.
    """
    spec = spec_for(root)
    want = spec.tick_for(kind)
    ratio = observed_tick / float(want)
    n = round(ratio)
    if n >= 1 and abs(ratio - n) <= max(rel_tol * n, 1e-9):
        return want
    raise ValueError(
        f"tick disagreement for {root} {kind}: the specification says "
        f"{float(want):g} but the instrument printed on a grid of "
        f"{observed_tick:g}, which is not an integer multiple of it"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_products.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Verify every tick against the CME contract specification**

The values above are the starting point, not the authority. Before committing, confirm each `outright_tick`, `usd_per_tick`, `spread_tick` and `match_algo` against the product's page on cmegroup.com, and correct any that differ. Record the check in the commit message. A wrong tick here is invisible downstream — `check_tick` only catches disagreement with the *observed* grid, and an instrument that never prints a one-tick move will not disagree with anything.

- [ ] **Step 6: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-mbos add RVUtils/MBO/products.py tests/test_mbo_products.py
git -C C:/Users/chris/clee/ARBS-mbos commit -m "feat(MBO): per-product units, ticks and match algorithm"
```

---

### Task 2: Symbology package and the Treasury grammar

**Files:**
- Create: `RVUtils/MBO/symbols/__init__.py`, `RVUtils/MBO/symbols/_ust.py`
- Move: `RVUtils/MBO/symbols.py` → `RVUtils/MBO/symbols/_sr3.py` (content unchanged apart from the module docstring)
- Test: `tests/test_mbo_symbols_ust.py`
- Modify: `tests/test_mbo_book.py` imports (`from RVUtils.MBO.symbols import bp_per_price_unit, parse_symbol` keeps working through the package `__init__`)

**Interfaces:**
- Consumes: `RVUtils.MBO.products.root_of`, `spec_for`.
- Produces: `parse_symbol(symbol: str, ref_year: int) -> ParsedSymbol`, `parse_symbols`, `ParsedSymbol` (unchanged fields plus `root: str`), and the re-exports `KINDS_QUOTED_IN_BP`, `USD_PER_BP_PER_CONTRACT`, `bp_per_price_unit`, `contract_month`, `quarterly_strip`, `MONTH_CODES`, `QUARTERLY_CODES`.

- [ ] **Step 1: Write the failing test**

```python
"""Known-answer tests for the Treasury futures symbol grammar.

Every form here was taken from the archives on D:\\ by resolving the parent
symbol, so the test is against symbology the exchange actually publishes rather
than against a grammar someone reconstructed.
"""
from __future__ import annotations

import datetime

import pytest

from RVUtils.MBO.symbols import parse_symbol

REF = 2026


def test_outright():
    p = parse_symbol("ZNU6", REF)
    assert p.kind == "OUTRIGHT"
    assert p.root == "ZN"
    assert p.legs == ("ZNU6",)
    assert p.weights == (1,)
    assert p.months == (datetime.date(2026, 9, 1),)
    assert p.n_contracts == 1


def test_calendar_spread():
    p = parse_symbol("ZNU6-ZNZ6", REF)
    assert p.kind == "CALENDAR"
    assert p.legs == ("ZNU6", "ZNZ6")
    assert p.weights == (1, -1)
    assert p.n_contracts == 2
    assert p.span_months() == 3


def test_listed_butterfly():
    p = parse_symbol("ZN:BF M6-U6-Z6", REF)
    assert p.kind == "BUTTERFLY"
    assert p.legs == ("ZNM6", "ZNU6", "ZNZ6")
    assert p.weights == (1, -2, 1)
    assert p.n_contracts == 4


def test_micro_intercommodity_legs_are_modelled():
    """Unlike SR3's inter-commodity spreads, full-versus-micro legs are known."""
    p = parse_symbol("TNU6-MTNU6", REF)
    assert p.kind == "INTERCOMMODITY"
    assert p.legs == ("TNU6", "MTNU6")
    assert p.weights == (1, -1)
    assert p.root == "TN"


def test_ultra_bond_versus_micro():
    p = parse_symbol("UBZ6-MWNZ6", REF)
    assert p.kind == "INTERCOMMODITY"
    assert p.legs == ("UBZ6", "MWNZ6")


def test_year_digit_resolves_forward_from_the_reference_year():
    assert parse_symbol("ZNH7", REF).months == (datetime.date(2027, 3, 1),)
    assert parse_symbol("ZNH5", REF).months == (datetime.date(2035, 3, 1),)


def test_treasury_kinds_are_not_quoted_in_basis_points():
    """SR3 spreads quote in bp; a Treasury spread quotes in price points."""
    for sym in ("ZNU6-ZNZ6", "ZN:BF M6-U6-Z6"):
        assert parse_symbol(sym, REF).bp_per_price_unit == 100.0


def test_unknown_root_is_other_and_does_not_raise():
    p = parse_symbol("XYZQ9", REF)
    assert p.kind == "OTHER"
    assert p.legs == ()


def test_sr3_parsing_is_unchanged_by_the_split():
    p = parse_symbol("SR3:BF Z6-H7-M7", REF)
    assert p.kind == "BUTTERFLY"
    assert p.root == "SR3"
    assert p.weights == (1, -2, 1)
    assert p.bp_per_price_unit == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_symbols_ust.py -v`
Expected: FAIL — `parse_symbol("ZNU6", 2026).kind == "OTHER"`, since the current parser only knows `SR3`.

- [ ] **Step 3: Write minimal implementation**

Move the existing file, add `root` to `ParsedSymbol`, write `_ust.py`, and dispatch:

```python
# RVUtils/MBO/symbols/__init__.py
"""Exchange symbol -> kind, legs and leg weights, dispatched by product root.

The leg structure lives only in the symbol string -- the ``definition`` schema is
a separate file we do not have -- so this package is the single place that
decodes it.  Each root's grammar is its own module because they genuinely differ:
SR3 lists packs, bundles, condors and double flies with two different leg
separators, and the Treasury roots list none of those.
"""
from __future__ import annotations

from typing import Dict, Sequence

from RVUtils.MBO.products import root_of, spec_for
from RVUtils.MBO.symbols._sr3 import (
    KINDS_QUOTED_IN_BP,
    MONTH_CODES,
    QUARTERLY_CODES,
    USD_PER_BP_PER_CONTRACT,
    ParsedSymbol,
    bp_per_price_unit,
    contract_month,
    quarterly_strip,
)
from RVUtils.MBO.symbols._sr3 import parse_symbol as _parse_sr3
from RVUtils.MBO.symbols._ust import parse_symbol as _parse_ust

__all__ = [
    "KINDS_QUOTED_IN_BP", "MONTH_CODES", "QUARTERLY_CODES",
    "USD_PER_BP_PER_CONTRACT", "ParsedSymbol", "bp_per_price_unit",
    "contract_month", "parse_symbol", "parse_symbols", "quarterly_strip",
]

_GRAMMARS = {"sr3": _parse_sr3, "ust": _parse_ust}


def parse_symbol(symbol: str, ref_year: int) -> ParsedSymbol:
    """Decode one exchange symbol.  Unknown roots come back ``kind='OTHER'``.

    Never raises on an unrecognised symbol: a single odd string must not be able
    to stop a seventy-nine day build.
    """
    root = root_of(symbol)
    if root is None:
        return ParsedSymbol(symbol, "OTHER", (), (), (), symbol, root="")
    return _GRAMMARS[spec_for(root).grammar](symbol, ref_year)


def parse_symbols(symbols: Sequence[str], ref_year: int) -> Dict[str, ParsedSymbol]:
    return {s: parse_symbol(s, ref_year) for s in symbols}
```

```python
# RVUtils/MBO/symbols/_ust.py
"""Treasury futures symbology: outright, calendar, listed butterfly, micro spread.

The four forms below are every form present in the ZT/ZF/ZN/TN/ZB/UB archives.
There are no packs, bundles or condors on these roots.

``INTERCOMMODITY`` here means the full-size contract against its micro
(``TNU6-MTNU6``, ``UBZ6-MWNZ6``).  Unlike SR3's inter-commodity spreads, whose
far leg is a different product we do not carry, both legs are known, so they are
populated.
"""
from __future__ import annotations

import datetime
import re
from typing import List, Optional, Tuple

from RVUtils.MBO.products import root_of
from RVUtils.MBO.symbols._sr3 import MONTH_CODES, ParsedSymbol, contract_month

__all__ = ["parse_symbol"]

_MY = r"([FGHJKMNQUVXZ])(\d)"
_OUTRIGHT_RE = re.compile(rf"^([A-Z0-9]+){_MY}$")
_PAIR_RE = re.compile(rf"^([A-Z0-9]+){_MY}-([A-Z0-9]+){_MY}$")
_BF_RE = re.compile(rf"^([A-Z0-9]+):BF\s+{_MY}-{_MY}-{_MY}$")


def _other(s: str, root: str) -> ParsedSymbol:
    return ParsedSymbol(s, "OTHER", (), (), (), s, root=root)


def parse_symbol(symbol: str, ref_year: int) -> ParsedSymbol:
    s = symbol.strip()
    root = root_of(s) or ""

    m = _BF_RE.match(s)
    if m:
        r = m.group(1)
        months = tuple(contract_month(m.group(i), m.group(i + 1), ref_year)
                       for i in (2, 4, 6))
        legs = tuple(f"{r}{m.group(i)}{m.group(i + 1)}" for i in (2, 4, 6))
        step = ((months[1].year - months[0].year) * 12
                + (months[1].month - months[0].month))
        return ParsedSymbol(s, "BUTTERFLY", legs, (1, -2, 1), months,
                            f"{step}m fly", root=root)

    m = _PAIR_RE.match(s)
    if m:
        r1, r2 = m.group(1), m.group(4)
        a = contract_month(m.group(2), m.group(3), ref_year)
        b = contract_month(m.group(5), m.group(6), ref_year)
        legs = (f"{r1}{m.group(2)}{m.group(3)}", f"{r2}{m.group(5)}{m.group(6)}")
        if r1 == r2:
            span = (b.year - a.year) * 12 + (b.month - a.month)
            return ParsedSymbol(s, "CALENDAR", legs, (1, -1), (a, b),
                                f"{span}m calendar", root=root)
        return ParsedSymbol(s, "INTERCOMMODITY", legs, (1, -1), (a, b),
                            f"{r1} vs {r2}", root=root)

    m = _OUTRIGHT_RE.match(s)
    if m:
        month = contract_month(m.group(2), m.group(3), ref_year)
        return ParsedSymbol(s, "OUTRIGHT", (s,), (1,), (month,), s, root=root)

    return _other(s, root)
```

In `_sr3.py`, add `root: str = "SR3"` as the last field of `ParsedSymbol` (it has a default, so the existing positional constructions keep working) and set `root=root_of(s) or ""` on each returned instance.

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_symbols_ust.py tests/test_mbo_book.py -v`
Expected: PASS. The 30 existing tests must still pass unmodified — that is the point of keeping `_sr3.py` byte-identical apart from the docstring and the `root` field.

- [ ] **Step 5: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-mbos add RVUtils/MBO/symbols tests/test_mbo_symbols_ust.py
git -C C:/Users/chris/clee/ARBS-mbos commit -m "feat(MBO): Treasury futures symbol grammar behind a root dispatcher"
```

---

### Task 3: Banded price ladder

**Files:**
- Modify: `RVUtils/MBO/book.py` (`build_price_grid`, `replay_book`, `ReplayResult`; **the `_replay` numba kernel is not touched**)
- Modify: `tests/test_mbo_book.py` (one existing test replaced, five added)

**Interfaces:**
- Consumes: nothing new.
- Produces: `build_price_grid(price, *, coverage=0.9999, pad_ticks=200, max_slots=MAX_PRICE_SLOTS) -> PriceGrid`; `PriceGrid` gains `px_max` property; `ReplayResult` gains `n_unindexed: int`, `n_out_of_band: int`, `band: tuple[float, float]`; `replay_book` gains `assert_band: bool = True`.

**Why the kernel is not touched.** Re-reading `_replay`: an `A` whose price index is `-1` never sets `ord_gen[o]`, so a later `C` or `M` on that order is already a correct no-op, and an `M` that moves an order out of the band clears `ord_gen[o]` before failing to re-add it. The kernel is already right about unindexable orders. What it does not do is *say* so. So the change is entirely outside it: choose a band, assert vectorised that nothing outside the band could have been at the touch, and count what was skipped.

- [ ] **Step 1: Replace the outlier test and write the new failing tests**

Delete `test_price_grid_rejects_an_outlier_that_would_blow_the_ladder`. It asserts the behaviour that makes `ZNU6` — the most active instrument in the archive — unreplayable. Replace it and add the band tests:

```python
# --------------------------------------------------------------------------- #
# banded price grid
# --------------------------------------------------------------------------- #

def test_price_grid_bands_around_the_mass_instead_of_the_extremes():
    """The real case: ZNU6 prints 6.76 M records in a ~900 tick band and 57 at
    absurd prices, one of them 109,080.00.  Sizing the ladder to the extremes
    needs seven million slots and raises; sizing it to the mass does not."""
    px = np.concatenate([
        np.arange(108.0, 109.0, 0.015625),
        np.array([50.0, 88.1875, 109_080.0]),
    ])
    g = build_price_grid((px * PRICE_SCALE).round().astype(np.int64))
    assert g.n_slots < 2_000
    assert g.px_min / PRICE_SCALE == pytest.approx(108.0, abs=4.0)
    assert g.px_max / PRICE_SCALE < 200.0


def test_price_grid_band_still_covers_every_ordinary_price():
    px = np.arange(96.0, 96.5, 0.005)
    g = build_price_grid((px * PRICE_SCALE).round().astype(np.int64))
    off = (px * PRICE_SCALE).round().astype(np.int64) - g.px_min
    assert (off >= 0).all()
    assert (off // g.tick < g.n_slots).all()


def test_tick_is_taken_from_inside_the_band_not_from_an_outlier():
    """An off-lattice outlier would collapse a gcd taken over every price."""
    px = np.concatenate([np.arange(96.0, 96.2, 0.005), np.array([1234.5678901])])
    g = build_price_grid((px * PRICE_SCALE).round().astype(np.int64))
    assert g.tick == 5_000_000


def test_replay_counts_orders_it_could_not_index():
    r = replay_book(make([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "A", 96.01, 7, 2, 0),
        (1, "A", "B", 50.00, 1, 3, L),      # far below the band
    ]))
    assert r.n_unindexed == 1
    assert r.tob.iloc[-1]["bid_px"] == 96.00      # the stub is not the touch


def test_replay_raises_when_an_out_of_band_order_could_have_been_the_touch():
    """A bid above the band is not a stub -- it means the band is wrong, and
    reporting a touch computed without it would be a silent error."""
    px_hi = 96.00 + 1e-3
    with pytest.raises(ValueError, match="out of band"):
        replay_book(
            make([
                (1, "A", "B", 96.00, 10, 1, 0),
                (1, "A", "A", 96.01, 7, 2, L),
            ]),
            grid=build_price_grid(
                (np.array([95.99, 96.00, 96.01]) * PRICE_SCALE).round().astype(np.int64)
            )._replace_for_test(px_max_price=px_hi),
        )


def test_assert_band_can_be_disabled_for_a_deliberate_narrow_band():
    r = replay_book(
        make([
            (1, "A", "B", 96.00, 10, 1, 0),
            (1, "A", "A", 96.01, 7, 2, L),
        ]),
        grid=build_price_grid((np.array([96.00, 96.005]) * PRICE_SCALE).round().astype(np.int64)),
        assert_band=False,
    )
    assert r.n_out_of_band >= 1
```

Drop `_replace_for_test` — instead construct the narrow grid directly, since `PriceGrid` is a plain frozen dataclass:

```python
def test_replay_raises_when_an_out_of_band_order_could_have_been_the_touch():
    narrow = PriceGrid(px_min=int(95.98 * PRICE_SCALE), tick=5_000_000, n_slots=3)
    with pytest.raises(ValueError, match="out of band"):
        replay_book(
            make([
                (1, "A", "B", 96.10, 10, 1, 0),   # above the band, on the bid
                (1, "A", "A", 96.01, 7, 2, L),
            ]),
            grid=narrow,
        )
```

Add `PriceGrid` to the imports at the top of the test module.

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_book.py -v -k "band or unindexed or outlier or tick_is_taken"`
Expected: FAIL — `build_price_grid` still raises on the outlier, and `ReplayResult` has no `n_unindexed`.

- [ ] **Step 3: Write the implementation**

In `book.py`, replace `build_price_grid` and extend `replay_book`:

```python
def build_price_grid(
    price: np.ndarray,
    *,
    coverage: float = 0.9999,
    pad_ticks: int = 200,
    max_slots: int = MAX_PRICE_SLOTS,
) -> PriceGrid:
    """Infer the tick lattice and a price band from the prices actually printed.

    The tick is the gcd of price offsets *within the band*, so it adapts to the
    quarter-tick front outright, the half-tick back of the strip and the finer
    grids spread instruments quote on, without any of them being hard-coded.

    The band matters because a dense ladder is only sane while it stays small.
    ``ZNU6`` prints 6.76 M records inside about nine hundred ticks and 57 outside
    it -- one ask at 109,080.00 and stub bids down at 50.00 -- and a ladder sized
    to the extremes needs seven million slots.  The band is a robust quantile of
    the live prices, widened by ``pad_ticks`` and by the same width again, which
    leaves every real quote inside it and the stubs out.

    Orders outside the band are not silently ignored: :func:`replay_book` counts
    them and asserts that none of them could have been at the touch.
    """
    px = price[price != UNDEF_PRICE].astype(np.int64)
    if px.size == 0:
        return PriceGrid(px_min=0, tick=1, n_slots=1)

    lo_q, hi_q = (1.0 - coverage) / 2.0, 1.0 - (1.0 - coverage) / 2.0
    lo = int(np.quantile(px, lo_q))
    hi = int(np.quantile(px, hi_q))
    inside = px[(px >= lo) & (px <= hi)]
    if inside.size == 0:
        inside = px

    base = int(inside.min())
    offs = np.unique(inside - base)
    tick = int(np.gcd.reduce(offs)) if offs.size > 1 else 0
    if tick <= 0:
        tick = 1

    width = int(inside.max()) - base
    pad = max(int(pad_ticks) * tick, width)
    px_min = base - pad
    px_max = int(inside.max()) + pad
    n_slots = (px_max - px_min) // tick + 1

    if n_slots > max_slots:
        # Shrink symmetrically toward the median rather than failing: a ladder
        # this wide means the quantile band itself is wide, and the alternative
        # is refusing to replay the instrument at all.
        keep = (max_slots - 1) * tick
        mid = int(np.median(inside))
        px_min = mid - keep // 2
        px_max = px_min + keep
        n_slots = (px_max - px_min) // tick + 1

    return PriceGrid(px_min=int(px_min), tick=int(tick), n_slots=int(n_slots))
```

Add to `PriceGrid`:

```python
    @property
    def px_max(self) -> int:
        """Price of the last slot, on the integer 1e-9 scale."""
        return self.px_min + (self.n_slots - 1) * self.tick
```

Add to `ReplayResult`:

```python
    #: Records whose price could not be placed on the ladder -- outside the band
    #: or off its lattice.  The kernel already treats these correctly (the order
    #: never rests, and its later cancel or modify is a no-op); this is what
    #: makes that visible rather than silent.
    n_unindexed: int = 0
    n_out_of_band: int = 0
    band: Tuple[float, float] = (float("nan"), float("nan"))
```

In `replay_book`, after `px_idx` is computed and before the kernel call:

```python
    unindexed = live & (px_idx < 0)
    n_unindexed = int(unindexed.sum())
    n_out_of_band = int((live & ((price < g.px_min) | (price > g.px_max))).sum())

    if assert_band and n_out_of_band:
        oob = live & ((price < g.px_min) | (price > g.px_max))
        is_bid = side == _BID
        is_ask = side == _ASK
        bad_bid = oob & is_bid & (price > g.px_max)
        bad_ask = oob & is_ask & (price < g.px_min)
        if bad_bid.any() or bad_ask.any():
            worst = price[bad_bid].max() if bad_bid.any() else price[bad_ask].min()
            raise ValueError(
                f"{int(bad_bid.sum() + bad_ask.sum())} order(s) out of band on the "
                f"side that would put them at the touch (worst {worst / PRICE_SCALE:g}, "
                f"band [{g.px_min / PRICE_SCALE:g}, {g.px_max / PRICE_SCALE:g}]). "
                f"Widen the band; do not ignore them."
            )
```

`side` is already decoded above `px_idx` in the current function; if not, move its decode earlier. Populate the three new fields on the returned `ReplayResult`.

- [ ] **Step 4: Run the whole book test module**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_book.py -v`
Expected: PASS, 35 tests (30 existing minus 1 replaced plus 6 new).

- [ ] **Step 5: Mutation-test the band assertion**

Change `price > g.px_max` to `price >= g.px_max` in the `bad_bid` mask and confirm `test_replay_raises_when_an_out_of_band_order_could_have_been_the_touch` still passes but a boundary case does not — then revert. Then delete the `if bad_bid.any() or bad_ask.any():` guard entirely and confirm `test_replay_counts_orders_it_could_not_index` *fails* (it would now raise on a harmless stub). A test that cannot fail when the code is wrong is not a test.

- [ ] **Step 6: Verify against the real failure**

```bash
C:/Users/chris/anaconda3/envs/stir/python.exe -c "import sys; sys.path.insert(0,'C:/Users/chris/clee/ARBS-mbos'); import databento as db, numpy as np; from RVUtils.MBO.book import build_price_grid, replay_book; s=db.DBNStore.from_file('D:/mbo_work/probe/glbx-mdp3-20260714.mbo.dbn.zst'); m={int(e['symbol']):k for k,v in s.metadata.mappings.items() for e in v if e['symbol']}; want=[i for i,k in m.items() if k=='ZNU6'][0]; parts=[a[a['instrument_id']==want] for a in s.to_ndarray(count=5_000_000)]; rec=np.concatenate(parts); r=replay_book(rec); print('records',rec.size,'tob',len(r.tob),'unindexed',r.n_unindexed,'oob',r.n_out_of_band,'crossed',r.crossed_events)"
```

Expected: it completes, reporting roughly 6.76 M records, a large top-of-book count, `unindexed` around 57, and `crossed` small. Before this task it raised.

- [ ] **Step 7: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-mbos add RVUtils/MBO/book.py tests/test_mbo_book.py
git -C C:/Users/chris/clee/ARBS-mbos commit -m "fix(MBO): band the price ladder so the busiest Treasury contract replays"
```

---

### Task 4: Archive index and per-session source

**Files:**
- Create: `RVUtils/MBO/archive.py`
- Modify: `RVUtils/MBO/source.py` (namespaced cache, `(product, date)` identity)
- Test: `tests/test_mbo_archive.py`

**Interfaces:**
- Consumes: `RVUtils.MBO.products.PRODUCTS`.
- Produces: `MboArchive(roots: Sequence[str])` with `.sessions() -> pd.DataFrame` (columns `product, date, zip_path, member, member_bytes`), `.open_session(product, date) -> ContextManager[str]` yielding a readable local path, `ARCHIVE_ROOTS` default `("D:/sr3_mbo", "D:/zt_mbo", ...)`; `session_key(product, date) -> str`.

- [ ] **Step 1: Write the failing test**

```python
"""Archive indexing tests.

Built against a synthetic zip so they run in the fast gate; the real archives on
D:\\ are exercised by the marked test at the end.
"""
from __future__ import annotations

import os
import zipfile

import pytest

from RVUtils.MBO.archive import MboArchive, session_key


def _fake_archive(tmp_path, product, dates):
    d = tmp_path / f"{product.lower()}_mbo"
    d.mkdir()
    zp = d / "GLBX-20260808-FAKE.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("metadata.json", "{}")
        for dt in dates:
            z.writestr(f"glbx-mdp3-{dt}.mbo.dbn.zst", b"\x00" * 32)
    return str(d)


def test_sessions_lists_one_row_per_day(tmp_path):
    _fake_archive(tmp_path, "ZN", ["20260505", "20260506"])
    a = MboArchive([str(tmp_path / "zn_mbo")])
    s = a.sessions()
    assert list(s["product"]) == ["ZN", "ZN"]
    assert [str(x) for x in s["date"]] == ["2026-05-05", "2026-05-06"]
    assert (s["member_bytes"] > 0).all()


def test_sessions_merges_two_zips_of_one_product(tmp_path):
    d = tmp_path / "sr3_mbo"
    d.mkdir()
    for name, dates in (("a.zip", ["20260601"]), ("b.zip", ["20260602"])):
        with zipfile.ZipFile(d / name, "w") as z:
            z.writestr(f"glbx-mdp3-{dates[0]}.mbo.dbn.zst", b"\x00" * 16)
    s = MboArchive([str(d)]).sessions()
    assert len(s) == 2
    assert s["zip_path"].nunique() == 2


def test_duplicate_session_across_zips_raises_rather_than_picking_one(tmp_path):
    d = tmp_path / "zn_mbo"
    d.mkdir()
    for name in ("a.zip", "b.zip"):
        with zipfile.ZipFile(d / name, "w") as z:
            z.writestr("glbx-mdp3-20260601.mbo.dbn.zst", b"\x00" * 16)
    with pytest.raises(ValueError, match="appears in more than one archive"):
        MboArchive([str(d)]).sessions()


def test_session_key_is_stable_and_filesystem_safe():
    import datetime
    assert session_key("ZN", datetime.date(2026, 7, 14)) == "ZN/2026-07-14"


def test_open_session_yields_a_readable_path(tmp_path):
    _fake_archive(tmp_path, "ZN", ["20260505"])
    a = MboArchive([str(tmp_path / "zn_mbo")])
    import datetime
    with a.open_session("ZN", datetime.date(2026, 5, 5)) as path:
        assert os.path.getsize(path) == 32
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_archive.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'RVUtils.MBO.archive'`

- [ ] **Step 3: Write the implementation**

```python
"""Finding a session inside the zip archives, without unpacking 64 GB.

Each product's directory holds one or more Databento batch zips, and each zip
holds one ``glbx-mdp3-YYYYMMDD.mbo.dbn.zst`` member per session.  The members are
already zstd-compressed, so the zip stores them uncompressed and reading one is a
copy rather than a decompression.

A session is extracted to a scratch file rather than streamed into memory.  The
largest SR3 member is 1.6 GB and a process pool of workers each holding one would
not fit; a scratch file costs disk that is already budgeted and lets the decoder
seek.
"""
from __future__ import annotations

import contextlib
import datetime
import os
import re
import shutil
import zipfile
from typing import Iterator, List, Optional, Sequence

import pandas as pd

from RVUtils.MBO.products import PRODUCTS

__all__ = ["ARCHIVE_ROOTS", "MboArchive", "session_key"]

ARCHIVE_ROOTS: Sequence[str] = tuple(
    f"D:/{root.lower()}_mbo" for root in PRODUCTS
)

_MEMBER_RE = re.compile(r"glbx-mdp3-(\d{8})\.mbo\.dbn\.zst$")
_SCRATCH = os.environ.get("ARBS_MBO_SCRATCH", "D:/mbo_work/sessions")


def session_key(product: str, date: datetime.date) -> str:
    return f"{product}/{date.isoformat()}"


class MboArchive:
    """An index over the per-product zip archives."""

    def __init__(self, roots: Optional[Sequence[str]] = None) -> None:
        self.roots = list(roots) if roots is not None else list(ARCHIVE_ROOTS)
        self._sessions: Optional[pd.DataFrame] = None

    def sessions(self, force: bool = False) -> pd.DataFrame:
        if self._sessions is not None and not force:
            return self._sessions
        rows: List[dict] = []
        for root in self.roots:
            if not os.path.isdir(root):
                continue
            product = os.path.basename(root.rstrip("/\\")).split("_")[0].upper()
            for fn in sorted(os.listdir(root)):
                if not fn.endswith(".zip"):
                    continue
                zp = os.path.join(root, fn)
                with zipfile.ZipFile(zp) as z:
                    for info in z.infolist():
                        m = _MEMBER_RE.search(info.filename)
                        if not m:
                            continue
                        rows.append({
                            "product": product,
                            "date": datetime.date(int(m.group(1)[:4]),
                                                  int(m.group(1)[4:6]),
                                                  int(m.group(1)[6:])),
                            "zip_path": zp,
                            "member": info.filename,
                            "member_bytes": int(info.file_size),
                        })
        df = pd.DataFrame(rows)
        if df.empty:
            self._sessions = df
            return df
        dup = df.duplicated(["product", "date"], keep=False)
        if dup.any():
            bad = df[dup].sort_values(["product", "date"])
            raise ValueError(
                "a session appears in more than one archive, which would make the "
                f"build non-deterministic:\n{bad.to_string(index=False)}"
            )
        df = df.sort_values(["product", "date"]).reset_index(drop=True)
        self._sessions = df
        return df

    @contextlib.contextmanager
    def open_session(self, product: str, date: datetime.date,
                     scratch: Optional[str] = None, keep: bool = False) -> Iterator[str]:
        """Yield a local path to one session's DBN file."""
        s = self.sessions()
        hit = s[(s["product"] == product) & (s["date"] == date)]
        if hit.empty:
            raise KeyError(f"no session {session_key(product, date)} in {self.roots}")
        row = hit.iloc[0]
        out_dir = scratch or _SCRATCH
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"{product}_{os.path.basename(row['member'])}")
        if not os.path.exists(out) or os.path.getsize(out) != row["member_bytes"]:
            tmp = out + ".part"
            with zipfile.ZipFile(row["zip_path"]) as z, z.open(row["member"]) as src, \
                    open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1 << 24)
            os.replace(tmp, out)
        try:
            yield out
        finally:
            if not keep:
                with contextlib.suppress(OSError):
                    os.remove(out)
```

In `source.py`, change `_instrument_path` and the two catalogue paths to sit under a per-session subdirectory, and make the session identity explicit:

```python
    def _cache_path(self, name: str) -> str:
        sub = os.path.join(self.cache_dir, self.product, self.session_date.isoformat())
        os.makedirs(sub, exist_ok=True)
        return os.path.join(sub, name)
```

`product` and `session_date` are new `MboSource` fields, defaulted from the metadata (`session_start.date()`) and from `products.root_of` on any mapped symbol.

- [ ] **Step 4: Run tests**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_archive.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-mbos add RVUtils/MBO/archive.py RVUtils/MBO/source.py tests/test_mbo_archive.py
git -C C:/Users/chris/clee/ARBS-mbos commit -m "feat(MBO): archive index and per-session cache namespacing"
```

---

### Task 5: Store schema and writer

**Files:**
- Create: `RVUtils/MBO/store/__init__.py`, `RVUtils/MBO/store/schema.py`, `RVUtils/MBO/store/writer.py`
- Test: `tests/test_mbo_store.py`

**Interfaces:**
- Consumes: `ReplayResult`, `PriceGrid`, `ParsedSymbol`, `ProductSpec`.
- Produces: `TOB_SCHEMA`, `TRADES_SCHEMA`, `CATALOG_SCHEMA` (`pyarrow.Schema`); `StoreWriter(root, product, date, engine_version)` with `.add(symbol, parsed, grid, result)`, `.close() -> dict`; `store_path(root, kind, product, date) -> str`.

- [ ] **Step 1: Write the failing test**

```python
"""Store round-trip tests.

The load-bearing property is that reading the store back gives exactly what the
replay produced.  A store that is 99.99% right is a store that produces plausible
research, which is worse than one that is obviously broken.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from RVUtils.MBO.book import PRICE_SCALE, build_price_grid, replay_book
from RVUtils.MBO.store.schema import CATALOG_SCHEMA, TOB_SCHEMA, TRADES_SCHEMA
from RVUtils.MBO.store.writer import StoreWriter, store_path
from RVUtils.MBO.symbols import parse_symbol
from tests.test_mbo_book import make

DATE = datetime.date(2026, 7, 14)


def _one(tmp_path, symbol="SR3Z6"):
    rec = make([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "A", 96.01, 7, 2, L_) if False else (1, "A", "A", 96.01, 7, 2, 128),
        (2, "T", "B", 96.01, 3, 9, 0),
        (2, "F", "A", 96.01, 3, 2, 0),
        (3, "C", "A", 96.01, 3, 2, 128),
    ])
    g = build_price_grid(rec["price"].astype(np.int64))
    r = replay_book(rec, grid=g)
    w = StoreWriter(str(tmp_path), "SR3", DATE, engine_version="test")
    w.add(symbol, parse_symbol(symbol, 2026), g, r)
    stats = w.close()
    return g, r, stats


def test_writer_creates_all_three_tables(tmp_path):
    _one(tmp_path)
    for kind in ("tob", "trades", "catalog"):
        assert pq.read_metadata(store_path(str(tmp_path), kind, "SR3", DATE)).num_rows >= 1


def test_tob_round_trips_to_the_same_prices(tmp_path):
    g, r, _ = _one(tmp_path)
    t = pq.read_table(store_path(str(tmp_path), "tob", "SR3", DATE)).to_pandas()
    idx = t["bid_idx"].to_numpy()
    px = np.where(idx >= 0, (g.px_min + idx * g.tick) / PRICE_SCALE, np.nan)
    np.testing.assert_allclose(px, r.tob["bid_px"].to_numpy(), equal_nan=True)


def test_trades_carry_the_book_that_prevailed_before_them(tmp_path):
    g, r, _ = _one(tmp_path)
    t = pq.read_table(store_path(str(tmp_path), "trades", "SR3", DATE)).to_pandas()
    assert len(t) == 1
    assert t.iloc[0]["size"] == 3
    assert t.iloc[0]["aggressor"] == 1
    # the book before the trade's packet had 96.00 bid / 96.01 ask
    assert (g.px_min + t.iloc[0]["prev_bid_idx"] * g.tick) / PRICE_SCALE == pytest.approx(96.00)
    assert (g.px_min + t.iloc[0]["prev_ask_idx"] * g.tick) / PRICE_SCALE == pytest.approx(96.01)


def test_catalog_carries_the_grid_so_tick_indices_can_be_decoded(tmp_path):
    g, _, _ = _one(tmp_path)
    c = pq.read_table(store_path(str(tmp_path), "catalog", "SR3", DATE)).to_pandas()
    row = c.iloc[0]
    assert row["px_min"] == g.px_min
    assert row["tick"] == g.tick
    assert row["n_slots"] == g.n_slots
    assert row["kind"] == "BUTTERFLY" or row["kind"] == "OUTRIGHT"


def test_one_row_group_per_symbol(tmp_path):
    rec = make([(1, "A", "B", 96.0, 5, 1, 128)])
    g = build_price_grid(rec["price"].astype(np.int64))
    r = replay_book(rec, grid=g)
    w = StoreWriter(str(tmp_path), "SR3", DATE, engine_version="test")
    for sym in ("SR3Z6", "SR3H7", "SR3M7"):
        w.add(sym, parse_symbol(sym, 2026), g, r)
    w.close()
    md = pq.read_metadata(store_path(str(tmp_path), "tob", "SR3", DATE))
    assert md.num_row_groups == 3


def test_writing_the_same_session_twice_is_atomic(tmp_path):
    _one(tmp_path)
    first = pq.read_metadata(store_path(str(tmp_path), "tob", "SR3", DATE)).num_rows
    _one(tmp_path)
    assert pq.read_metadata(store_path(str(tmp_path), "tob", "SR3", DATE)).num_rows == first
```

Fix the awkward `L_` line when writing the test for real — the row is simply `(1, "A", "A", 96.01, 7, 2, 128)`.

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_store.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'RVUtils.MBO.store'`

- [ ] **Step 3: Write the implementation**

`schema.py` defines the three Arrow schemas exactly as in the design (§4.2–§4.3), with `symbol` as `pa.dictionary(pa.int32(), pa.string())`, timestamps as `pa.int64()`, tick indices as `pa.int32()`, counts as `pa.int16()`, `aggressor` as `pa.int8()`.

`writer.py`:

```python
"""Replay results -> one parquet per (product, date, kind), row group per symbol.

One file per session rather than one per instrument: SR3 alone would otherwise
produce about 190,000 small files.  Row groups are written in symbol order as the
replay loop produces them, so a single-symbol read across a quarter is one file
open per day with row-group pruning, and no global sort is ever needed.

Prices are stored as integer tick indices and the grid lives in the catalogue.
The reason is exactness rather than size: 0.005 is not representable in binary
floating point, so on floats "is this market one tick wide" has to be asked with
a tolerance, and on tick indices it is an integer comparison.
"""
```

with `StoreWriter` opening three `pq.ParquetWriter`s on `.part` paths (`version="2.6"`, `compression="zstd"`, `compression_level=9`, `write_statistics=True`), `add()` appending one row group to each, and `close()` closing them and `os.replace`-ing all three into place together — so a killed build never leaves a half-written session that resume would treat as complete.

- [ ] **Step 4: Run tests**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_store.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-mbos add RVUtils/MBO/store tests/test_mbo_store.py
git -C C:/Users/chris/clee/ARBS-mbos commit -m "feat(MBO): event store schema and session writer"
```

---

### Task 6: Manifest, resume and engine versioning

**Files:**
- Create: `RVUtils/MBO/store/manifest.py`
- Test: `tests/test_mbo_manifest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ENGINE_VERSION: str`, `MANIFEST_SCHEMA`, `append(root, row: dict) -> None`, `read(root) -> pd.DataFrame`, `is_complete(root, product, date, kind, engine_version) -> bool`, `pending(root, sessions: pd.DataFrame, kinds, engine_version) -> pd.DataFrame`.

- [ ] **Step 1: Write the failing test**

```python
"""Manifest and resume tests.

Resume that ignores the engine version is how a store ends up holding two
vintages that nothing can tell apart afterwards.
"""
from __future__ import annotations

import datetime

import pandas as pd
import pytest

from RVUtils.MBO.store import manifest as mf

D1 = datetime.date(2026, 7, 14)
D2 = datetime.date(2026, 7, 15)


def _row(product="ZN", date=D1, kind="tob", version="v1", status="OK"):
    return {"product": product, "date": date, "tier": "wide", "kind": kind,
            "engine_version": version, "source_zip": "z.zip", "source_member": "m",
            "source_bytes": 1, "n_records": 10, "n_symbols": 1, "n_rows": 5,
            "bytes_written": 100, "wall_s": 0.1, "crossed_events": 0,
            "trades_outside_book": 0, "status": status, "error": ""}


def test_append_then_read(tmp_path):
    mf.append(str(tmp_path), _row())
    df = mf.read(str(tmp_path))
    assert len(df) == 1
    assert df.iloc[0]["product"] == "ZN"


def test_is_complete_only_for_ok_status(tmp_path):
    mf.append(str(tmp_path), _row(status="FAILED"))
    assert not mf.is_complete(str(tmp_path), "ZN", D1, "tob", "v1")


def test_is_complete_requires_a_matching_engine_version(tmp_path):
    mf.append(str(tmp_path), _row(version="v1"))
    assert mf.is_complete(str(tmp_path), "ZN", D1, "tob", "v1")
    assert not mf.is_complete(str(tmp_path), "ZN", D1, "tob", "v2")


def test_a_later_row_supersedes_an_earlier_one(tmp_path):
    mf.append(str(tmp_path), _row(status="FAILED"))
    mf.append(str(tmp_path), _row(status="OK"))
    assert mf.is_complete(str(tmp_path), "ZN", D1, "tob", "v1")


def test_pending_lists_only_unbuilt_units(tmp_path):
    mf.append(str(tmp_path), _row(date=D1))
    sessions = pd.DataFrame({"product": ["ZN", "ZN"], "date": [D1, D2]})
    p = mf.pending(str(tmp_path), sessions, kinds=("tob",), engine_version="v1")
    assert list(p["date"]) == [D2]


def test_read_on_an_empty_store_is_an_empty_frame_not_an_error(tmp_path):
    assert mf.read(str(tmp_path)).empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_manifest.py -v`
Expected: FAIL, no module `RVUtils.MBO.store.manifest`.

- [ ] **Step 3: Write the implementation**

Append-only parquet fragments under `_manifest/`, one file per append (cheap and lock-free across worker processes), read as a dataset and reduced with `groupby(["product","date","kind"]).tail(1)`. `ENGINE_VERSION = "1.0.0"` with a docstring stating the bump rule.

- [ ] **Step 4: Run tests**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_manifest.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-mbos add RVUtils/MBO/store/manifest.py tests/test_mbo_manifest.py
git -C C:/Users/chris/clee/ARBS-mbos commit -m "feat(MBO): append-only build manifest with version-aware resume"
```

---

### Task 7: Store reader and panel builder

**Files:**
- Create: `RVUtils/MBO/store/reader.py`, `RVUtils/MBO/store/panel.py`
- Test: `tests/test_mbo_panel.py`

**Interfaces:**
- Consumes: the three schemas, the catalogue.
- Produces: `read_tob(root, product, dates, symbols=None, raw=False) -> pd.DataFrame` (with `bid_px`/`ask_px` decoded unless `raw`), `read_trades(...)`, `read_catalog(...)`, `panel(root, symbols, dates, freq="1s", fields=(...), session=None, clock="ts_recv") -> pd.DataFrame`, `panel_events(root, symbols, dates, ...) -> pd.DataFrame`.

- [ ] **Step 1: Write the failing test**

```python
"""Panel construction tests.

Both a gridded panel and an event panel are provided, and the tests pin the
property that separates them: the grid forward-fills, and the event frame does
not resample at all.  Imposing a grid on asynchronous data is what biases
high-frequency comovement toward zero, so a lead-lag study must be able to avoid
it.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.store.panel import panel, panel_events


def test_grid_panel_forward_fills_from_each_symbols_own_events(store_2sym):
    p = panel(store_2sym, ["AAA", "BBB"], [DATE], freq="1s", fields=("mid",))
    assert list(p.columns) == [("mid", "AAA"), ("mid", "BBB")]
    assert p[("mid", "AAA")].isna().sum() == 0
    assert p.index.freq is not None


def test_grid_panel_is_nan_before_a_symbols_first_quote(store_late_start):
    p = panel(store_late_start, ["AAA", "BBB"], [DATE], freq="1s", fields=("mid",))
    assert p[("mid", "BBB")].iloc[0] != p[("mid", "BBB")].iloc[0]   # NaN


def test_event_panel_keeps_every_original_timestamp(store_2sym):
    e = panel_events(store_2sym, ["AAA", "BBB"], [DATE])
    assert len(e) == N_EVENTS_AAA + N_EVENTS_BBB
    assert e["symbol"].nunique() == 2
    assert e["ts_recv"].is_monotonic_increasing


def test_event_panel_does_not_invent_observations(store_2sym):
    e = panel_events(store_2sym, ["AAA", "BBB"], [DATE])
    g = panel(store_2sym, ["AAA", "BBB"], [DATE], freq="1s", fields=("mid",))
    assert len(e) <= len(g) * 2 or True     # no assertion on ratio; only that
    assert e.notna().all().all()            # nothing was filled in


def test_requesting_bp_units_without_a_risk_row_raises(store_ust):
    with pytest.raises(ValueError, match="no DV01"):
        panel(store_ust, ["ZNU6"], [DATE], freq="1s", fields=("mid",), units="bp")
```

Provide the `store_2sym`, `store_late_start` and `store_ust` fixtures in the same module, each building a tiny store with `StoreWriter` from hand-made sequences, so the tests need no `D:\`.

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_panel.py -v`
Expected: FAIL, no module `RVUtils.MBO.store.panel`.

- [ ] **Step 3: Write the implementation**

`reader.py` uses `pyarrow.dataset` with a `symbol` filter so row groups are pruned, then joins the catalogue to turn tick indices into prices. `panel.py` builds the wide gridded frame (resample-last then `ffill`, NaN before first quote) and the long event frame (concatenate, sort by `ts_recv`, stable). `units="bp"` looks up `risk/` and raises `ValueError("... no DV01 ...")` on a miss.

- [ ] **Step 4: Run tests**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_panel.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-mbos add RVUtils/MBO/store/reader.py RVUtils/MBO/store/panel.py tests/test_mbo_panel.py
git -C C:/Users/chris/clee/ARBS-mbos commit -m "feat(MBO): store reader plus gridded and event panels"
```

---

### Task 8: Risk partition

**Files:**
- Create: `RVUtils/MBO/store/risk.py`
- Test: `tests/test_mbo_risk.py`

**Interfaces:**
- Consumes: `Query/USTFutures` (`USTFutureValue.DV01`), `MDP/USTFutures/treasury_conversion_factors`.
- Produces: `RISK_SCHEMA`, `build_risk(root, product, date) -> pd.DataFrame`, `read_risk(root, product, dates) -> pd.DataFrame`, `dv01_for(root, symbol, date) -> float` (raises on a miss).

- [ ] **Step 1: Write the failing test**

```python
def test_sr3_dv01_is_synthesised_from_the_intrinsic_bp_value(tmp_path):
    df = build_risk(str(tmp_path), "SR3", DATE)
    assert (df["dv01_per_contract"] == 25.0).all()
    assert (df["source"] == "intrinsic").all()


def test_dv01_for_raises_on_a_missing_row_rather_than_returning_nan(tmp_path):
    build_risk(str(tmp_path), "SR3", DATE)
    with pytest.raises(KeyError, match="no DV01"):
        dv01_for(str(tmp_path), "ZNU6", DATE)


def test_a_failed_curve_build_is_recorded_as_failed_not_as_zero(tmp_path, monkeypatch):
    monkeypatch.setattr("RVUtils.MBO.store.risk._price_dv01",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("curve down")))
    df = build_risk(str(tmp_path), "ZN", DATE)
    assert df["dv01_per_contract"].isna().all()
    assert (df["source"] == "FAILED").all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_risk.py -v`
Expected: FAIL, no module.

- [ ] **Step 3: Write the implementation**

SR3 rows are synthesised at $25/bp. Treasury rows call the existing pricer per `(symbol, date)`; a failure writes `NaN` with `source="FAILED"` rather than a zero, and `dv01_for` raises on both a missing row and a `NaN` one. That is the whole point: this repo has already published an all-NaN risk set as a successful run, and the defence is that the read path refuses NaN, not that the write path is assumed to succeed.

- [ ] **Step 4: Run tests**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_risk.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-mbos add RVUtils/MBO/store/risk.py tests/test_mbo_risk.py
git -C C:/Users/chris/clee/ARBS-mbos commit -m "feat(MBO): risk partition with CTD DV01, failing loud on a missing curve"
```

---

### Task 9: Build CLI

**Files:**
- Create: `RVUtils/MBO/build.py`
- Test: `tests/test_mbo_build.py`

**Interfaces:**
- Consumes: `MboArchive`, `StoreWriter`, `manifest`, `replay_book`, `parse_symbol`.
- Produces: `build_session(root, archive, product, date, tiers) -> dict`, `plan(root, archive, products, dates, tiers, engine_version) -> pd.DataFrame`, `estimate_bytes(plan, bytes_per_record) -> float`, `main(argv) -> int`.

- [ ] **Step 1: Write the failing test**

```python
def test_plan_skips_sessions_already_built_at_this_engine_version(tmp_store, fake_archive):
    ...

def test_estimate_refuses_a_build_that_would_exceed_the_disk_budget(tmp_store, fake_archive):
    with pytest.raises(RuntimeError, match="disk budget"):
        main(["--root", tmp_store, "--products", "ZN", "--disk-budget-gb", "0.000001"])

def test_a_failed_session_records_a_failed_row_and_does_not_stop_the_build(...):
    ...

def test_worker_count_is_derived_from_session_size_not_from_core_count(...):
    assert workers_for(session_gb=4.0, free_ram_gb=64.0) == 9
    assert workers_for(session_gb=0.4, free_ram_gb=64.0) >= 16
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_build.py -v`
Expected: FAIL, no module.

- [ ] **Step 3: Write the implementation**

`ProcessPoolExecutor` over `(product, date)`; each worker opens its session through `MboArchive.open_session`, scans the catalogue, replays each instrument, writes through `StoreWriter`, appends one manifest row. A session that raises records `status="FAILED"` with the message and the build continues — one bad session must not cost the other 552.

Docstring must state: invoke as `C:/Users/chris/anaconda3/envs/stir/python.exe -m RVUtils.MBO.build`, never through `conda run`.

- [ ] **Step 4: Run tests**

Run: `C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_mbo_build.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git -C C:/Users/chris/clee/ARBS-mbos add RVUtils/MBO/build.py tests/test_mbo_build.py
git -C C:/Users/chris/clee/ARBS-mbos commit -m "feat(MBO): resumable multi-session build CLI with a disk budget"
```

---

### Task 10: Pilot build and real-data verification

**Files:**
- Create: `RVUtils/MBO/verify.py`
- Test: `tests/test_mbo_verify.py` (marked `slow`, skipped without `D:\`)

**Interfaces:**
- Consumes: the store, `notebooks/data/stir_intraday/contracts.parquet`.
- Produces: `ohlcv_tieout(root, product, date, reference) -> pd.DataFrame`, `invariants(root, products, dates) -> pd.DataFrame`, `pilot(root, archive, products) -> dict`.

- [ ] **Step 1: Build one session per product**

```bash
C:/Users/chris/anaconda3/envs/stir/python.exe -m RVUtils.MBO.build \
  --products SR3,ZT,ZF,ZN,TN,ZB,UB --dates 2026-07-14:2026-07-14 \
  --tier wide --workers 2 --disk-budget-gb 250
```

- [ ] **Step 2: Record measured bytes per record and extrapolate**

Read the manifest, compute `bytes_written / n_records` per product, multiply by each product's total sessions, and write the projection into the findings document. **The full build does not start until this projection is under the budget.** The 401 GB free against a deep tier covering every active instrument is comfortable but not unlimited, and an estimate made before this step is a guess.

- [ ] **Step 3: OHLCV tie-out**

Rebuild session and four-hour bars from stored trades and compare with the Barchart panel. Test both bar-labelling conventions and report both; the previous work found start-labelling reproduced 100% of closes exactly against 23% for end-labelling, and that alignment is a finding, not a setting.

- [ ] **Step 4: Invariants across the pilot**

Assert per instrument-day, from the manifest: crossed books at packet boundaries are rare and confined to the pre-open, and trades outside the prevailing book stay at the order of a few basis points of trades and appear only on outrights and bundles (the implied-matching signature).

- [ ] **Step 5: Store round-trip on real data**

For three instruments per product, replay in memory and compare every column of the stored top-of-book against it. Exact equality, not tolerance — tick indices are integers.

- [ ] **Step 6: Commit and write findings**

```bash
git -C C:/Users/chris/clee/ARBS-mbos add RVUtils/MBO/verify.py tests/test_mbo_verify.py docs/superpowers/specs/2026-08-08-cme-mbo-suite-findings.md
git -C C:/Users/chris/clee/ARBS-mbos commit -m "feat(MBO): pilot verification -- tie-out, invariants and store round-trip"
```

---

## Self-Review

**Spec coverage.** §1 product model → Task 1. §2 symbology → Task 2. §3 banded ladder → Task 3. §4.1/4.2/4.3 store → Task 5. §4.4 risk → Task 8. §4.5 manifest → Task 6. §4.6 build pipeline → Task 9. §4.7 panels → Task 7. §9 verification → Tasks 3 (mutation), 5–8 (unit), 10 (real data). §5–§8 are Phases 2–5 and are out of scope for this plan by design; each gets its own plan written against the store as built.

**Gap found and closed.** The spec's §4.6 memory constraint had no task. It is now `workers_for` in Task 9, with a test that pins it to session size rather than core count — the host has 32 cores and can only afford nine concurrent SR3 sessions.

**Type consistency.** `PriceGrid` gains `px_max` in Task 3 and Task 5's writer uses it; `ParsedSymbol` gains `root` in Task 2 and Task 5's catalogue writes it; `ENGINE_VERSION` is defined in Task 6 and consumed in Task 9. `store_path(root, kind, product, date)` has one signature, used identically in Tasks 5, 7, 8 and 9.
