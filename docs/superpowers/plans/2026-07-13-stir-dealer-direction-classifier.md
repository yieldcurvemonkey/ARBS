# STIR Dealer Direction Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify dealer direction (paid/received) on sub-3Y USD swap SDR prints by repricing each trade against BARCHART_STIRF-RL curve mids at t−1min, with a Clarus/BoE tick-size + dispersion layer driving a hump-shaped confidence model. POC: classify 2026-07-10, calibrate ticks over 2026-06-10..2026-07-10.

**Spec:** `docs/superpowers/specs/2026-07-12-stir-dealer-direction-classifier-design.md` (approved). The spec is the authority on rules; this plan implements it.

**Architecture:** New `SDRUtils/stir_flow/` package of pure, individually testable modules (selection → pricing → classification → confidence → tick stats), a schema module following the `_tape_schema_v2.py` pattern, and one CLI backfill orchestrator. Reads the existing tape tables; writes ONLY to two new `arbs_stir_*_v1` tables.

**Tech Stack:** Python (conda env `stir`), pandas, psycopg2, existing `IRSwapsMDP`/`IRSwapQuery` pricer stack, pytest.

## Global Constraints

- All Python/pytest runs via `conda run -n stir ...` (never bare python).
- Fast test gate: `conda run -n stir python -m pytest tests -m "not slow and not network and not db"` — every task's fast tests must pass under this command.
- Pricer-touching tests marked `@pytest.mark.network` + `@pytest.mark.slow`; prod-DB tests marked `@pytest.mark.db`.
- DB `fixed_rate` is ALREADY decimal (0.03713 = 3.713%) — pass to pricer as-is, never divide by 100. `IRSwapValue.RATE` returns percent (3.713).
- Curves: SOFR → `USD-SOFR-1D-Q12xM12STIRT`; FED_FUNDS → `USD-OIS-Q12xM12STIRT-SERFFX-MIX23`; source `BARCHART_STIRF-RL`.
- Curve snapshot: `floor(original_execution_timestamp → America/New_York, 1min) − 1min` (fallback `execution_timestamp` when original is NULL).
- The tape DB is REMOTE SUPABASE PROD. Never write to `arbs_usd_swap_tape_*` tables. New tables only: `arbs_stir_direction_v1`, `arbs_stir_tick_size_v1`.
- Off-market NPV sums ALL legs of a package (fetched by `package_id` with no eligibility filters).
- Work on branch `feat/stir-dealer-direction` (create worktree via superpowers:using-git-worktrees at execution start; use a short sibling path per repo memory, e.g. `../ARBS-stir`).
- Don't parse raw SDR numerics here — we read the already-typed v2 tape columns only.

## File Structure

```
SDRUtils/stir_flow/__init__.py            (empty)
SDRUtils/stir_flow/config.py              constants: curve map, futures ticks, DV01 buckets, thresholds
SDRUtils/stir_flow/trade_selection.py     SQL + eligibility predicates + ClassificationUnit builder
SDRUtils/stir_flow/pricing.py             snapshot rule, curve-handle cache, price_leg wrapper
SDRUtils/stir_flow/classifier.py          pure direction rules (on/off-market, all structures)
SDRUtils/stir_flow/confidence.py          hump model, P_flip, tick-rule fallback
SDRUtils/stir_flow/tick_size.py           tick pairs, bucket stats, DispVW/DispJNS/Amihud
SDRUtils/_swappulse_scripts/_stir_flow_schema_v1.py   DDL + ensure_schema
SDRUtils/_swappulse_scripts/backfill_stir_direction.py CLI orchestrator
tests/test_stir_flow_config.py
tests/test_stir_flow_selection.py
tests/test_stir_flow_pricing.py
tests/test_stir_flow_classifier.py
tests/test_stir_flow_confidence.py
tests/test_stir_flow_tick_size.py
tests/test_stir_flow_backfill.py
```

---

### Task 1: Config module

**Files:**
- Create: `SDRUtils/stir_flow/__init__.py` (empty file)
- Create: `SDRUtils/stir_flow/config.py`
- Test: `tests/test_stir_flow_config.py`

**Interfaces:**
- Produces: `CURVE_FOR: dict[str, str]`, `assign_dv01_bucket(dv01: float) -> str`, `futures_tick_bps(rate_index: str, special_tenor_type: str | None) -> float`, plus all threshold constants listed below. Every later task imports from here.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stir_flow_config.py
from SDRUtils.stir_flow import config


def test_curve_mapping():
    assert config.CURVE_FOR["SOFR"] == "USD-SOFR-1D-Q12xM12STIRT"
    assert config.CURVE_FOR["FED_FUNDS"] == "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"


def test_dv01_bucket_edges():
    assert config.assign_dv01_bucket(0) == "MICRO"
    assert config.assign_dv01_bucket(4_999) == "MICRO"
    assert config.assign_dv01_bucket(5_000) == "SMALL"
    assert config.assign_dv01_bucket(14_999) == "SMALL"
    assert config.assign_dv01_bucket(15_000) == "MID"
    assert config.assign_dv01_bucket(49_999) == "MID"
    assert config.assign_dv01_bucket(50_000) == "LARGE"
    assert config.assign_dv01_bucket(149_999) == "LARGE"
    assert config.assign_dv01_bucket(150_000) == "BLOCK"
    assert config.assign_dv01_bucket(None) == "UNKNOWN"


def test_futures_tick():
    assert config.futures_tick_bps("FED_FUNDS", "FOMC") == 0.50
    assert config.futures_tick_bps("FED_FUNDS", "STANDARD") == 0.50
    assert config.futures_tick_bps("SOFR", "FOMC") == 0.50   # 1M SOFR futures hedge
    assert config.futures_tick_bps("SOFR", "IMM") == 0.25    # SR3 hedge
    assert config.futures_tick_bps("SOFR", "STANDARD") == 0.25
    assert config.futures_tick_bps("SOFR", None) == 0.25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'SDRUtils.stir_flow'`

- [ ] **Step 3: Write minimal implementation**

```python
# SDRUtils/stir_flow/config.py
"""Constants for the STIR dealer-direction classifier (spec 2026-07-12)."""

CURVE_SOURCE = "BARCHART_STIRF-RL"
CURVE_FOR = {
    "SOFR": "USD-SOFR-1D-Q12xM12STIRT",
    "FED_FUNDS": "USD-OIS-Q12xM12STIRT-SERFFX-MIX23",
}

# CME rulebook minimum ticks (bps). FF futures Ch.22 / 1M SOFR Ch.461 = 0.5bp,
# SR3 Ch.460 = 0.25bp. Near-expiry halving deferred (POC).
_FF_TICK = 0.50
_SER_TICK = 0.50
_SR3_TICK = 0.25

# DV01 buckets per Clarus tick-vs-size methodology.
DV01_BUCKETS = (
    ("MICRO", 0.0, 5_000.0),
    ("SMALL", 5_000.0, 15_000.0),
    ("MID", 15_000.0, 50_000.0),
    ("LARGE", 50_000.0, 150_000.0),
    ("BLOCK", 150_000.0, float("inf")),
)

PTP_USD_FLOOR = 500.0          # |PTP| below this = notation-polluted price, not USD
PTP_UFRO_DISAGREE_RATIO = 2.0  # flag when both present and >2x apart
TICK_PAIR_MAX_GAP_MIN = 60     # consecutive-print pairs beyond this measure drift
MIN_DISP_VW_BPS = 0.05         # ratio-denominator floor for the curve_suspect gate
CURVE_SUSPECT_RATIO = 2.0      # DispJNS/DispVW above this -> bucket-day curve_suspect
HUMP_OUTLIER_MULT = 3.0        # |s2m| > 3*S -> curve_suspect_trade, LOW
AMBIGUOUS_FRAC = 0.5           # |s2m| < 0.5*(S/2) -> tick-rule fallback
P_FLIP_HIGH = 0.05
P_FLIP_MEDIUM = 0.20
SUB3Y_HORIZON_DAYS = 1105      # ~3.02y: maturity cutoff from as_of_date

EXCLUDED_LABEL_TOKENS = ("CME Term", "Amortizing")
EXCLUDED_TRADE_TYPES = (
    "MAC", "SPREADOVER", "SPREADOVER_CURVE", "SPREADOVER_FLY",
    "MATCHED_MATURITY", "MATCHED_MATURITY_CURVE", "MATCHED_MATURITY_FLY",
    "INVOICE", "INVOICE_SWAP", "INVOICE_CALENDAR", "INVOICE_SWITCH",
)


def assign_dv01_bucket(dv01) -> str:
    if dv01 is None:
        return "UNKNOWN"
    try:
        v = abs(float(dv01))
    except (TypeError, ValueError):
        return "UNKNOWN"
    if v != v:  # NaN
        return "UNKNOWN"
    for name, lo, hi in DV01_BUCKETS:
        if lo <= v < hi:
            return name
    return "UNKNOWN"


def futures_tick_bps(rate_index: str, special_tenor_type) -> float:
    if rate_index == "FED_FUNDS":
        return _FF_TICK
    if special_tenor_type == "FOMC":
        return _SER_TICK
    return _SR3_TICK
```

Also create empty `SDRUtils/stir_flow/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_config.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/stir_flow/__init__.py SDRUtils/stir_flow/config.py tests/test_stir_flow_config.py
git commit -m "feat(stir-flow): config constants, DV01 buckets, futures tick lookup"
```

---

### Task 2: Schema module

**Files:**
- Create: `SDRUtils/_swappulse_scripts/_stir_flow_schema_v1.py`
- Test: `tests/test_stir_flow_backfill.py` (schema section)

**Interfaces:**
- Produces: `DIRECTION_TABLE = "arbs_stir_direction_v1"`, `TICK_TABLE = "arbs_stir_tick_size_v1"`, `DDL_STATEMENTS: list[str]`, `ensure_schema(conn) -> None` (executes every DDL statement; all statements idempotent `IF NOT EXISTS`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stir_flow_backfill.py
from SDRUtils._swappulse_scripts import _stir_flow_schema_v1 as schema


def test_schema_ddl_columns():
    ddl = "\n".join(schema.DDL_STATEMENTS)
    assert "CREATE TABLE IF NOT EXISTS arbs_stir_direction_v1" in ddl
    assert "CREATE TABLE IF NOT EXISTS arbs_stir_tick_size_v1" in ddl
    for col in (
        "unit_key", "trade_id", "package_id", "classification_method",
        "dealer_direction", "direction_confidence", "dealer_bought",
        "dealer_charge_bps", "curve_suspect_trade", "quality_flags",
        "repriced_npv", "reported_ptp", "reported_opa", "p_flip",
        "spread_to_mid_bps", "structure_dv01", "tenor_query",
    ):
        assert col in ddl, col
    for col in (
        "tenor_bucket", "structure_type", "dv01_bucket", "median_tick_bps",
        "disp_vw", "disp_jns", "curve_suspect", "amihud",
        "median_dealer_charge_bps", "futures_min_tick_bps",
    ):
        assert col in ddl, col


def test_ensure_schema_executes_all(monkeypatch):
    executed = []

    class FakeCursor:
        def execute(self, sql):
            executed.append(sql)
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class FakeConn:
        def cursor(self):
            return FakeCursor()
        def commit(self):
            executed.append("COMMIT")

    schema.ensure_schema(FakeConn())
    assert executed[-1] == "COMMIT"
    assert len(executed) == len(schema.DDL_STATEMENTS) + 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_backfill.py -v`
