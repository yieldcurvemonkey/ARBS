-- CORE Distributed Cache Schema
-- Run via Caching.supabase_schema.ensure_schema()

CREATE TABLE IF NOT EXISTS arbs_curve_snapshots_v1 (
    curve_name VARCHAR NOT NULL,
    timestamp_utc TIMESTAMPTZ NOT NULL,
    trading_date DATE NOT NULL,
    session_minute SMALLINT NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}',
    cfg_hash VARCHAR NOT NULL,
    reference_key VARCHAR NOT NULL,
    interpolation VARCHAR NOT NULL,
    source_variant VARCHAR NOT NULL DEFAULT '',
    node_dates DATE[] NOT NULL,
    discount_factors FLOAT8[] NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (curve_name, timestamp_utc)
);

-- Log-cubic spline knot sequence (rl.Curve's `t`) and endpoint conditions.
-- Nullable: absent for plain log-linear curves, and for rows written before
-- spline support, which reconstruct log-linear exactly as they always did.
-- Without these a spline-calibrated curve rebuilds as plain log-linear, and the
-- stored node DFs are the spline's solution rather than a valid log-linear
-- curve for the same market.
ALTER TABLE arbs_curve_snapshots_v1
    ADD COLUMN IF NOT EXISTS spline_knots DATE[];
ALTER TABLE arbs_curve_snapshots_v1
    ADD COLUMN IF NOT EXISTS spline_endpoints VARCHAR;

CREATE INDEX IF NOT EXISTS idx_snapshots_tags
    ON arbs_curve_snapshots_v1 USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_snapshots_date
    ON arbs_curve_snapshots_v1 (curve_name, trading_date);

CREATE TABLE IF NOT EXISTS arbs_curve_intraday_blocks_v1 (
    trading_date DATE NOT NULL,
    curve_name VARCHAR NOT NULL,
    data_format VARCHAR NOT NULL DEFAULT 'parquet_zstd',
    row_count INTEGER NOT NULL,
    payload BYTEA NOT NULL,
    sha256 VARCHAR NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trading_date, curve_name)
);

CREATE TABLE IF NOT EXISTS arbs_curve_analytics_blocks_v1 (
    trading_date DATE NOT NULL,
    curve_name VARCHAR NOT NULL,
    data_format VARCHAR NOT NULL DEFAULT 'parquet_zstd',
    row_count INTEGER NOT NULL,
    payload BYTEA NOT NULL,
    sha256 VARCHAR NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trading_date, curve_name)
);

CREATE TABLE IF NOT EXISTS arbs_kv_cache_v1 (
    cache_ns VARCHAR NOT NULL,
    cache_key VARCHAR NOT NULL,
    key_repr TEXT,
    payload BYTEA NOT NULL,
    serializer VARCHAR NOT NULL DEFAULT 'cloudpickle',
    ttl_seconds INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cache_ns, cache_key)
);

CREATE INDEX IF NOT EXISTS idx_kv_updated
    ON arbs_kv_cache_v1 (updated_at);

CREATE TABLE IF NOT EXISTS arbs_computed_timeseries_blocks_v1 (
    trading_date DATE NOT NULL,
    symbol VARCHAR NOT NULL,
    data_format VARCHAR NOT NULL DEFAULT 'parquet_zstd',
    row_count INTEGER NOT NULL,
    payload BYTEA NOT NULL,
    sha256 VARCHAR NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trading_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_computed_ts_symbol_date
    ON arbs_computed_timeseries_blocks_v1 (symbol, trading_date);

CREATE TABLE IF NOT EXISTS arbs_computed_timeseries_rows_v1 (
    symbol        VARCHAR   NOT NULL,
    trading_date  DATE      NOT NULL,
    column_name   VARCHAR   NOT NULL,
    value         FLOAT8    NOT NULL,
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, trading_date)
);

CREATE TABLE IF NOT EXISTS arbs_ustf_snapshot_blocks_v1 (
    trading_date DATE NOT NULL,
    symbol VARCHAR NOT NULL,
    data_format VARCHAR NOT NULL DEFAULT 'parquet_zstd',
    row_count INTEGER NOT NULL,
    payload BYTEA NOT NULL,
    sha256 VARCHAR NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trading_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_ustf_snapshot_symbol_date
    ON arbs_ustf_snapshot_blocks_v1 (symbol, trading_date);

CREATE TABLE IF NOT EXISTS arbs_ustf_basis_report_blocks_v1 (
    trading_date DATE NOT NULL,
    symbol VARCHAR NOT NULL,
    data_format VARCHAR NOT NULL DEFAULT 'parquet_zstd',
    row_count INTEGER NOT NULL,
    payload BYTEA NOT NULL,
    sha256 VARCHAR NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trading_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_ustf_basis_symbol_date
    ON arbs_ustf_basis_report_blocks_v1 (symbol, trading_date);

CREATE TABLE IF NOT EXISTS arbs_forex_factory_calendar_blocks_v1 (
    trading_date DATE NOT NULL,
    data_format VARCHAR NOT NULL DEFAULT 'parquet_zstd',
    row_count INTEGER NOT NULL,
    payload BYTEA NOT NULL,
    sha256 VARCHAR NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trading_date)
);

CREATE INDEX IF NOT EXISTS idx_forex_factory_calendar_date
    ON arbs_forex_factory_calendar_blocks_v1 (trading_date);

-- 2026-08-08: swaption vol cube day-blocks, for Caching.swaption_cube_store's L2
-- tier (Caching.supabase_swaption_cube_sync).
--
-- Same blob-block shape as the curve / USTF / computed-timeseries tables above:
-- one row per partition, the whole partition's parquet as BYTEA, with
-- data_format + row_count + sha256 so a reader can tell what it has without
-- decoding it. The key column is named `asset` rather than `symbol` because the
-- store's own vocabulary is `asset` — it partitions on
-- vol_raw/asset=<CCY>-SWAPTIONVOL-<PROVIDER>/ and `asset_for()` mints the name.
--
-- One difference in MEANING from arbs_curve_intraday_blocks_v1, even though the
-- columns are the same: a curve partition may legitimately hold several parquet
-- files (different timestamps within the day) and readers concat them, whereas a
-- cube partition is exactly ONE surface. SwaptionCubeStore.write_day raises
-- FileExistsError on a conflicting local write for that reason, and the sync
-- refuses a differing remote sha without an explicit rewrite so the property
-- survives the round trip.
CREATE TABLE IF NOT EXISTS arbs_swaption_cube_blocks_v1 (
    trading_date DATE NOT NULL,
    asset VARCHAR NOT NULL,
    data_format VARCHAR NOT NULL DEFAULT 'parquet_zstd',
    row_count INTEGER NOT NULL,
    payload BYTEA NOT NULL,
    sha256 VARCHAR NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trading_date, asset)
);

CREATE INDEX IF NOT EXISTS idx_swaption_cube_asset_date
    ON arbs_swaption_cube_blocks_v1 (asset, trading_date);
