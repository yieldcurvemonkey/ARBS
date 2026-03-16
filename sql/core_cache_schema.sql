-- CORE Distributed Cache Schema
-- Run via Caching.supabase_schema.ensure_schema()

CREATE TABLE IF NOT EXISTS curve_snapshots (
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

CREATE INDEX IF NOT EXISTS idx_snapshots_tags
    ON curve_snapshots USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_snapshots_date
    ON curve_snapshots (curve_name, trading_date);

CREATE TABLE IF NOT EXISTS curve_intraday_blocks (
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