Expected: FAIL with `ImportError` / module not found

- [ ] **Step 3: Write minimal implementation**

```python
# SDRUtils/_swappulse_scripts/_stir_flow_schema_v1.py
"""DDL for the STIR dealer-direction POC tables (spec 2026-07-12 section 7)."""

DIRECTION_TABLE = "arbs_stir_direction_v1"
TICK_TABLE = "arbs_stir_tick_size_v1"

DDL_STATEMENTS = [
    f"""
CREATE TABLE IF NOT EXISTS {DIRECTION_TABLE} (
    id                    BIGSERIAL PRIMARY KEY,
    unit_key              TEXT NOT NULL UNIQUE,
    trade_id              TEXT,
    package_id            TEXT,
    as_of_date            DATE NOT NULL,
    execution_timestamp   TIMESTAMPTZ NOT NULL,
    trade_type            TEXT,
    rate_index_clean      TEXT,
    curve_name            TEXT,
    curve_timestamp       TIMESTAMPTZ,
    is_off_market         BOOLEAN,
    classification_method TEXT,
    curve_mid             NUMERIC,
    curve_mid_spread_bps  NUMERIC,
    fixed_rate            NUMERIC,
    traded_spread_bps     NUMERIC,
    spread_to_mid_bps     NUMERIC,
    repriced_npv          NUMERIC,
    repriced_pv01         NUMERIC,
    reported_opa          NUMERIC,
    reported_ptp          NUMERIC,
    dealer_direction      TEXT NOT NULL DEFAULT 'UNKNOWN',
    dealer_bought         BOOLEAN,
    direction_confidence  TEXT,
    p_flip                NUMERIC,
    dealer_charge         NUMERIC,
    dealer_charge_bps     NUMERIC,
    structure_dv01        NUMERIC,
    notional              NUMERIC,
    dv01                  NUMERIC,
    tenor_query           TEXT,
    tenor_bucket          TEXT,
    dv01_bucket           TEXT,
    curve_suspect_trade   BOOLEAN DEFAULT FALSE,
    quality_flags         TEXT[],
    classified_at         TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    f"CREATE INDEX IF NOT EXISTS idx_stir_dir_asof ON {DIRECTION_TABLE} (as_of_date)",
    f"CREATE INDEX IF NOT EXISTS idx_stir_dir_trade ON {DIRECTION_TABLE} (trade_id)",
    f"CREATE INDEX IF NOT EXISTS idx_stir_dir_pkg ON {DIRECTION_TABLE} (package_id)",
    f"CREATE INDEX IF NOT EXISTS idx_stir_dir_dir ON {DIRECTION_TABLE} (dealer_direction, as_of_date)",
    f"""
CREATE TABLE IF NOT EXISTS {TICK_TABLE} (
    tenor_bucket            TEXT NOT NULL,
    structure_type          TEXT NOT NULL,
    dv01_bucket             TEXT NOT NULL,
    as_of_date              DATE NOT NULL,
    futures_min_tick_bps    NUMERIC,
    mean_tick_bps           NUMERIC,
    median_tick_bps         NUMERIC,
    p25_tick_bps            NUMERIC,
    p75_tick_bps            NUMERIC,
    tick_sample_count       INTEGER,
    mean_dealer_charge_bps  NUMERIC,
    median_dealer_charge_bps NUMERIC,
    edge_sample_count       INTEGER,
    disp_vw                 NUMERIC,
    disp_jns                NUMERIC,
    curve_suspect           BOOLEAN,
    amihud                  NUMERIC,
    total_dv01_traded       NUMERIC,
    trade_count             INTEGER,
    window_days             INTEGER,
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenor_bucket, structure_type, dv01_bucket, as_of_date)
)""",
    f"CREATE INDEX IF NOT EXISTS idx_stir_tick_asof ON {TICK_TABLE} (as_of_date)",
]


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        for stmt in DDL_STATEMENTS:
            cur.execute(stmt)
    conn.commit()
```

Note: FakeCursor in the test is not a context manager returning itself unless implemented — the implementation uses `with conn.cursor() as cur`, matching the fake.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_backfill.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/_swappulse_scripts/_stir_flow_schema_v1.py tests/test_stir_flow_backfill.py
git commit -m "feat(stir-flow): schema DDL for direction + tick tables"
```

---

### Task 3: Trade selection

**Files:**
- Create: `SDRUtils/stir_flow/trade_selection.py`
- Test: `tests/test_stir_flow_selection.py`

**Interfaces:**
- Consumes: `config` constants.
- Produces:
  - `ELIGIBLE_LEGS_SQL: str` — parameterized on `%(start)s`/`%(end)s` (as_of_date range), returns the leg+package columns listed in the implementation.
  - `ALL_PKG_LEGS_SQL: str` — parameterized on `%(package_ids)s` (list), no eligibility filters.
  - `is_excluded_unit(legs: pd.DataFrame) -> str | None` — returns exclusion reason or None.
  - `build_units(eligible: pd.DataFrame, all_legs: pd.DataFrame) -> list[Unit]` where `Unit` is a dataclass: `unit_key: str`, `kind: str` ('OUTRIGHT'|'CURVE'|'FLY'|'PKG'), `legs: pd.DataFrame` (all legs, sorted by expiration_date), `package_id: str | None`, `is_off_market: bool`.
  - `resolve_upfront(pkg_ptp, leg_ufros: list[float]) -> tuple[float | None, str | None, bool]` — `(abs_upfront_usd, source 'PTP'|'UFRO_SUM'|None, disagree_flag)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stir_flow_selection.py
import datetime
import pandas as pd
import pytest
from SDRUtils.stir_flow import trade_selection as sel


def _leg(**kw):
    base = dict(
        trade_id="T1", package_id="OUTRIGHT-T1", as_of_date=datetime.date(2026, 7, 10),
        execution_timestamp=pd.Timestamp("2026-07-10 16:00:00+00:00"),
        original_execution_timestamp=pd.Timestamp("2026-07-10 16:00:00+00:00"),
        trade_type="OUTRIGHT", rate_index_clean="FED_FUNDS", venue="D2C",
        special_tenor_type="FOMC", fomc_meeting_label="JUL26",
        tenor_label="2M", forward_label=None, forward_start_years=0.0,
        effective_date=datetime.date(2026, 7, 29), expiration_date=datetime.date(2026, 9, 16),
        notional=1e9, risk=13_500.0, fixed_rate=0.03713,
        other_payment_ufro=0.0, pkg_ptp=None, pkg_pts=None,
        is_capped=False, is_block=False, is_off_date=False,
        leg_tape_label="USD-Federal Funds-OIS Compound 1D Constant FOMC JUL26 Outright PHYS",
        n_package_legs=1, package_structure="2M Outright",
    )
    base.update(kw)
    return base


def test_exclusion_reasons():
    ok = pd.DataFrame([_leg()])
    assert sel.is_excluded_unit(ok) is None

    cme_term = pd.DataFrame([_leg(leg_tape_label="USD-SOFR CME Term 1D Amortizing Spot 3Y Outright CASH")])
    assert sel.is_excluded_unit(cme_term) == "EXCLUDED_UNDERLIER"

    mms = pd.DataFrame([_leg(trade_type="MATCHED_MATURITY")])
    assert sel.is_excluded_unit(mms) == "EXCLUDED_TRADE_TYPE"

    too_long = pd.DataFrame([
        _leg(),
        _leg(trade_id="T2", expiration_date=datetime.date(2056, 9, 16)),
    ])
    assert sel.is_excluded_unit(too_long) == "LEG_BEYOND_3Y"

    no_rate = pd.DataFrame([_leg(fixed_rate=None)])
    assert sel.is_excluded_unit(no_rate) == "MISSING_FIXED_RATE"


def test_resolve_upfront():
    # plausible USD PTP wins
    assert sel.resolve_upfront(-48419.0, [22998.0, 25503.0]) == (48419.0, "PTP", False)
    # notation-polluted PTP falls back to UFRO sum
    up, src, flag = sel.resolve_upfront(9.99, [13427.27])
    assert (round(up, 2), src, flag) == (13427.27, "UFRO_SUM", False)
    # disagreement >2x flags
    up, src, flag = sel.resolve_upfront(-5392.0, [20430.0, 13219.0, 13257.0])
    assert src == "PTP" and flag is True
    # nothing present
    assert sel.resolve_upfront(None, [0.0]) == (None, None, False)


