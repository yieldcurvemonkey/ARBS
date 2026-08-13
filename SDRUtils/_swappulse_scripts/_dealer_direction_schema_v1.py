"""Materialised dealer-direction tables — DDL and the table-name constants.

Direction cannot be computed at request time. It needs ``rateslib``, the local
Citi Velocity minute curve store (a DuckDB/parquet cache the web tier has no
access to) and ~180 s of CPU per tape day for repricing plus key-rate risk. So
a batch job materialises it here and the front end reads it.

FOUR TABLES, AND WHY FOUR
=========================

Two are expensive to produce and two are cheap, and the split is drawn on
exactly that line so that a bug in the cheap half never costs a re-run of the
expensive half.

``arbs_dd_unit_v1``
    One row per **unit** — the same object as one row of
    ``arbs_usd_swap_tape_display_v3``. Carries the call, the three clocks, the
    exclusion reason where there is one, and the provenance. Expensive.

``arbs_dd_unit_bucket_v1``
    One row per (unit, tenor bucket), signed. This is
    ``ladder.unit_ladder_rows()`` rolled up to ``indicator``'s ten reporting
    buckets. The ladder and the daily indicator are both *pure functions* of
    this table, so an aggregation or z-score defect is repaired by
    re-aggregating in minutes rather than repricing for a day. Expensive.

``arbs_dd_coverage_v1``
    Per (visibility date, bucket, venue class, series, **reason**) the unit
    count and the DV01 behind it, where ``reason`` is either ``IN_LADDER`` or
    an exclusion code. Two jobs in one table: ``indicator.build`` *requires*
    coverage as ``dv01_kept`` **and** ``dv01_total`` (a ratio cannot be
    re-aggregated), and the front end needs the exclusion breakdown by DV01
    share. Both roll up from the same rows, so they cannot disagree. Cheap.

``arbs_dd_ladder_v1``
    The published indicator cell, one row per
    (bucket_space, bucket_key, visibility_date, venue_class, series). Its
    columns mirror ``indicator.CELL_COLUMNS`` **verbatim**. Cheap, and
    rebuilt wholesale on every run — see REBUILD WHOLESALE below.

AND TWO MORE, ADDED LATER: THE INTRADAY MID GRID
================================================

``arbs_dd_curve_mid_v1``
    One row per (rate_index, tenor_label, minute) — the model **par rate**, so
    a print can be drawn against where the market actually was. It exists for
    the same reason the four above do: the Citi minute curve store is local
    parquet/DuckDB and the web tier cannot reach it.

    **The mid comes from ``midprice.SessionBranchPricer.price_leg``, the same
    object that priced the deviation behind every direction annotation.** A
    second, independent discount-factor path would let the chart and the
    annotations drawn on it disagree with nothing to say so. Measured on 890
    single-leg ``RATE_VS_MID`` prints over three days: the grid reproduces
    ``fixed_rate*100 - deviation_bps/100`` to a **max of 2.7e-13 bp** at
    1-minute spacing. That is not "close"; it is the same number.

``arbs_dd_curve_mid_day_v1``
    One row per (grid_date, rate_index): how many minutes the store partition
    held, how many were served, how many were refused, and how many grid rows
    resulted. The completion check for the grid is an **equality**
    (``n_rows == n_tenors * minutes_served``), and the denominator is a
    property of the curve store, which the database cannot see. Storing it is
    what lets ``verify`` run against the database alone — and what stops
    "exit code 0" from standing in for "the day produced its rows".

WHAT IS NOT STORED: THE 28 KRD PILLARS
======================================

``krd.krd_frame`` produces one row per (unit × KRD pillar) over 28 pillars.
Across the tape that is tens of millions of rows. It is **not** materialised
here, deliberately:

* no web view reads a pillar. The panel is on the ten ``TENOR10`` buckets and
  the per-trade drill-down is a ten-bucket profile;
* the roll-up is **not lossy for anything published**. ``ladder.aggregate``,
  ``indicator.daily_levels`` and every column of ``arbs_dd_ladder_v1`` are
  computed from the ``TENOR10`` rows, so ``arbs_dd_unit_bucket_v1`` is a
  sufficient statistic for the whole published surface;
* the pillar frame is written un-lossy to the parquet stage cache on ``D:``
  by the runner anyway, which is where any future pillar question would be
  answered — and it is a local file, which the web tier could not read.

Storing 65 M rows that no consumer reads, behind a connection pooler, to
protect against a re-derivation that is already protected, is a cost with no
buyer. If a pillar-grained consumer ever appears, the parquet is the source
and a fifth table is an additive change.

THE JOIN KEY IS ``package_id``, NOT ``unit_key``
================================================

Measured on five days spanning the whole tape (``scratch/ddfe02_*``): the
display view and ``universe.unit_frame`` agree on the *grain* exactly and on
only **21.7–29.3% of the keys**. ``universe.py:614`` sets
``unit_key = trade_id`` for a single-leg unit, while the view keys that same
row by its ``package_id`` — and a single-leg print that still carries a
package id (``MATCHED_MATURITY_…``, ``SPREADOVER_…``) is most of the tape.
On ``package_id`` the join is **100.0000%**, both directions, every day tried.

Both keys are stored. ``unit_key`` is the backend's identity and every
``dealer_direction`` frame is keyed on it, so dropping it would break the
audit trail back to the ladder. ``package_id`` is what the front end joins.
Deriving one from the other at read time would put the ``n_legs <= 1`` branch
in a SQL ``CASE`` on the web tier, which is where it would be got wrong.

THE REFUSAL CANNOT LIVE HERE
============================

``indicator`` refuses a cross-bucket *level* comparison structurally: the
level column is named for its bucket (``delta_dv01__5_7Y``), so a naive
concat is a NaN block diagonal. A relational table cannot do that — buckets
are rows, and ``SELECT bucket_key, delta_dv01 … WHERE visibility_date = $1``
is one line of SQL. **The enforcement point is therefore the API route**, and
it is asserted by a route test:

* the level endpoint accepts exactly one ``bucket`` and returns one bucket's
  series;
* the all-buckets endpoint returns ``z``/percentile and **no level-named
  key**.

The measurement that makes this necessary: DV01 retention runs 0.761 at 0-1Y
down to 0.495 at 15-20Y, a 1.54x cross-bucket scaling distortion, because the
packages the classifier cannot orient are not a random sample. ``z`` is
exactly invariant to a constant retention factor and is the one
cross-bucket-safe view.

REBUILD WHOLESALE
=================

``arbs_dd_ladder_v1`` must be rebuilt over the **whole** history on every
run, never appended to. ``indicator``'s adjusted level divides by
``mean(coverage)`` over the full sample and its ``z`` is a trailing-250
statistic, so extending history restates earlier cells. Appending would leave
a table whose old rows were computed against a shorter sample than its new
ones, with nothing to say so.

``arbs_dd_unit_v1`` / ``arbs_dd_unit_bucket_v1`` / ``arbs_dd_coverage_v1`` are
per-day and are delete-and-rewritten one ``as_of_date`` at a time.

NAMING
======

``_v1`` is this feature's own version, not the tape's. The tape generation it
was built from is carried explicitly in ``tape_generation`` on every unit row
(and hashed into ``code_vintage``), so a reader can tell without decoding a
hash. Index names carry the version for the reason ``_tape_tables.py:17-21``
records: index names are schema-global, so a v2 name on a v1 table silently
no-ops and leaves the table unindexed with nothing raised.
"""
from __future__ import annotations