def test_build_units_groups_outright_and_package():
    eligible = pd.DataFrame([
        _leg(),
        _leg(trade_id="C1", package_id="PTP_C1", n_package_legs=2,
             package_structure="1M/1M Curve", trade_type="FOMC",
             pkg_ptp=-48419.0, other_payment_ufro=22998.0),
    ])
    all_legs = pd.DataFrame([
        _leg(),
        _leg(trade_id="C1", package_id="PTP_C1", n_package_legs=2,
             package_structure="1M/1M Curve", pkg_ptp=-48419.0,
             other_payment_ufro=22998.0),
        _leg(trade_id="C2", package_id="PTP_C1", n_package_legs=2,
             package_structure="1M/1M Curve", pkg_ptp=-48419.0,
             other_payment_ufro=25503.0, venue="D2D",   # ineligible leg still included
             effective_date=datetime.date(2026, 9, 16),
             expiration_date=datetime.date(2026, 10, 28)),
    ])
    units = sel.build_units(eligible, all_legs)
    keys = {u.unit_key: u for u in units}
    assert keys["T1"].kind == "OUTRIGHT" and len(keys["T1"].legs) == 1
    pkg = keys["PTP_C1"]
    assert pkg.kind == "CURVE" and len(pkg.legs) == 2 and pkg.is_off_market
    # legs sorted by expiration
    assert list(pkg.legs["trade_id"]) == ["C1", "C2"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_selection.py -v`
Expected: FAIL with module not found

- [ ] **Step 3: Write the implementation**

```python
# SDRUtils/stir_flow/trade_selection.py
"""Trade eligibility + classification-unit construction (spec section 2)."""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd

from SDRUtils.stir_flow import config

_LEG_COLS = """
    l.trade_id, l.package_id, l.as_of_date,
    l.execution_timestamp, l.original_execution_timestamp,
    l.trade_type, l.rate_index_clean, l.venue,
    l.special_tenor_type, l.fomc_meeting_label,
    l.tenor_label, l.forward_label, l.forward_start_years,
    l.effective_date, l.expiration_date,
    l.notional, l.risk, l.fixed_rate,
    l.other_payment_ufro, l.is_capped, l.is_block, l.is_off_date,
    l.leg_tape_label, l.execution_session,
    p.package_structure, p.n_package_legs,
    p.package_transaction_price AS pkg_ptp,
    p.package_transaction_spread AS pkg_pts
"""

ELIGIBLE_LEGS_SQL = f"""
SELECT {_LEG_COLS}
FROM arbs_usd_swap_tape_legs_v2 l
LEFT JOIN arbs_usd_swap_tape_packages_v2 p USING (package_id)
WHERE l.as_of_date BETWEEN %(start)s AND %(end)s
  AND l.economic_class = 'ECONOMIC_FLOW'
  AND l.contributes_to_flow = true
  AND l.venue = 'D2C'
  AND l.rate_index_clean IN ('SOFR', 'FED_FUNDS')
  AND l.fixed_rate IS NOT NULL
ORDER BY l.execution_timestamp
"""

ALL_PKG_LEGS_SQL = f"""
SELECT {_LEG_COLS}
FROM arbs_usd_swap_tape_legs_v2 l
LEFT JOIN arbs_usd_swap_tape_packages_v2 p USING (package_id)
WHERE l.package_id = ANY(%(package_ids)s)
ORDER BY l.package_id, l.expiration_date
"""


@dataclasses.dataclass
class Unit:
    unit_key: str
    kind: str                    # OUTRIGHT | CURVE | FLY | PKG
    legs: pd.DataFrame           # all legs, sorted by expiration_date
    package_id: str | None
    is_off_market: bool


def _horizon(as_of: datetime.date) -> datetime.date:
    return as_of + datetime.timedelta(days=config.SUB3Y_HORIZON_DAYS)


def is_excluded_unit(legs: pd.DataFrame) -> str | None:
    labels = legs["leg_tape_label"].fillna("")
    if labels.str.contains("|".join(config.EXCLUDED_LABEL_TOKENS)).any():
        return "EXCLUDED_UNDERLIER"
    if legs["trade_type"].isin(config.EXCLUDED_TRADE_TYPES).any():
        return "EXCLUDED_TRADE_TYPE"
    if legs["fixed_rate"].isna().any():
        return "MISSING_FIXED_RATE"
    as_of = pd.Timestamp(legs.iloc[0]["as_of_date"]).date()
    mats = pd.to_datetime(legs["expiration_date"]).dt.date
    if (mats > _horizon(as_of)).any():
        return "LEG_BEYOND_3Y"
    return None


def resolve_upfront(pkg_ptp, leg_ufros) -> tuple:
    ufro_sum = float(sum(u for u in leg_ufros if u)) if leg_ufros is not None else 0.0
    ptp_usd = None
    if pkg_ptp is not None and pkg_ptp == pkg_ptp and abs(float(pkg_ptp)) > config.PTP_USD_FLOOR:
        ptp_usd = abs(float(pkg_ptp))
    disagree = False
    if ptp_usd is not None and ufro_sum > 0:
        hi, lo = max(ptp_usd, ufro_sum), min(ptp_usd, ufro_sum)
        disagree = lo > 0 and (hi / lo) > config.PTP_UFRO_DISAGREE_RATIO
    if ptp_usd is not None:
        return ptp_usd, "PTP", disagree
    if ufro_sum > 0:
        return ufro_sum, "UFRO_SUM", False
    return None, None, False


def _kind(n_legs: int) -> str:
    return {1: "OUTRIGHT", 2: "CURVE", 3: "FLY"}.get(n_legs, "PKG")


def build_units(eligible: pd.DataFrame, all_legs: pd.DataFrame) -> list:
    units: list[Unit] = []
    seen: set[str] = set()
    for _, row in eligible.iterrows():
        pkg_id = row["package_id"]
        n = int(row["n_package_legs"] or 1)
        if n <= 1:
            key = row["trade_id"]
            if key in seen:
                continue
            seen.add(key)
            legs = eligible[eligible["trade_id"] == key].head(1).copy()
            upfront, _, _ = resolve_upfront(row.get("pkg_ptp"), [row.get("other_payment_ufro") or 0.0])
            units.append(Unit(key, "OUTRIGHT", legs, None, upfront is not None))
        else:
            if pkg_id in seen:
                continue
            seen.add(pkg_id)
            legs = all_legs[all_legs["package_id"] == pkg_id].copy()
            legs = legs.sort_values("expiration_date").reset_index(drop=True)
            upfront, _, _ = resolve_upfront(
                legs.iloc[0].get("pkg_ptp"),
                list(legs["other_payment_ufro"].fillna(0.0)),
            )
            units.append(Unit(pkg_id, _kind(len(legs)), legs, pkg_id, upfront is not None))
    return units
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_selection.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/stir_flow/trade_selection.py tests/test_stir_flow_selection.py
git commit -m "feat(stir-flow): eligibility predicates, upfront resolution, unit builder"
```

---

### Task 4: Pricing wrapper

**Files:**
- Create: `SDRUtils/stir_flow/pricing.py`
- Test: `tests/test_stir_flow_pricing.py`

**Interfaces:**
- Consumes: `config.CURVE_SOURCE`, `config.CURVE_FOR`.
- Produces:
  - `snap_timestamp(orig_ts, exec_ts) -> datetime` — tz-aware America/New_York, floored to minute, minus 1 minute; uses `orig_ts` unless NaT/None.
  - `LegPricing` dataclass: `mid_pct: float`, `npv_pay: float | None`, `pv01: float`.
  - `CurvePricer` class: `__init__(self, mdp=None)` (default constructs `IRSwapsMDP(source=config.CURVE_SOURCE)`), `handle(self, curve_name, ts)` (memoized `_get_curve`), `price_leg(self, curve_name, ts, effective_date, maturity_date, notional, fixed_rate=None) -> LegPricing` (fixed_rate decimal or None → mid only; when fixed_rate given, `npv_pay` is the pay-fixed NPV).

- [ ] **Step 1: Write the failing fast tests**

```python
# tests/test_stir_flow_pricing.py
import datetime
import pandas as pd
import pytest
import pytz
from SDRUtils.stir_flow import pricing

NY = pytz.timezone("America/New_York")


def test_snap_timestamp_floor_minus_one():
    orig = pd.Timestamp("2026-07-10 16:57:28+00:00")   # 12:57:28 ET
    snap = pricing.snap_timestamp(orig, None)
    assert snap == NY.localize(datetime.datetime(2026, 7, 10, 12, 56))


def test_snap_timestamp_fallback_to_exec():
    exec_ts = pd.Timestamp("2026-07-10 19:41:45+00:00")  # 15:41:45 ET
    snap = pricing.snap_timestamp(pd.NaT, exec_ts)
    assert snap == NY.localize(datetime.datetime(2026, 7, 10, 15, 40))


def test_curve_pricer_memoizes_handles():
    calls = []

    class FakeMDP:
        def _get_curve(self, curve_name, timestamp):
            calls.append((curve_name, timestamp))
            return object()

    p = pricing.CurvePricer(mdp=FakeMDP())
    ts = NY.localize(datetime.datetime(2026, 7, 10, 12, 56))
    h1 = p.handle("USD-OIS-Q12xM12STIRT-SERFFX-MIX23", ts)
    h2 = p.handle("USD-OIS-Q12xM12STIRT-SERFFX-MIX23", ts)
    assert h1 is h2 and len(calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_pricing.py -v`
Expected: FAIL with module not found

- [ ] **Step 3: Write the implementation**

```python
# SDRUtils/stir_flow/pricing.py
"""Curve snapshot rule + IRSwapQuery pricing wrapper (spec sections 3-4)."""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd
import pytz

from SDRUtils.stir_flow import config

NY = pytz.timezone("America/New_York")


def snap_timestamp(orig_ts, exec_ts):
    ts = orig_ts
    if ts is None or (isinstance(ts, float) and ts != ts) or pd.isna(ts):
        ts = exec_ts
    et = pd.Timestamp(ts).tz_convert(NY)
    et = et.replace(second=0, microsecond=0) - pd.Timedelta(minutes=1)
    return NY.localize(datetime.datetime(et.year, et.month, et.day, et.hour, et.minute))


@dataclasses.dataclass
class LegPricing:
    mid_pct: float
    npv_pay: float | None
    pv01: float


class CurvePricer:
    def __init__(self, mdp=None):
        if mdp is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            mdp = IRSwapsMDP(source=config.CURVE_SOURCE)
        self._mdp = mdp
        self._handles: dict = {}

    def handle(self, curve_name: str, ts):
        key = (curve_name, ts)
        if key not in self._handles:
            self._handles[key] = self._mdp._get_curve(curve_name=curve_name, timestamp=ts)
        return self._handles[key]

    def price_leg(self, curve_name, ts, effective_date, maturity_date,
                  notional, fixed_rate=None) -> LegPricing:
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapValue import IRSwapValue

        h = self.handle(curve_name, ts)
        skw = {"notional": float(notional)}
        if fixed_rate is not None:
            skw["fixed_rate"] = float(fixed_rate)   # decimal in, decimal through
        q = IRSwapQuery(
            curve=curve_name,
            effective_date=pd.Timestamp(effective_date).date(),
            maturity_date=pd.Timestamp(maturity_date).date(),
            structure_kwargs=skw,
        ).resolve_query(ts, pricer_or_curve=h)
        pkg, rws = q.resolve_package(pricer_or_curve=h)
        vmap = q.build_value_map(pricer_or_curve=h, package=pkg, risk_weights=rws)
        mid = float(vmap.apply(value=IRSwapValue.RATE))
        npv = float(vmap.apply(value=IRSwapValue.NPV)) if fixed_rate is not None else None
        pv01 = float(vmap.apply(value=IRSwapValue.PV01))
        return LegPricing(mid_pct=mid, npv_pay=npv, pv01=pv01)
```

- [ ] **Step 4: Run fast tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_pricing.py -v`
Expected: 3 PASS

- [ ] **Step 5: Add the golden integration test (network+slow)**

Append to `tests/test_stir_flow_pricing.py`:

```python
@pytest.mark.network
@pytest.mark.slow
def test_price_leg_golden_ff_jul26():
    """User-verified print 4137861837000000101 (POC report 2026-07-12)."""
    import datetime
    p = pricing.CurvePricer()
    ts = NY.localize(datetime.datetime(2026, 7, 10, 15, 40))
    lp = p.price_leg(
        "USD-OIS-Q12xM12STIRT-SERFFX-MIX23", ts,
        datetime.date(2026, 7, 29), datetime.date(2026, 9, 16),
        notional=3_700_000_000, fixed_rate=0.03713,
    )
    assert abs(lp.mid_pct - 3.717511) < 5e-4
    assert abs(lp.npv_pay - 22_555) < 200
    assert abs(lp.pv01 - 50_001) < 25
```

Run: `conda run -n stir python -m pytest tests/test_stir_flow_pricing.py -m "network" -v`
Expected: 1 PASS (needs network + warm curve cache; if calibration data unavailable, investigate before proceeding)

- [ ] **Step 6: Run the fast gate**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_pricing.py -m "not slow and not network and not db" -v`
Expected: 3 PASS, golden test deselected

- [ ] **Step 7: Commit**

```bash
git add SDRUtils/stir_flow/pricing.py tests/test_stir_flow_pricing.py
git commit -m "feat(stir-flow): snapshot rule + CurvePricer wrapper with golden test"
```

---

### Task 5: Direction classifier

**Files:**
- Create: `SDRUtils/stir_flow/classifier.py`
- Test: `tests/test_stir_flow_classifier.py`

**Interfaces:**
- Consumes: `trade_selection.Unit`, `trade_selection.resolve_upfront`, `pricing.LegPricing`.
- Produces:
  - `DirectionResult` dataclass with fields matching `arbs_stir_direction_v1` columns: `unit_key, trade_id, package_id, classification_method, dealer_direction ('PAID'|'RECEIVED'|'UNKNOWN'), dealer_bought (bool|None), is_off_market, curve_mid, curve_mid_spread_bps, traded_spread_bps, spread_to_mid_bps, repriced_npv, repriced_pv01, reported_opa, reported_ptp, dealer_charge, dealer_charge_bps, structure_dv01, quality_flags (list[str])`.
  - `classify_unit(unit, pricings: list[LegPricing]) -> DirectionResult` — pure; no confidence fields (Task 6 fills those).
  - `structure_dv01(kind: str, pv01s: list[float]) -> float` — OUTRIGHT=leg, CURVE=max|leg|, FLY=|belly| (middle by maturity order), PKG=gross/2.

- [ ] **Step 1: Write the failing tests — golden numbers from the validated 07/10 POC run**

```python
# tests/test_stir_flow_classifier.py
import datetime
import pandas as pd
import pytest
from SDRUtils.stir_flow.classifier import classify_unit, structure_dv01
from SDRUtils.stir_flow.pricing import LegPricing
from SDRUtils.stir_flow.trade_selection import Unit


def _legs(rows):
    return pd.DataFrame(rows)


def _leg_row(trade_id, rate, ufro=0.0, ptp=None, notional=1e9,
             eff="2026-07-29", mat="2026-09-16"):
    return dict(
        trade_id=trade_id, package_id="P", fixed_rate=rate,
        other_payment_ufro=ufro, pkg_ptp=ptp, notional=notional,
        effective_date=datetime.date.fromisoformat(eff),
        expiration_date=datetime.date.fromisoformat(mat),
        is_block=False,
    )


def test_structure_dv01_conventions():
    assert structure_dv01("OUTRIGHT", [50_000.0]) == 50_000.0
    assert structure_dv01("CURVE", [100_003.0, 100_328.0]) == 100_328.0
    assert structure_dv01("FLY", [8_578.0, 16_986.0, 8_471.0]) == 16_986.0
    assert structure_dv01("PKG", [10_000.0, 10_000.0, 20_000.0]) == 20_000.0


def test_on_market_outright_received():
    # FF FOMC SEP26 print 4135037480000000101: traded 3.8320 vs mid 3.812597
    u = Unit("T", "OUTRIGHT", _legs([_leg_row("T", 0.03832)]), None, False)
    r = classify_unit(u, [LegPricing(3.812597, None, 149_917.0)])
    assert r.classification_method == "RATE_VS_MID"
    assert r.dealer_direction == "RECEIVED"
    assert abs(r.spread_to_mid_bps - 1.9403) < 0.01


def test_off_market_outright_bought_paid():
    # user-verified 4137861837000000101: NPV_pay 22,555 vs UFRO 13,427.27
    u = Unit("T", "OUTRIGHT", _legs([_leg_row("T", 0.03713, ufro=13427.26854, notional=3.7e9)]), None, True)
    r = classify_unit(u, [LegPricing(3.717511, 22554.95, 50000.99)])
    assert r.classification_method == "NPV_VS_UPFRONT"
    assert r.dealer_bought is True and r.dealer_direction == "PAID"
    assert abs(r.dealer_charge - 9127.68) < 1.0
    assert abs(r.dealer_charge_bps - 0.1826) < 0.005


def test_on_market_curve_paid_spread():
    # FF SEP26/OCT26 curve: traded 5.550bp vs mid 8.251bp
    legs = _legs([
        _leg_row("A", 0.038151, eff="2026-09-16", mat="2026-10-28"),
        _leg_row("B", 0.038706, eff="2026-10-28", mat="2026-12-09"),
    ])
    u = Unit("P", "CURVE", legs, "P", False)
    r = classify_unit(u, [
        LegPricing(3.800453, None, 74_960.34),
        LegPricing(3.882959, None, 74_622.04),
    ])
    assert r.classification_method == "SPREAD_VS_MID"
    assert r.dealer_direction == "PAID"
    assert abs(r.traded_spread_bps - 5.550) < 0.01
    assert abs(r.curve_mid_spread_bps - 8.2506) < 0.01
    assert abs(r.spread_to_mid_bps - (-2.7006)) < 0.01
    assert r.structure_dv01 == pytest.approx(74_960.34)


def test_off_market_curve_bought_via_ptp():
    # user-verified PTP_4135370792000000201: NPV_pay -94,254 vs |PTP| 48,419
    legs = _legs([
        _leg_row("A", 0.037097, ufro=22998.45996, ptp=-48419.0, notional=7.4e9),
        _leg_row("B", 0.038335, ufro=25502.85562, ptp=-48419.0, notional=8.7e9,
                 eff="2026-09-16", mat="2026-10-28"),
    ])
    u = Unit("P", "CURVE", legs, "P", True)
    r = classify_unit(u, [
        LegPricing(3.711621, 19207.35, 100_003.19),
        LegPricing(3.822191, -113461.62, 100_327.57),
    ])
    assert r.reported_ptp == -48419.0
    assert r.dealer_bought is True and r.dealer_direction == "RECEIVED"
    assert abs(r.repriced_npv - (-94254.26)) < 1.0
    assert abs(r.dealer_charge - 45835.26) < 1.0
    assert abs(r.dealer_charge_bps - 0.4569) < 0.005


def test_off_market_curve_sold():
    # PTP_4129543090000000501: NPV_pay -201,564 vs |PTP| 251,977 -> SOLD/PAID
    legs = _legs([
        _leg_row("A", 0.03713, ufro=204640.92, ptp=-251977.0, notional=5.5e9),
        _leg_row("B", 0.03799, ufro=45463.44, ptp=-251977.0, notional=6.5e9,
                 eff="2026-09-16", mat="2026-10-28"),
    ])
    u = Unit("P", "CURVE", legs, "P", True)
    r = classify_unit(u, [
        LegPricing(3.692295, -153895.99, 74_328.99),
        LegPricing(3.792641, -47667.82, 74_962.26),
    ])
    assert r.dealer_bought is False and r.dealer_direction == "PAID"
    assert abs(r.dealer_charge_bps - 0.6725) < 0.005


def test_on_market_fly_received():
    # SOFR 8M/9M/1Y fly: traded -3.970 vs mid -4.031
    legs = _legs([
        _leg_row("A", 0.039060, eff="2026-07-14", mat="2027-03-14"),
        _leg_row("B", 0.039339, eff="2026-07-14", mat="2027-04-14"),
        _leg_row("C", 0.040015, eff="2026-07-14", mat="2027-07-14"),
    ])
    u = Unit("P", "FLY", legs, "P", False)
    r = classify_unit(u, [
        LegPricing(3.906754, None, 8578.47),
        LegPricing(3.934867, None, 16985.91),
        LegPricing(4.003289, None, 8471.46),
    ])
    assert r.classification_method == "FLY_VS_MID"
    assert r.dealer_direction == "RECEIVED"
    assert abs(r.spread_to_mid_bps - 0.0610) < 0.005


def test_off_market_missing_upfront_is_unknown():
    u = Unit("T", "OUTRIGHT", _legs([_leg_row("T", 0.03713)]), None, True)
    r = classify_unit(u, [LegPricing(3.7175, 22554.95, 50001.0)])
    # unit flagged off-market but no UFRO/PTP resolvable -> UNKNOWN + flag
    assert r.dealer_direction == "UNKNOWN"
    assert "NO_UPFRONT" in r.quality_flags
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_classifier.py -v`
Expected: FAIL with module not found

- [ ] **Step 3: Write the implementation**

```python
# SDRUtils/stir_flow/classifier.py
"""Pure dealer-direction rules (spec section 5). Confidence added separately."""
from __future__ import annotations

import dataclasses

from SDRUtils.stir_flow import config
from SDRUtils.stir_flow.trade_selection import Unit, resolve_upfront


@dataclasses.dataclass
class DirectionResult:
    unit_key: str
    trade_id: str | None
    package_id: str | None
    classification_method: str
    dealer_direction: str = "UNKNOWN"
    dealer_bought: bool | None = None
    is_off_market: bool = False
    curve_mid: float | None = None
    curve_mid_spread_bps: float | None = None
    traded_spread_bps: float | None = None
    spread_to_mid_bps: float | None = None
    repriced_npv: float | None = None
    repriced_pv01: float | None = None
    reported_opa: float | None = None
    reported_ptp: float | None = None
    dealer_charge: float | None = None
    dealer_charge_bps: float | None = None
    structure_dv01: float | None = None
    quality_flags: list = dataclasses.field(default_factory=list)


def structure_dv01(kind: str, pv01s: list) -> float:
    a = [abs(float(p)) for p in pv01s]
    if kind == "OUTRIGHT":
        return a[0]
    if kind == "CURVE":
        return max(a)
    if kind == "FLY":
        return a[1]                    # legs sorted by maturity -> middle = belly
    return sum(a) / 2.0                # PKG-N: gross/2


def _rate_pct(decimal_rate) -> float:
    return float(decimal_rate) * 100.0


def classify_unit(unit: Unit, pricings: list) -> DirectionResult:
    legs = unit.legs
    first = legs.iloc[0]
    res = DirectionResult(
        unit_key=unit.unit_key,
        trade_id=first["trade_id"] if unit.kind == "OUTRIGHT" else None,
        package_id=unit.package_id,
        classification_method="",
        is_off_market=unit.is_off_market,
    )
    pv01s = [p.pv01 for p in pricings]
    res.structure_dv01 = structure_dv01(unit.kind, pv01s)
    res.repriced_pv01 = sum(abs(p) for p in pv01s)
    ptp_raw = first.get("pkg_ptp")
    if ptp_raw is not None and ptp_raw == ptp_raw:
        res.reported_ptp = float(ptp_raw)
    ufros = list(legs["other_payment_ufro"].fillna(0.0))
    res.reported_opa = sum(ufros) if any(u > 0 for u in ufros) else None

    if unit.is_off_market:
        res.classification_method = "NPV_VS_UPFRONT"
        upfront, src, disagree = resolve_upfront(ptp_raw, ufros)
        if disagree:
            res.quality_flags.append("PTP_UFRO_DISAGREE")
        if upfront is None:
            res.quality_flags.append("NO_UPFRONT")
            return res
        npv_pay = sum(p.npv_pay for p in pricings)
        res.repriced_npv = npv_pay
        res.dealer_bought = upfront < abs(npv_pay)
        itm_side = "PAID" if npv_pay > 0 else "RECEIVED"
        other = "RECEIVED" if itm_side == "PAID" else "PAID"
        res.dealer_direction = itm_side if res.dealer_bought else other
        res.dealer_charge = abs(abs(npv_pay) - upfront)
        res.dealer_charge_bps = res.dealer_charge / res.structure_dv01
        return res

    # on-market
    traded = [_rate_pct(r) for r in legs["fixed_rate"]]
    mids = [p.mid_pct for p in pricings]
    if unit.kind == "OUTRIGHT":
        res.classification_method = "RATE_VS_MID"
        res.curve_mid = mids[0]
        s2m = (traded[0] - mids[0]) * 100.0
    elif unit.kind == "CURVE":
        res.classification_method = "SPREAD_VS_MID"
        res.traded_spread_bps = (traded[1] - traded[0]) * 100.0
        res.curve_mid_spread_bps = (mids[1] - mids[0]) * 100.0
        s2m = res.traded_spread_bps - res.curve_mid_spread_bps
    elif unit.kind == "FLY":
        res.classification_method = "FLY_VS_MID"
        res.traded_spread_bps = (2 * traded[1] - traded[0] - traded[2]) * 100.0
        res.curve_mid_spread_bps = (2 * mids[1] - mids[0] - mids[2]) * 100.0
        s2m = res.traded_spread_bps - res.curve_mid_spread_bps
    else:
        res.classification_method = "RATE_VS_MID"
        res.quality_flags.append("ON_MARKET_PKG_N_UNSUPPORTED")
        return res
    res.spread_to_mid_bps = s2m
    res.dealer_direction = "RECEIVED" if s2m > 0 else "PAID"
    return res
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_classifier.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/stir_flow/classifier.py tests/test_stir_flow_classifier.py
git commit -m "feat(stir-flow): direction classifier with golden-number tests"
```

---

### Task 6: Confidence model

**Files:**
- Create: `SDRUtils/stir_flow/confidence.py`
- Test: `tests/test_stir_flow_confidence.py`

**Interfaces:**
- Consumes: `config` thresholds.
- Produces:
  - `TickStats` dataclass: `median_tick_bps: float | None`, `disp_jns: float | None`, `futures_tick_bps: float`.
  - `sigma_mid(stats: TickStats) -> float`
  - `p_flip(deviation_bps: float, sigma: float) -> float`
  - `ConfidenceDecision` dataclass: `confidence: str`, `p_flip: float | None`, `use_tick_rule: bool`, `curve_suspect_trade: bool`.
  - `score_on_market(s2m_bps, stats, is_block) -> ConfidenceDecision`
  - `score_off_market(charge_bps, stats) -> ConfidenceDecision`
  - `apply_tick_rule(rate_pct, prev_rate_pct) -> str | None` — 'RECEIVED' on uptick, 'PAID' on downtick, None if equal/missing.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stir_flow_confidence.py
import math
import pytest
from SDRUtils.stir_flow.confidence import (
    ConfidenceDecision, TickStats, apply_tick_rule, p_flip,
    score_off_market, score_on_market, sigma_mid,
)


def test_sigma_mid_decomposition_and_fallback():
    # DispJNS^2 = (S/2)^2 + sigma^2 -> sigma = sqrt(0.3^2 - 0.25^2)
    s = TickStats(median_tick_bps=0.5, disp_jns=0.3, futures_tick_bps=0.5)
    assert sigma_mid(s) == pytest.approx(math.sqrt(0.09 - 0.0625), rel=1e-6)
    # thin sample -> futures_tick/2
    s2 = TickStats(median_tick_bps=None, disp_jns=None, futures_tick_bps=0.5)
    assert sigma_mid(s2) == 0.25


def test_p_flip_boundaries():
    assert p_flip(0.0, 0.25) == pytest.approx(0.5)
    assert p_flip(1.0, 0.25) < 0.001
    assert 0.0 < p_flip(0.25, 0.25) < 0.5


def test_hump_outlier_capped_low_and_flagged():
    s = TickStats(0.5, 0.3, 0.5)
    d = score_on_market(3.11, s, is_block=False)   # 6x the tick
    assert d.confidence == "LOW" and d.curve_suspect_trade
    d_blk = score_on_market(3.11, s, is_block=True)
    assert d_blk.confidence == "MEDIUM" and d_blk.curve_suspect_trade


def test_ambiguous_zone_requests_tick_rule():
    s = TickStats(0.5, 0.3, 0.5)
    d = score_on_market(0.05, s, is_block=False)   # < 0.5*(S/2)=0.125
    assert d.use_tick_rule and d.confidence == "LOW"


def test_main_zone_pflip_tiers():
    s = TickStats(0.5, 0.3, 0.5)      # sigma ~ 0.166
    d = score_on_market(0.18, s, is_block=False)   # z~1.08 -> P~0.14 -> MEDIUM
    assert d.confidence == "MEDIUM" and not d.use_tick_rule
    d_hi = score_on_market(0.45, s, is_block=False)  # z~2.7 -> P<0.05 -> HIGH
    assert d_hi.confidence == "HIGH"


def test_off_market_textbook_print_not_punished():
    # POC correction: 0.18bp charge vs 0.5bp FF tick was wrongly LOW before
    s = TickStats(0.5, 0.3, 0.5)
    d = score_off_market(0.18, s)
    assert d.confidence == "MEDIUM"


def test_off_market_outlier_charge_flagged():
    s = TickStats(0.5, 0.3, 0.5)
    d = score_off_market(3.0, s)      # > 3*S
    assert d.confidence == "LOW" and d.curve_suspect_trade


def test_apply_tick_rule():
    assert apply_tick_rule(3.715, 3.713) == "RECEIVED"
    assert apply_tick_rule(3.713, 3.715) == "PAID"
    assert apply_tick_rule(3.713, 3.713) is None
    assert apply_tick_rule(3.713, None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_confidence.py -v`
Expected: FAIL with module not found

- [ ] **Step 3: Write the implementation**

```python
# SDRUtils/stir_flow/confidence.py
"""Hump-shaped confidence model (spec section 6e)."""
from __future__ import annotations

import dataclasses
import math

from SDRUtils.stir_flow import config


@dataclasses.dataclass
class TickStats:
    median_tick_bps: float | None
    disp_jns: float | None
    futures_tick_bps: float


@dataclasses.dataclass
class ConfidenceDecision:
    confidence: str
    p_flip: float | None = None
    use_tick_rule: bool = False
    curve_suspect_trade: bool = False


def _tick(stats: TickStats) -> float:
    if stats.median_tick_bps is not None and stats.median_tick_bps > 0:
        return stats.median_tick_bps
    return stats.futures_tick_bps


def sigma_mid(stats: TickStats) -> float:
    half = _tick(stats) / 2.0
    if stats.disp_jns is not None and stats.disp_jns > half:
        return math.sqrt(stats.disp_jns ** 2 - half ** 2)
    return stats.futures_tick_bps / 2.0


def p_flip(deviation_bps: float, sigma: float) -> float:
    if sigma <= 0:
        return 0.0
    z = abs(deviation_bps) / sigma
    return 1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _tier(p: float) -> str:
    if p < config.P_FLIP_HIGH:
        return "HIGH"
    if p < config.P_FLIP_MEDIUM:
        return "MEDIUM"
    return "LOW"


def score_on_market(s2m_bps: float, stats: TickStats, is_block: bool) -> ConfidenceDecision:
    s = _tick(stats)
    dev = abs(s2m_bps)
    if dev > config.HUMP_OUTLIER_MULT * s:
        return ConfidenceDecision(
            confidence="MEDIUM" if is_block else "LOW",
            curve_suspect_trade=True,
        )
    if dev < config.AMBIGUOUS_FRAC * (s / 2.0):
        return ConfidenceDecision(confidence="LOW", use_tick_rule=True)
    p = p_flip(dev, sigma_mid(stats))
    return ConfidenceDecision(confidence=_tier(p), p_flip=p)


def score_off_market(charge_bps: float, stats: TickStats) -> ConfidenceDecision:
    s = _tick(stats)
    dev = abs(charge_bps)
    if dev > config.HUMP_OUTLIER_MULT * s:
        return ConfidenceDecision(confidence="LOW", curve_suspect_trade=True)
    p = p_flip(dev, sigma_mid(stats))
    return ConfidenceDecision(confidence=_tier(p), p_flip=p)


def apply_tick_rule(rate_pct, prev_rate_pct):
    if prev_rate_pct is None or rate_pct is None:
        return None
    if rate_pct > prev_rate_pct:
        return "RECEIVED"
    if rate_pct < prev_rate_pct:
        return "PAID"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_confidence.py -v`
Expected: 8 PASS. If `test_main_zone_pflip_tiers` or `test_off_market_textbook_print_not_punished` fail on tier boundaries, print the computed `p_flip` and adjust the test's expected tier to the computed value ONLY if the math is verified by hand (z = dev/σ, σ = sqrt(0.09−0.0625) ≈ 0.1658; dev 0.18 → z 1.086 → P ≈ 0.139 → MEDIUM; dev 0.45 → z 2.715 → P ≈ 0.0033 → HIGH).

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/stir_flow/confidence.py tests/test_stir_flow_confidence.py
git commit -m "feat(stir-flow): hump confidence model, P_flip, tick-rule fallback"
```

---

### Task 7: Tick size + dispersion stats

**Files:**
- Create: `SDRUtils/stir_flow/tick_size.py`
- Test: `tests/test_stir_flow_tick_size.py`

**Interfaces:**
- Consumes: `config.assign_dv01_bucket`, `config.TICK_PAIR_MAX_GAP_MIN`, `config.MIN_DISP_VW_BPS`, `config.CURVE_SUSPECT_RATIO`, `config.futures_tick_bps`.
- Produces (all pure pandas functions):
  - `tenor_bucket_for(row: dict | pd.Series) -> str` — FOMC → `f"FOMC_{fomc_meeting_label}"`; IMM → `f"IMM_{tenor_label}"`; STANDARD spot (fwd < 0.05y) → `tenor_label`; STANDARD fwd → `f"{forward_label}x{tenor_label}"`; missing pieces → "UNMAPPED".
  - `build_tick_pairs(prints: pd.DataFrame) -> pd.DataFrame` — input columns `[tenor_bucket, structure_type, as_of_date, execution_session, execution_timestamp, rate_pct, dv01]`; output columns `[tenor_bucket, structure_type, dv01_bucket, as_of_date, tick_bps]` (dv01_bucket from the LATER print of each pair).
  - `compute_bucket_stats(pairs, prints, offmkt) -> pd.DataFrame` — one row per (tenor_bucket, structure_type, dv01_bucket, as_of_date) plus a `dv01_bucket='ALL'` row; columns matching the tick table.
  - `compute_dispersion(prints_with_s2m: pd.DataFrame) -> pd.DataFrame` — per (tenor_bucket, structure_type, as_of_date): `disp_vw`, `disp_jns`, `curve_suspect`; input adds column `s2m_bps` (nullable — rows without mids excluded from disp_jns but kept for disp_vw).
  - `compute_amihud(daily_vwap: pd.DataFrame) -> pd.DataFrame` — per bucket-day `|Δvwap_bps| / total_dv01`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stir_flow_tick_size.py
import datetime
import numpy as np
import pandas as pd
import pytest
from SDRUtils.stir_flow import tick_size as tk


def test_tenor_bucket_for():
    assert tk.tenor_bucket_for({"special_tenor_type": "FOMC", "fomc_meeting_label": "JUL26",
                                "tenor_label": "2M", "forward_label": None,
                                "forward_start_years": 0.0}) == "FOMC_JUL26"
    assert tk.tenor_bucket_for({"special_tenor_type": "IMM", "fomc_meeting_label": None,
                                "tenor_label": "1Y", "forward_label": "IMM_Z2027",
                                "forward_start_years": 1.4}) == "IMM_1Y"
    assert tk.tenor_bucket_for({"special_tenor_type": "STANDARD", "fomc_meeting_label": None,
                                "tenor_label": "2Y", "forward_label": None,
                                "forward_start_years": 0.0}) == "2Y"
    assert tk.tenor_bucket_for({"special_tenor_type": "STANDARD", "fomc_meeting_label": None,
                                "tenor_label": "1Y", "forward_label": "1Y",
                                "forward_start_years": 1.0}) == "1Yx1Y"


def _prints(rows):
    df = pd.DataFrame(rows)
    df["as_of_date"] = datetime.date(2026, 7, 10)
    df["tenor_bucket"] = "FOMC_JUL26"
    df["structure_type"] = "OUTRIGHT"
    df["execution_session"] = "NY_AM"
    return df


def test_build_tick_pairs_gap_and_session_rules():
    t0 = pd.Timestamp("2026-07-10 14:00:00+00:00")
    rows = [
        dict(execution_timestamp=t0, rate_pct=3.710, dv01=10_000),
        dict(execution_timestamp=t0 + pd.Timedelta(minutes=10), rate_pct=3.715, dv01=10_000),
        dict(execution_timestamp=t0 + pd.Timedelta(minutes=100), rate_pct=3.700, dv01=10_000),  # gap>60m dropped
    ]
    pairs = tk.build_tick_pairs(_prints(rows))
    assert len(pairs) == 1
    assert pairs.iloc[0]["tick_bps"] == pytest.approx(0.5)
    assert pairs.iloc[0]["dv01_bucket"] == "SMALL"

    # different sessions never pair
    df = _prints([
        dict(execution_timestamp=t0, rate_pct=3.710, dv01=10_000),
        dict(execution_timestamp=t0 + pd.Timedelta(minutes=5), rate_pct=3.715, dv01=10_000),
    ])
    df.loc[1, "execution_session"] = "NY_PM"
    assert len(tk.build_tick_pairs(df)) == 0


def test_compute_dispersion_and_curve_suspect():
    # trades agree with each other (disp_vw ~ 0) but sit 2bp from our mid -> suspect
    df = _prints([
        dict(execution_timestamp=pd.Timestamp("2026-07-10 14:00:00+00:00"),
             rate_pct=3.710, dv01=10_000, s2m_bps=2.0),
        dict(execution_timestamp=pd.Timestamp("2026-07-10 14:10:00+00:00"),
             rate_pct=3.7101, dv01=10_000, s2m_bps=2.01),
    ])
    disp = tk.compute_dispersion(df)
    row = disp.iloc[0]
    assert row["disp_jns"] == pytest.approx(2.005, abs=0.01)
    assert row["disp_vw"] < 0.1
    assert bool(row["curve_suspect"]) is True


def test_compute_bucket_stats_medians():
    pairs = pd.DataFrame({
        "tenor_bucket": ["FOMC_JUL26"] * 4, "structure_type": ["OUTRIGHT"] * 4,
        "dv01_bucket": ["SMALL"] * 4, "as_of_date": [datetime.date(2026, 7, 10)] * 4,
        "tick_bps": [0.25, 0.5, 0.5, 1.0],
    })
    prints = _prints([dict(execution_timestamp=pd.Timestamp("2026-07-10 14:00:00+00:00"),
                           rate_pct=3.71, dv01=10_000)])
    prints["rate_index_clean"] = "FED_FUNDS"
    offmkt = pd.DataFrame({
        "tenor_bucket": ["FOMC_JUL26"], "structure_type": ["OUTRIGHT"],
        "dv01_bucket": ["SMALL"], "as_of_date": [datetime.date(2026, 7, 10)],
        "dealer_charge_bps": [0.18],
    })
    stats = tk.compute_bucket_stats(pairs, prints, offmkt)
    small = stats[stats["dv01_bucket"] == "SMALL"].iloc[0]
    assert small["median_tick_bps"] == pytest.approx(0.5)
    assert small["tick_sample_count"] == 4
    assert small["median_dealer_charge_bps"] == pytest.approx(0.18)
    assert small["futures_min_tick_bps"] == pytest.approx(0.5)
    assert (stats["dv01_bucket"] == "ALL").any()


def test_compute_amihud():
    daily = pd.DataFrame({
        "tenor_bucket": ["2Y", "2Y"], "structure_type": ["OUTRIGHT"] * 2,
        "as_of_date": [datetime.date(2026, 7, 9), datetime.date(2026, 7, 10)],
        "vwap_rate_pct": [4.060, 4.065], "total_dv01": [1e6, 2e6],
    })
    am = tk.compute_amihud(daily)
    row = am[am["as_of_date"] == datetime.date(2026, 7, 10)].iloc[0]
    assert row["amihud"] == pytest.approx(0.5 / 2e6)   # 0.5bp move / 2M dv01
    assert am[am["as_of_date"] == datetime.date(2026, 7, 9)]["amihud"].isna().all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_tick_size.py -v`
Expected: FAIL with module not found

- [ ] **Step 3: Write the implementation**

```python
# SDRUtils/stir_flow/tick_size.py
"""Clarus tick pairs + BoE dispersion metrics (spec section 6)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from SDRUtils.stir_flow import config


def tenor_bucket_for(row) -> str:
    stt = row.get("special_tenor_type") or "STANDARD"
    if stt == "FOMC":
        lbl = row.get("fomc_meeting_label")
        return f"FOMC_{lbl}" if lbl else "UNMAPPED"
    if stt == "IMM":
        t = row.get("tenor_label")
        return f"IMM_{t}" if t else "UNMAPPED"
    t = row.get("tenor_label")
    if not t:
        return "UNMAPPED"
    fsy = row.get("forward_start_years") or 0.0
    if abs(fsy) < 0.05:
        return str(t)
    fwd = row.get("forward_label")
    return f"{fwd}x{t}" if fwd else "UNMAPPED"


_KEY = ["tenor_bucket", "structure_type", "as_of_date", "execution_session"]


def build_tick_pairs(prints: pd.DataFrame) -> pd.DataFrame:
    out = []
    for _, grp in prints.groupby(_KEY, dropna=False):
        g = grp.sort_values("execution_timestamp")
        ts = pd.to_datetime(g["execution_timestamp"])
        gap_min = ts.diff().dt.total_seconds() / 60.0
        tick = (g["rate_pct"].diff().abs() * 100.0)
        ok = gap_min <= config.TICK_PAIR_MAX_GAP_MIN
        sel = g[ok & tick.notna()]
        if sel.empty:
            continue
        out.append(pd.DataFrame({
            "tenor_bucket": sel["tenor_bucket"].values,
            "structure_type": sel["structure_type"].values,
            "dv01_bucket": [config.assign_dv01_bucket(v) for v in sel["dv01"]],
            "as_of_date": sel["as_of_date"].values,
            "tick_bps": tick[sel.index].values,
        }))
    if not out:
        return pd.DataFrame(columns=["tenor_bucket", "structure_type", "dv01_bucket",
                                     "as_of_date", "tick_bps"])
    return pd.concat(out, ignore_index=True)


def compute_dispersion(prints: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key, g in prints.groupby(["tenor_bucket", "structure_type", "as_of_date"], dropna=False):
        w = g["dv01"].abs().astype(float)
        if w.sum() <= 0:
            w = pd.Series(1.0, index=g.index)
        w = w / w.sum()
        vwap = float((w * g["rate_pct"]).sum())
        disp_vw = float(np.sqrt((w * ((g["rate_pct"] - vwap) * 100.0) ** 2).sum()))
        disp_jns = None
        if "s2m_bps" in g and g["s2m_bps"].notna().any():
            m = g["s2m_bps"].notna()
            wj = w[m] / w[m].sum()
            disp_jns = float(np.sqrt((wj * g.loc[m, "s2m_bps"] ** 2).sum()))
        suspect = False
        if disp_jns is not None:
            suspect = (disp_jns / max(disp_vw, config.MIN_DISP_VW_BPS)) > config.CURVE_SUSPECT_RATIO
        rows.append(dict(zip(["tenor_bucket", "structure_type", "as_of_date"], key))
                    | dict(disp_vw=disp_vw, disp_jns=disp_jns, curve_suspect=suspect,
                           vwap_rate_pct=vwap, total_dv01=float(g["dv01"].abs().sum()),
                           trade_count=len(g)))
    return pd.DataFrame(rows)


def compute_amihud(daily_vwap: pd.DataFrame) -> pd.DataFrame:
    df = daily_vwap.sort_values("as_of_date").copy()
    def _per_bucket(g):
        g = g.copy()
        dv = g["vwap_rate_pct"].diff().abs() * 100.0
        g["amihud"] = dv / g["total_dv01"]
        return g
    return df.groupby(["tenor_bucket", "structure_type"], group_keys=False).apply(_per_bucket)


def compute_bucket_stats(pairs: pd.DataFrame, prints: pd.DataFrame,
                         offmkt: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for with_all in (False, True):
        p = pairs.copy()
        o = offmkt.copy() if offmkt is not None and len(offmkt) else pd.DataFrame(
            columns=["tenor_bucket", "structure_type", "dv01_bucket", "as_of_date",
                     "dealer_charge_bps"])
        if with_all:
            p["dv01_bucket"] = "ALL"
            o["dv01_bucket"] = "ALL"
        key = ["tenor_bucket", "structure_type", "dv01_bucket", "as_of_date"]
        tick_stats = p.groupby(key)["tick_bps"].agg(
            mean_tick_bps="mean", median_tick_bps="median",
            p25_tick_bps=lambda s: s.quantile(0.25),
            p75_tick_bps=lambda s: s.quantile(0.75),
            tick_sample_count="count").reset_index()
        edge = o.groupby(key)["dealer_charge_bps"].agg(
            mean_dealer_charge_bps="mean", median_dealer_charge_bps="median",
            edge_sample_count="count").reset_index()
        frames.append(tick_stats.merge(edge, on=key, how="outer"))
    stats = pd.concat(frames, ignore_index=True)
    # futures tick floor: FED_FUNDS or FOMC_* buckets -> 0.5, else 0.25
    idx_map = {}
    if prints is not None and len(prints) and "rate_index_clean" in prints:
        idx_map = prints.groupby("tenor_bucket")["rate_index_clean"].first().to_dict()
    def _floor(b):
        ri = idx_map.get(b, "SOFR")
        stt = "FOMC" if str(b).startswith("FOMC_") else "STANDARD"
        return config.futures_tick_bps(ri, stt)
    stats["futures_min_tick_bps"] = stats["tenor_bucket"].map(_floor)
    return stats
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_tick_size.py -v`
Expected: 5 PASS

- [ ] **Step 5: Run the full fast gate for the package so far**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_config.py tests/test_stir_flow_selection.py tests/test_stir_flow_pricing.py tests/test_stir_flow_classifier.py tests/test_stir_flow_confidence.py tests/test_stir_flow_tick_size.py tests/test_stir_flow_backfill.py -m "not slow and not network and not db" -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/stir_flow/tick_size.py tests/test_stir_flow_tick_size.py
git commit -m "feat(stir-flow): tick pairs, DispVW/DispJNS/Amihud, bucket stats"
```

---

### Task 8: Backfill orchestrator CLI

**Files:**
- Create: `SDRUtils/_swappulse_scripts/backfill_stir_direction.py`
- Modify: `tests/test_stir_flow_backfill.py` (append orchestration tests)

**Interfaces:**
- Consumes: everything above, plus `resolve_pg_url` from `SDRUtils._swappulse_scripts.ingest_usdswaps_tape`.
- Produces CLI:
  ```
  conda run -n stir python -m SDRUtils._swappulse_scripts.backfill_stir_direction \
      --classify-date 2026-07-10 --calib-start 2026-06-10 --calib-end 2026-07-10 \
      [--calib-mode ticks-only|full] [--limit N] [--dry-run] [--pg-url URL]
  ```
  and library functions used by tests: `classify_units(units, pricer, tick_lookup, prev_rate_lookup) -> list[dict]` (rows ready for insert; per-unit try/except → UNKNOWN row with `quality_flags=['PRICING_ERROR:...']`), `write_direction_rows(conn, rows)`, `write_tick_rows(conn, stats_df)` (both `execute_values` upserts with `ON CONFLICT ... DO UPDATE`).

- [ ] **Step 1: Write the failing tests (append to tests/test_stir_flow_backfill.py)**

```python
import datetime
import pandas as pd
import pytest
from SDRUtils.stir_flow.pricing import LegPricing
from SDRUtils.stir_flow.trade_selection import Unit


def _unit_df():
    return pd.DataFrame([dict(
        trade_id="T1", package_id="OUTRIGHT-T1", as_of_date=datetime.date(2026, 7, 10),
        execution_timestamp=pd.Timestamp("2026-07-10 19:41:45+00:00"),
        original_execution_timestamp=pd.Timestamp("2026-07-10 19:41:45+00:00"),
        trade_type="OUTRIGHT", rate_index_clean="FED_FUNDS",
        special_tenor_type="FOMC", fomc_meeting_label="JUL26",
        tenor_label="2M", forward_label=None, forward_start_years=0.0,
        effective_date=datetime.date(2026, 7, 29),
        expiration_date=datetime.date(2026, 9, 16),
        notional=3.7e9, risk=50_000.0, fixed_rate=0.03713,
        other_payment_ufro=13427.26854, pkg_ptp=None, pkg_pts=None,
        is_capped=False, is_block=False, is_off_date=False,
        leg_tape_label="FF FOMC JUL26", execution_session="NY_PM",
        package_structure="2M Outright", n_package_legs=1,
    )])


def test_classify_units_produces_row_and_handles_errors():
    from SDRUtils._swappulse_scripts import backfill_stir_direction as bf

    unit = Unit("T1", "OUTRIGHT", _unit_df(), None, True)

    class FakePricer:
        def price_leg(self, curve_name, ts, eff, mat, notional, fixed_rate=None):
            return LegPricing(3.717511, 22554.95, 50000.99)

    rows = bf.classify_units([unit], FakePricer(),
                             tick_lookup=lambda *a: None,
                             prev_rate_lookup=lambda *a: None)
    r = rows[0]
    assert r["unit_key"] == "T1"
    assert r["dealer_direction"] == "PAID" and r["dealer_bought"] is True
    assert r["curve_name"] == "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"
    assert r["tenor_bucket"] == "FOMC_JUL26"

    class BoomPricer:
        def price_leg(self, *a, **k):
            raise ValueError("fixings gap")

    rows = bf.classify_units([unit], BoomPricer(),
                             tick_lookup=lambda *a: None,
                             prev_rate_lookup=lambda *a: None)
    r = rows[0]
    assert r["dealer_direction"] == "UNKNOWN"
    assert any(f.startswith("PRICING_ERROR") for f in r["quality_flags"])


def test_write_direction_rows_upsert_sql():
    from SDRUtils._swappulse_scripts import backfill_stir_direction as bf
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class FakeConn:
        def cursor(self):
            return FakeCursor()
        def commit(self):
            captured["committed"] = True

    def fake_execute_values(cur, sql, argslist, template=None):
        captured["sql"] = sql
        captured["n"] = len(argslist)

    bf._execute_values = fake_execute_values  # inject
    bf.write_direction_rows(FakeConn(), [dict(bf.EMPTY_DIRECTION_ROW, unit_key="T1",
                                              as_of_date=datetime.date(2026, 7, 10),
                                              execution_timestamp=pd.Timestamp("2026-07-10 19:41:45+00:00"))])
    assert "ON CONFLICT (unit_key) DO UPDATE" in captured["sql"]
    assert captured["n"] == 1 and captured["committed"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_backfill.py -v`
Expected: new tests FAIL (module attribute missing)

- [ ] **Step 3: Write the implementation**

```python
# SDRUtils/_swappulse_scripts/backfill_stir_direction.py
"""Backfill STIR dealer-direction classifications + tick-size calibration.

POC (spec 2026-07-12): classify --classify-date; calibrate ticks over
[--calib-start, --calib-end]. Writes ONLY arbs_stir_direction_v1 /
arbs_stir_tick_size_v1.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values as _execute_values

from SDRUtils._swappulse_scripts._stir_flow_schema_v1 import (
    DIRECTION_TABLE, TICK_TABLE, ensure_schema,
)
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.stir_flow import config, tick_size
from SDRUtils.stir_flow.classifier import classify_unit
from SDRUtils.stir_flow.confidence import (
    TickStats, apply_tick_rule, score_off_market, score_on_market,
)
from SDRUtils.stir_flow.pricing import CurvePricer, snap_timestamp
from SDRUtils.stir_flow.trade_selection import (
    ALL_PKG_LEGS_SQL, ELIGIBLE_LEGS_SQL, build_units, is_excluded_unit,
)

DIRECTION_COLUMNS = [
    "unit_key", "trade_id", "package_id", "as_of_date", "execution_timestamp",
    "trade_type", "rate_index_clean", "curve_name", "curve_timestamp",
    "is_off_market", "classification_method", "curve_mid", "curve_mid_spread_bps",
    "fixed_rate", "traded_spread_bps", "spread_to_mid_bps", "repriced_npv",
    "repriced_pv01", "reported_opa", "reported_ptp", "dealer_direction",
    "dealer_bought", "direction_confidence", "p_flip", "dealer_charge",
    "dealer_charge_bps", "structure_dv01", "notional", "dv01", "tenor_query",
    "tenor_bucket", "dv01_bucket", "curve_suspect_trade", "quality_flags",
]
EMPTY_DIRECTION_ROW = {c: None for c in DIRECTION_COLUMNS}


def _unit_meta(unit):
    first = unit.legs.iloc[0]
    curve_name = config.CURVE_FOR[first["rate_index_clean"]]
    snap = snap_timestamp(first.get("original_execution_timestamp"),
                          first["execution_timestamp"])
    bucket = tick_size.tenor_bucket_for(first)
    total_dv01 = float(unit.legs["risk"].abs().sum())
    return first, curve_name, snap, bucket, total_dv01


def classify_units(units, pricer, tick_lookup, prev_rate_lookup):
    rows = []
    for unit in units:
        first, curve_name, snap, bucket, total_dv01 = _unit_meta(unit)
        row = dict(EMPTY_DIRECTION_ROW)
        row.update(
            unit_key=unit.unit_key,
            trade_id=first["trade_id"] if unit.kind == "OUTRIGHT" else None,
            package_id=unit.package_id,
            as_of_date=first["as_of_date"],
            execution_timestamp=first["execution_timestamp"],
            trade_type=unit.kind,
            rate_index_clean=first["rate_index_clean"],
            curve_name=curve_name,
            curve_timestamp=snap,
            is_off_market=unit.is_off_market,
            dealer_direction="UNKNOWN",
            fixed_rate=float(first["fixed_rate"]) if unit.kind == "OUTRIGHT" else None,
            notional=float(unit.legs["notional"].sum()),
            dv01=total_dv01,
            tenor_bucket=bucket,
            dv01_bucket=config.assign_dv01_bucket(total_dv01),
            tenor_query=f"{first['effective_date']}->{unit.legs.iloc[-1]['expiration_date']}",
            quality_flags=[],
        )
        try:
            pricings = []
            for _, leg in unit.legs.iterrows():
                fixed = float(leg["fixed_rate"]) if unit.is_off_market else None
                pricings.append(pricer.price_leg(
                    curve_name, snap, leg["effective_date"], leg["expiration_date"],
                    notional=float(leg["notional"]), fixed_rate=fixed,
                ))
            res = classify_unit(unit, pricings)
            for f in ("classification_method", "dealer_direction", "dealer_bought",
                      "curve_mid", "curve_mid_spread_bps", "traded_spread_bps",
                      "spread_to_mid_bps", "repriced_npv", "repriced_pv01",
                      "reported_opa", "reported_ptp", "dealer_charge",
                      "dealer_charge_bps", "structure_dv01"):
                row[f] = getattr(res, f)
            row["quality_flags"] = list(res.quality_flags)

            stats = tick_lookup(bucket, unit.kind, row["dv01_bucket"]) or TickStats(
                None, None, config.futures_tick_bps(
                    first["rate_index_clean"], first["special_tenor_type"]))
            if res.dealer_direction != "UNKNOWN":
                if unit.is_off_market:
                    dec = score_off_market(res.dealer_charge_bps, stats)
                else:
                    dec = score_on_market(res.spread_to_mid_bps,
                                          stats, bool(first.get("is_block")))
                    if dec.use_tick_rule:
                        prev = prev_rate_lookup(bucket, unit.kind,
                                                first["execution_timestamp"])
                        tr = apply_tick_rule(float(first["fixed_rate"]) * 100.0, prev)
                        if tr is not None:
                            row["dealer_direction"] = tr
                            row["classification_method"] = "TICK_RULE"
                row["direction_confidence"] = dec.confidence
                row["p_flip"] = dec.p_flip
                row["curve_suspect_trade"] = dec.curve_suspect_trade
        except Exception as exc:  # noqa: BLE001 - per-unit isolation by design
            row["quality_flags"] = list(row["quality_flags"]) + [f"PRICING_ERROR:{exc}"]
        rows.append(row)
    return rows


def write_direction_rows(conn, rows):
    if not rows:
        return
    cols = DIRECTION_COLUMNS
    sql = (
        f"INSERT INTO {DIRECTION_TABLE} ({', '.join(cols)}) VALUES %s "
        f"ON CONFLICT (unit_key) DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "unit_key")
    )
    values = [tuple(r.get(c) for c in cols) for r in rows]
    with conn.cursor() as cur:
        _execute_values(cur, sql, values)
    conn.commit()


TICK_COLUMNS = [
    "tenor_bucket", "structure_type", "dv01_bucket", "as_of_date",
    "futures_min_tick_bps", "mean_tick_bps", "median_tick_bps", "p25_tick_bps",
    "p75_tick_bps", "tick_sample_count", "mean_dealer_charge_bps",
    "median_dealer_charge_bps", "edge_sample_count", "disp_vw", "disp_jns",
    "curve_suspect", "amihud", "total_dv01_traded", "trade_count", "window_days",
]


def write_tick_rows(conn, stats_df):
    if stats_df is None or stats_df.empty:
        return
    df = stats_df.copy()
    for c in TICK_COLUMNS:
        if c not in df:
            df[c] = None
    df = df[TICK_COLUMNS].where(pd.notna(df[TICK_COLUMNS]), None)
    sql = (
        f"INSERT INTO {TICK_TABLE} ({', '.join(TICK_COLUMNS)}) VALUES %s "
        f"ON CONFLICT (tenor_bucket, structure_type, dv01_bucket, as_of_date) "
        f"DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in TICK_COLUMNS
                    if c not in ("tenor_bucket", "structure_type",
                                 "dv01_bucket", "as_of_date"))
    )
    with conn.cursor() as cur:
        _execute_values(cur, sql, [tuple(r) for r in df.itertuples(index=False)])
    conn.commit()


def _load_frames(conn, start, end):
    eligible = pd.read_sql(ELIGIBLE_LEGS_SQL, conn, params={"start": start, "end": end})
    pkg_ids = sorted(set(eligible.loc[eligible["n_package_legs"].fillna(1) > 1,
                                      "package_id"].dropna()))
    all_legs = eligible.head(0)
    if pkg_ids:
        all_legs = pd.read_sql(ALL_PKG_LEGS_SQL, conn,
                               params={"package_ids": pkg_ids})
    return eligible, all_legs


def _onmarket_prints(eligible):
    df = eligible.copy()
    df["off"] = (df["other_payment_ufro"].fillna(0).abs() > 0) | (
        df["pkg_ptp"].abs() > config.PTP_USD_FLOOR)
    on = df[~df["off"] & (df["n_package_legs"].fillna(1) <= 1)].copy()
    on["tenor_bucket"] = on.apply(tick_size.tenor_bucket_for, axis=1)
    on["structure_type"] = "OUTRIGHT"
    on["rate_pct"] = on["fixed_rate"].astype(float) * 100.0
    on["dv01"] = on["risk"].abs()
    return on[on["tenor_bucket"] != "UNMAPPED"]


def run_calibration(conn, start, end, mode):
    eligible, _ = _load_frames(conn, start, end)
    prints = _onmarket_prints(eligible)
    pairs = tick_size.build_tick_pairs(prints)
    prints["s2m_bps"] = float("nan")   # ticks-only: no mids
    disp = tick_size.compute_dispersion(prints)
    daily = disp[["tenor_bucket", "structure_type", "as_of_date",
                  "vwap_rate_pct", "total_dv01"]]
    amih = tick_size.compute_amihud(daily)
    offmkt = pd.DataFrame(columns=["tenor_bucket", "structure_type", "dv01_bucket",
                                   "as_of_date", "dealer_charge_bps"])
    if mode == "full":
        # price off-market prints over the window (expensive; relies on curve cache)
        raise NotImplementedError(
            "full calibration mode is a follow-up; POC uses ticks-only + "
            "07/10 classification-day dispersion")
    stats = tick_size.compute_bucket_stats(pairs, prints, offmkt)
    stats = stats.merge(
        disp[["tenor_bucket", "structure_type", "as_of_date",
              "disp_vw", "disp_jns", "curve_suspect", "trade_count", "total_dv01"]]
        .rename(columns={"total_dv01": "total_dv01_traded"}),
        on=["tenor_bucket", "structure_type", "as_of_date"], how="left")
    stats = stats.merge(
        amih[["tenor_bucket", "structure_type", "as_of_date", "amihud"]],
        on=["tenor_bucket", "structure_type", "as_of_date"], how="left")
    stats["window_days"] = (pd.Timestamp(end) - pd.Timestamp(start)).days
    return stats


def _build_lookups(stats):
    med = {}
    if stats is not None and len(stats):
        for _, r in stats.iterrows():
            med[(r["tenor_bucket"], r["structure_type"], r["dv01_bucket"])] = r

    def tick_lookup(bucket, kind, dv01_bucket):
        r = med.get((bucket, kind, dv01_bucket)) or med.get((bucket, kind, "ALL"))
        if r is None:
            return None
        return TickStats(
            median_tick_bps=r.get("median_tick_bps"),
            disp_jns=r.get("disp_jns"),
            futures_tick_bps=float(r.get("futures_min_tick_bps") or 0.25),
        )
    return tick_lookup


def _build_prev_rate_lookup(prints):
    idx = {}
    for key, g in prints.groupby(["tenor_bucket", "structure_type"]):
        g = g.sort_values("execution_timestamp")
        idx[key] = list(zip(g["execution_timestamp"], g["rate_pct"]))

    def prev_rate_lookup(bucket, kind, ts):
        series = idx.get((bucket, kind), [])
        prev = None
        for t, r in series:
            if t >= ts:
                break
            prev = r
        return prev
    return prev_rate_lookup


def run_classification(conn, classify_date, stats, limit=0, dry_run=False):
    eligible, all_legs = _load_frames(conn, classify_date, classify_date)
    units, skipped = [], []
    for u in build_units(eligible, all_legs):
        reason = is_excluded_unit(u.legs)
        (skipped if reason else units).append((u, reason) if reason else u)
    if limit:
        units = units[:limit]
    prints = _onmarket_prints(eligible)
    rows = classify_units(units, CurvePricer(),
                          _build_lookups(stats), _build_prev_rate_lookup(prints))
    print(f"classified {len(rows)} units; skipped {len(skipped)} "
          f"({pd.Series([r for _, r in skipped]).value_counts().to_dict() if skipped else {}})")
    if not dry_run:
        write_direction_rows(conn, rows)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg-url", default=None)
    ap.add_argument("--classify-date", required=True)
    ap.add_argument("--calib-start", required=True)
    ap.add_argument("--calib-end", required=True)
    ap.add_argument("--calib-mode", choices=["ticks-only", "full"], default="ticks-only")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = psycopg2.connect(resolve_pg_url(args.pg_url))
    ensure_schema(conn)
    stats = run_calibration(conn, args.calib_start, args.calib_end, args.calib_mode)
    if not args.dry_run:
        write_tick_rows(conn, stats)
    print(f"tick stats rows: {len(stats)}")
    rows = run_classification(conn, args.classify_date, stats,
                              limit=args.limit, dry_run=args.dry_run)
    summary = pd.DataFrame(rows)["dealer_direction"].value_counts().to_dict()
    print(f"direction summary: {json.dumps(summary)}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_stir_flow_backfill.py -v`
Expected: 4 PASS (2 schema + 2 orchestration)

- [ ] **Step 5: Run the entire fast gate**

Run: `conda run -n stir python -m pytest tests -m "not slow and not network and not db" -q`
Expected: all pass, no regressions elsewhere

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/_swappulse_scripts/backfill_stir_direction.py tests/test_stir_flow_backfill.py
git commit -m "feat(stir-flow): backfill CLI - ticks-only calibration + classification"
```

---

### Task 9: POC execution + verification against prod

This task runs the backfill for real and verifies output. It needs network + the prod DB. Do NOT run during the fast gate.

- [ ] **Step 1: Dry-run smoke on 25 units**

Run:
```bash
conda run -n stir python -m SDRUtils._swappulse_scripts.backfill_stir_direction \
  --classify-date 2026-07-10 --calib-start 2026-06-10 --calib-end 2026-07-10 \
  --limit 25 --dry-run
```
Expected: no exceptions; "classified 25 units" and a non-empty direction summary printed. Investigate any PRICING_ERROR flags beyond the known seasoned-leg fixings case.

- [ ] **Step 2: Full run (writes to prod arbs_stir_* tables only)**

Run:
```bash
conda run -n stir python -m SDRUtils._swappulse_scripts.backfill_stir_direction \
  --classify-date 2026-07-10 --calib-start 2026-06-10 --calib-end 2026-07-10
```
Expected: tick stats rows > 100; classified units in the hundreds; summary with PAID/RECEIVED/UNKNOWN counts. Runtime dominated by curve fetches; the LayeredCacheMixin cache makes re-runs fast.

- [ ] **Step 3: Verify the two user-verified golden trades in the DB**

Run:
```bash
conda run -n stir python -c "import psycopg2, pandas as pd; from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url; conn = psycopg2.connect(resolve_pg_url()); print(pd.read_sql(\"SELECT unit_key, dealer_direction, dealer_bought, dealer_charge_bps, direction_confidence, classification_method FROM arbs_stir_direction_v1 WHERE unit_key IN ('4137861837000000101','PTP_4135370792000000201')\", conn).to_string()); conn.close()"
```
Expected:
- `4137861837000000101`: NPV_VS_UPFRONT, PAID, dealer_bought=true, dealer_charge_bps ≈ 0.183
- `PTP_4135370792000000201`: NPV_VS_UPFRONT, RECEIVED, dealer_bought=true, dealer_charge_bps ≈ 0.457

- [ ] **Step 4: Sanity queries**

```sql
-- distribution
SELECT dealer_direction, direction_confidence, count(*)
FROM arbs_stir_direction_v1 WHERE as_of_date = '2026-07-10'
GROUP BY 1, 2 ORDER BY 1, 2;
-- curve-suspect rate (expect the FOMC buckets flagged from the POC to appear)
SELECT tenor_bucket, count(*) FILTER (WHERE curve_suspect_trade) AS suspect, count(*)
FROM arbs_stir_direction_v1 WHERE as_of_date = '2026-07-10'
GROUP BY 1 ORDER BY 2 DESC LIMIT 15;
-- tick table spot-check
SELECT * FROM arbs_stir_tick_size_v1
WHERE tenor_bucket = 'FOMC_JUL26' AND dv01_bucket = 'ALL'
ORDER BY as_of_date DESC LIMIT 5;
```
Expected: plausible distributions; FOMC_JUL26 median tick present with sample count > 10.

- [ ] **Step 5: Write POC results note + commit**

Write findings (row counts, direction split, charge distribution vs the 0.18–0.67bp POC range, curve_suspect rate, list of PRICING_ERROR units) to `docs/superpowers/plans/2026-07-13-stir-dealer-direction-poc-results.md`, then:

```bash
git add docs/superpowers/plans/2026-07-13-stir-dealer-direction-poc-results.md
git commit -m "docs(stir-flow): POC backfill results for 2026-07-10"
```

---

## Deferred (explicitly out of POC scope, per spec section 10)

- `full` calibration mode (month-long DispJNS + dealer-charge distribution with pricing) — `run_calibration` raises NotImplementedError for it; follow-up after POC runtime is measured.
- Near-expiry futures tick halving.
- Seasoned-leg fixings patch (07/03 holiday gap) — such units land as UNKNOWN with PRICING_ERROR flags.
- Dashboard page, SR3 mapping, imbalance, event study, live 15-min loop.

## Self-Review Notes

- Spec coverage: sections 2 (Task 3), 3-4 (Task 4), 5 (Task 5), 6 (Tasks 6-7), 7 (Task 2), 8 (Tasks 8-9), 9 (golden tests in Tasks 4-5). Section 6's full-month DispJNS/dealer-charge calibration is deliberately deferred (ticks-only default) — flagged above and printed by the CLI, not silent.
- Type consistency: `Unit`, `LegPricing`, `TickStats`, `DirectionResult`, `ConfidenceDecision` signatures pinned in Interfaces blocks; `classify_units` consumes exactly those.
- Golden numbers traceable to the validated 07/10 POC run (variant_pricing_results.json) and the user's hand calcs.