from ._tape_tables import TAPE_GENERATION

#: This feature's own version. Deliberately a constant, not an env var, for
#: the reason `tape-tables.ts` gives: a missing env var must never silently
#: select the wrong generation. Mirrored in the dashboard at
#: `src/lib/dealer-direction-tables.ts` and asserted equal by a test there.
DD_GENERATION = "v1"

IDX_INFIX = DD_GENERATION


def _t(base: str) -> str:
    return f"arbs_dd_{base}_{DD_GENERATION}"


UNIT_TABLE = _t("unit")
UNIT_BUCKET_TABLE = _t("unit_bucket")
COVERAGE_TABLE = _t("coverage")
LADDER_TABLE = _t("ladder")
RUNS_TABLE = _t("runs")
CURVE_MID_TABLE = _t("curve_mid")
CURVE_MID_DAY_TABLE = _t("curve_mid_day")

#: The tape generation these rows were built from. Written to every unit row.
SOURCE_TAPE_GENERATION = TAPE_GENERATION

#: ``reason`` value for a unit that reached the ladder. Mirrors
#: ``provenance.IN_LADDER`` -- imported rather than re-spelled would create an
#: import cycle from a schema module into the analytics package, so it is
#: pinned here and asserted equal in the tests.
IN_LADDER = "IN_LADDER"


DDL_STATEMENTS = [
    # ---------------------------------------------------------------- units
    f"""
CREATE TABLE IF NOT EXISTS {UNIT_TABLE} (
    package_id              TEXT PRIMARY KEY,
    unit_key                TEXT NOT NULL,
    as_of_date              DATE NOT NULL,

    -- three clocks, always. Every aggregation stamps on `visibility_*`;
    -- execution time is lookahead and is carried for transparency only.
    execution_timestamp     TIMESTAMPTZ,
    event_timestamp         TIMESTAMPTZ,
    visibility_timestamp    TIMESTAMPTZ,
    visibility_date         DATE,
    visibility_source       TEXT,
    pricing_timestamp       TIMESTAMPTZ,
    pricing_clock_field     TEXT,
    report_lag_seconds      DOUBLE PRECISION,
    visibility_lag_seconds  DOUBLE PRECISION,

    -- the call. `p` is p(customer paid fixed) = p(dealer RECEIVED fixed).
    -- NULL `p` is a real state (a recovered PKG-N has a sign but no fitted
    -- tau); it must never be read as 0.5 or as 1.0.
    dealer_direction        TEXT NOT NULL,
    dealer_sign             SMALLINT,
    p                       DOUBLE PRECISION,
    signed_weight           DOUBLE PRECISION,
    rule                    TEXT,
    deviation_bps           DOUBLE PRECISION,
    tau_bps                 DOUBLE PRECISION,
    tau_bucket              TEXT,
    mid_bias_bps            DOUBLE PRECISION,
    in_dead_zone            BOOLEAN,
    exclusion_reason        TEXT,
    exclusion_detail        TEXT,

    -- unit shape
    kind                    TEXT,
    n_legs                  SMALLINT,
    -- STANDARD | IMM | FOMC | MATCHED_MATURITY | INVOICE_SWAP | MAC.
    -- Carried in its own column, not only inside `tau_bucket`, because FOMC
    -- is the one value a consumer has to be able to filter on: a
    -- meeting-to-meeting swap is repriced against a curve with no discrete
    -- meeting steps, so its deviation is dominated by that model error rather
    -- than by bid-offer. Measured on 2024-07-01..2024-08-09, median
    -- |deviation| against everything else on the same days:
    --   FED_FUNDS  1.994 bp vs 0.295 bp   (6.8x)
    --   SOFR       0.697 bp vs 0.174 bp   (4.0x)
    -- and the per-meeting median flips sign by 1-2 bp on BOTH indices
    -- together -- which is what rules out a rate-index routing fault.
    special_tenor_type      TEXT,
    rate_index              TEXT,
    venue_class             TEXT,
    series                  TEXT,
    is_lifecycle            BOOLEAN,
    is_block                BOOLEAN,
    is_capped               BOOLEAN,

    -- risk. `dv01_proxy` is the annuity proxy and is present even on an
    -- excluded unit, which is what makes the coverage denominator knowable.
    -- The tape's own `risk` column is never summed anywhere (55 legs carry
    -- the spec's 1e20 "value not available" sentinel and dominate every
    -- aggregate).
    total_dv01_if_received  DOUBLE PRECISION,
    total_delta_dv01        DOUBLE PRECISION,
    structure_dv01          DOUBLE PRECISION,
    dv01_proxy              DOUBLE PRECISION,

    -- provenance
    curve_name              TEXT,
    curve_timestamp         TIMESTAMPTZ,
    snapshot_lag_seconds    DOUBLE PRECISION,
    snapshot_policy         TEXT,
    curve_source            TEXT,
    notional_imputed        BOOLEAN,
    notional_impute_factor  DOUBLE PRECISION,
    risk_sanity_reason      TEXT,
    tape_generation         TEXT NOT NULL,
    code_vintage            TEXT NOT NULL,
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_unit_asof "
    f"ON {UNIT_TABLE} (as_of_date)",
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_unit_vis "
    f"ON {UNIT_TABLE} (visibility_date)",
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_unit_key "
    f"ON {UNIT_TABLE} (unit_key)",
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_unit_dir "
    f"ON {UNIT_TABLE} (dealer_direction, as_of_date)",
    # Partial: the exclusion breakdown only ever scans the excluded rows, and
    # ~58% of the table has a NULL reason.
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_unit_excl "
    f"ON {UNIT_TABLE} (exclusion_reason, as_of_date) "
    f"WHERE exclusion_reason IS NOT NULL",
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_unit_vintage "
    f"ON {UNIT_TABLE} (code_vintage)",
    # Added after the first backfill: see the column comment above. ALTER
    # rather than a new file, per the convention in _stir_flow_schema_v1.py.
    f"ALTER TABLE {UNIT_TABLE} ADD COLUMN IF NOT EXISTS "
    f"special_tenor_type TEXT",
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_unit_stt "
    f"ON {UNIT_TABLE} (special_tenor_type, as_of_date) "
    f"WHERE special_tenor_type IS DISTINCT FROM 'STANDARD'",

    # --------------------------------------------------------- unit x bucket
    f"""
CREATE TABLE IF NOT EXISTS {UNIT_BUCKET_TABLE} (
    package_id              TEXT NOT NULL,
    bucket_key              TEXT NOT NULL,
    unit_key                TEXT NOT NULL,
    as_of_date              DATE NOT NULL,
    visibility_date         DATE NOT NULL,
    venue_class             TEXT NOT NULL,
    series                  TEXT NOT NULL,
    bucket_space            TEXT NOT NULL,
    dv01_if_received        DOUBLE PRECISION NOT NULL,
    delta_dv01              DOUBLE PRECISION NOT NULL,
    signed_weight           DOUBLE PRECISION,
    code_vintage            TEXT NOT NULL,
    PRIMARY KEY (package_id, bucket_key)
)""",
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_ub_asof "
    f"ON {UNIT_BUCKET_TABLE} (as_of_date)",
    # Equality columns first, then the range column, per the composite-index
    # rule: every aggregate read is
    #   WHERE venue_class = $1 AND series = $2 AND bucket_key = $3
    #     AND visibility_date BETWEEN $4 AND $5
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_ub_cell "
    f"ON {UNIT_BUCKET_TABLE} (venue_class, series, bucket_key, visibility_date)",

    # ------------------------------------------------------------- coverage
    f"""
CREATE TABLE IF NOT EXISTS {COVERAGE_TABLE} (
    visibility_date         DATE NOT NULL,
    bucket_key              TEXT NOT NULL,
    venue_class             TEXT NOT NULL,
    series                  TEXT NOT NULL,
    reason                  TEXT NOT NULL,
    n_units                 INTEGER NOT NULL,
    dv01                    DOUBLE PRECISION NOT NULL,
    as_of_date              DATE NOT NULL,
    code_vintage            TEXT NOT NULL,
    PRIMARY KEY (visibility_date, bucket_key, venue_class, series, reason)
)""",
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_cov_asof "
    f"ON {COVERAGE_TABLE} (as_of_date)",
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_cov_cell "
    f"ON {COVERAGE_TABLE} (venue_class, series, bucket_key, visibility_date)",

    # --------------------------------------------------------------- ladder
    # Column-for-column `indicator.CELL_COLUMNS` plus the two coverage
    # columns `build` appends. Renaming anything at this seam is where a
    # translation bug would live, so nothing is renamed.
    f"""
CREATE TABLE IF NOT EXISTS {LADDER_TABLE} (
    bucket_space                    TEXT NOT NULL,
    bucket_key                      TEXT NOT NULL,
    visibility_date                 DATE NOT NULL,
    venue_class                     TEXT NOT NULL,
    series                          TEXT NOT NULL,
    observed                        BOOLEAN NOT NULL,
    delta_dv01                      DOUBLE PRECISION,
    delta_dv01_cov_adj              DOUBLE PRECISION,
    abs_dv01                        DOUBLE PRECISION,
    n_units                         INTEGER,
    mean_abs_signed_weight          DOUBLE PRECISION,
    z_raw                           DOUBLE PRECISION,
    z_cov_adj                       DOUBLE PRECISION,
    pct_raw                         DOUBLE PRECISION,
    z_n_obs                         INTEGER,
    coverage_frac                   DOUBLE PRECISION,
    coverage_smooth                 DOUBLE PRECISION,
    coverage_drift_flag             BOOLEAN,
    coverage_trend_pp_per_yr        DOUBLE PRECISION,
    coverage_drift_source           TEXT,
    frac_dv01_block                 DOUBLE PRECISION,
    frac_dv01_capped                DOUBLE PRECISION,
    frac_dv01_dead_zone             DOUBLE PRECISION,
    frac_dv01_visibility_measured   DOUBLE PRECISION,
    code_vintage                    TEXT,
    primary_level_basis             TEXT NOT NULL,
    coverage_dv01_kept              DOUBLE PRECISION,
    coverage_dv01_total             DOUBLE PRECISION,
    computed_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (bucket_space, bucket_key, visibility_date, venue_class, series)
)""",
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_lad_series "
    f"ON {LADDER_TABLE} (venue_class, series, bucket_key, visibility_date)",
    # The cross-bucket z view reads one date across all buckets.
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_lad_date "
    f"ON {LADDER_TABLE} (visibility_date, venue_class, series)",

    # ----------------------------------------------------------------- runs
    # An audit row per (day, stage). "exit code 0" is not evidence a day
    # produced anything, so the runner records what it actually wrote and the
    # completion check reads THIS, not the process's status.
    f"""
CREATE TABLE IF NOT EXISTS {RUNS_TABLE} (
    run_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    as_of_date      DATE NOT NULL,
    stage           TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    status          TEXT NOT NULL,
    n_legs          INTEGER,
    n_units         INTEGER,
    n_units_kept    INTEGER,
    n_unit_rows     INTEGER,
    n_coverage_rows INTEGER,
    seconds         DOUBLE PRECISION,
    code_vintage    TEXT,
    error_text      TEXT
)""",
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_runs_day "
    f"ON {RUNS_TABLE} (as_of_date, stage)",

    # ----------------------------------------------------- intraday mid grid
    # The model par rate per (index, tenor, minute), so a print can be drawn
    # against where the market actually was. Produced by
    # `backfill_curve_mids.py` through `midprice.SessionBranchPricer` -- the
    # same pricer the direction inference uses, deliberately, so the chart and
    # the annotations on it cannot disagree.
    f"""
CREATE TABLE IF NOT EXISTS {CURVE_MID_TABLE} (
    -- The ET CALENDAR DATE of the curve-store partition the minute came from.
    -- NOT `as_of_date`, and the difference is not cosmetic: the tape's
    -- `as_of_date` is a UTC date, so ~4% of a tape day's prints (ET hours
    -- 20-23) were executed the PREVIOUS ET evening. Keying the grid on
    -- `as_of_date` puts those prints a whole day away from their own minutes;
    -- every "no grid point within 30 minutes" case in the sizing probe was
    -- this artifact, and all of them disappeared on the ET date.
    grid_date               DATE NOT NULL,
    rate_index              TEXT NOT NULL,
    -- A standard-tenor label ('10Y'), NOT the print's own tenor. The tape's
    -- `tenor_label` is a bucket -- '10Y' spans 3,468-3,830 days over 273
    -- distinct offsets -- so `maturity_date` below is what says which
    -- instrument this row actually is.
    tenor_label             TEXT NOT NULL,

    -- THE INSTANT ASKED FOR, on a whole minute, tz-aware. This is the join
    -- key: `snapshot.snap_instant` floors to the minute and steps back one,
    -- and `arbs_dd_unit_v1.curve_timestamp` already IS that instant
    -- (973,305/973,305 rows carry second = 0). So an annotated print joins to
    -- its own mid by EQUALITY on this column. Joining at the print's raw
    -- execution minute silently returns the minute AFTER the one the
    -- annotation priced at, and the bit-exactness is gone.
    ts                      TIMESTAMPTZ NOT NULL,

    -- ...and the instant actually SERVED, with the realised staleness. A row
    -- served from a stale snapshot must SAY so: a chart that draws a
    -- 90-minute-old mid as if it were live is the failure these three columns
    -- exist to prevent. `ts` + `snapshot_lag_seconds` reconstructs
    -- `served_ts` exactly, so nothing is inferred at read time.
    -- `snapshot_policy` is STRICT_1MIN_IN_SESSION or ASOF_2H_OUT_OF_SESSION;
    -- a lag of 90 s means something different under each.
    served_ts               TIMESTAMPTZ,
    snapshot_lag_seconds    DOUBLE PRECISION,
    snapshot_policy         TEXT NOT NULL,

    -- The par (fair) rate in PERCENT -- `IRSwapValue.RATE` on a ONE-leg query
    -- is percent; two- and three-leg queries return bp. NOT NULL because a
    -- non-finite mark on a curve that was served is a pricing defect, and the
    -- runner fails the day rather than writing a hole that reads as a quiet
    -- market.
    mid_pct                 DOUBLE PRECISION NOT NULL,
    pv01                    DOUBLE PRECISION,

    -- The instrument, stored rather than implied. `effective_date` is
    -- `calendar_advance(curve.reference_date(), '2b')` on `nyc` -- the rule
    -- `RLIRSwapCurve.build_irswap(fwd="0D")` already uses in this repo, which
    -- reproduces the tape's own modal spot on 598/629 days (99.3% by print
    -- count; the residue is IMM roll weeks, which have no modal convention).
    -- Writing both dates makes the row auditable instead of folklore, and is
    -- what lets a reader tell a bucket-width difference from a pipeline
    -- error.
    effective_date          DATE NOT NULL,
    maturity_date           DATE NOT NULL,

    curve_name              TEXT NOT NULL,
    curve_source            TEXT NOT NULL,
    code_vintage            TEXT NOT NULL,
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Matches the read: one index, one tenor, a time range. A day's series
    -- for one tenor is then a ~1,300-row btree range scan.
    PRIMARY KEY (rate_index, tenor_label, ts)
)""",
    # "one day, one curve, one tenor, ordered by time" -- equality columns
    # first, then the range column, per the composite-index rule used above.
    f"CREATE INDEX IF NOT EXISTS idx_dd_{IDX_INFIX}_mid_day "
    f"ON {CURVE_MID_TABLE} (grid_date, rate_index, tenor_label, ts)",

    # ------------------------------------------- mid grid, per-day accounting
    # Citi publishes nothing between 23:00 and 00:59 ET, so no grid row exists
    # for a print in those two hours. THE CONSUMER CARRIES THE LAST POINT
    # FORWARD -- it is the closest of the available choices, not an exact one,
    # and the difference was measured rather than assumed.
    #
    # The direction pipeline serves an hour-00 print from an
    # ASOF_2H_OUT_OF_SESSION curve, which IS the previous 22:59 snapshot, so
    # the CURVE matches. The INSTRUMENT does not: at 00:xx ET the served
    # curve's reference date is still the previous business day, so the grid's
    # spot-start point is one business day behind the print's own effective
    # date. Decomposed on 11 such prints: repricing each print's OWN dates at
    # its own instant reproduces the annotation to 1.3e-13 bp, while the grid's
    # constant-maturity point disagrees by <= 0.42 bp under LOCF (<= 1.20 bp if
    # the consumer instead joins forward to the next session's 01:00 point).
    #
    # So: LOCF for line continuity, and expect up to ~0.4 bp of disagreement
    # against the annotation on the ~1% of prints in ET hour 00. Interpolating
    # across the hole invents a market that was not publishing; drawing a gap
    # loses the print entirely. Both are worse.
    f"""
CREATE TABLE IF NOT EXISTS {CURVE_MID_DAY_TABLE} (
    grid_date               DATE NOT NULL,
    rate_index              TEXT NOT NULL,
    curve_name              TEXT NOT NULL,

    -- The DENOMINATOR, and it is a property of the curve store, which the
    -- database cannot see. `partition_minutes` is how many distinct minutes
    -- the store partition held; `minutes_served` how many the snapshot policy
    -- answered; `minutes_missed` the rest, SKIPPED rather than fabricated.
    -- The completion check is the equality
    --     n_rows = n_tenors * minutes_served
    -- which is exact, so it is used instead of "non-zero". It is NOT checked
    -- against 1,320: truncated sessions are real (min 911 minutes observed)
    -- and interior holes exist, so `session_expected_minutes` is carried
    -- beside it as the soft, reportable comparison.
    partition_minutes       INTEGER NOT NULL,
    session_expected_minutes INTEGER,
    minutes_served          INTEGER NOT NULL,
    minutes_missed          INTEGER NOT NULL,
    n_rows                  INTEGER NOT NULL,
    n_tenors                SMALLINT NOT NULL,
    -- How many distinct curve reference dates the day's minutes carried.
    -- Normally 1. More than one means the spot date moved inside the day, and
    -- the instrument therefore changed inside the day -- a reportable fact,
    -- not an error, and the per-row dates are what resolve it.
    n_reference_dates       SMALLINT,
    seconds                 DOUBLE PRECISION,
    status                  TEXT NOT NULL,
    error_text              TEXT,
    code_vintage            TEXT,
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (grid_date, rate_index)
)""",
]


def ensure_schema(conn) -> None:
    """Create the six tables and the runs ledger. Idempotent."""
    with conn.cursor() as cur:
        for stmt in DDL_STATEMENTS:
            cur.execute(stmt)
    conn.commit()
