"""Schema DDL for the USD swap tape v2 ingest.

Creates three tables and one display view:

- ``arbs_usd_swap_tape_packages_v1`` — per-package aggregates.
- ``arbs_usd_swap_tape_legs_v1`` — per-trade enriched legs, FK to packages.
- ``arbs_usd_swap_tape_ingestion_runs_v1`` — observability row per ingest.
- ``arbs_usd_swap_tape_display_v1`` — view joining packages + legs (jsonb_agg)
  + manual-link metadata from the pre-existing ``arbs_usd_swap_manual_links_v2``.

Patterned after ``SCHEMA_SQL`` in ``ingest_usdswaps.py`` but expanded to
carry every TradeTape-enriched field used by the dashboard.
"""
from __future__ import annotations


PACKAGES_TABLE = "arbs_usd_swap_tape_packages_v1"
LEGS_TABLE = "arbs_usd_swap_tape_legs_v1"
RUNS_TABLE = "arbs_usd_swap_tape_ingestion_runs_v1"
DISPLAY_VIEW = "arbs_usd_swap_tape_display_v1"
MANUAL_LINKS_TABLE = "arbs_usd_swap_manual_links_v2"


TAPE_SCHEMA_SQL = f"""
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Packages table: per-package aggregates (rolled up from legs)
CREATE TABLE IF NOT EXISTS {PACKAGES_TABLE} (
    package_id TEXT PRIMARY KEY,
    manual_link_id UUID,
    as_of_date DATE NOT NULL,
    execution_start TIMESTAMPTZ NOT NULL,
    execution_end TIMESTAMPTZ NOT NULL,
    package_structure TEXT,
    package_type TEXT,
    package_tenors TEXT,
    n_package_legs INTEGER,
    legs_count INTEGER NOT NULL,
    total_notional NUMERIC,
    gross_notional NUMERIC,
    total_risk NUMERIC,
    gross_risk NUMERIC,
    weighted_fixed_rate NUMERIC,
    min_fixed_rate NUMERIC,
    max_fixed_rate NUMERIC,
    has_spread BOOLEAN,
    package_transaction_spread NUMERIC,
    package_transaction_price NUMERIC,
    package_transaction_price_currency TEXT,
    rate_index_clean TEXT,
    venue TEXT,
    ccp TEXT,
    execution_session TEXT,
    is_new_risk BOOLEAN,
    is_unwind BOOLEAN,
    is_compression_any BOOLEAN,
    is_ufro_any BOOLEAN,
    is_block_any BOOLEAN,
    is_capped_any BOOLEAN,
    is_off_date_any BOOLEAN,
    is_termination_any BOOLEAN,
    is_novation_any BOOLEAN,
    is_reset_optimization_any BOOLEAN,
    is_clearing_termination_any BOOLEAN,
    is_correction_any BOOLEAN,
    lifecycle_mix JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    is_fomc_dated BOOLEAN,
    fomc_meeting_label TEXT,
    cluster_id TEXT,
    cluster_size INTEGER,
    tape_label TEXT,
    package_metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Legs table: per-trade enrichment
CREATE TABLE IF NOT EXISTS {LEGS_TABLE} (
    trade_id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES {PACKAGES_TABLE}(package_id),
    leg_order INTEGER NOT NULL,
    as_of_date DATE NOT NULL,
    execution_timestamp TIMESTAMPTZ NOT NULL,
    execution_session TEXT,
    execution_hour_et INTEGER,
    tenor_years NUMERIC,
    tenor_label TEXT,
    tenor_display TEXT,
    forward_start_years NUMERIC,
    forward_label TEXT,
    forward_bucket TEXT,
    effective_date DATE,
    expiration_date DATE,
    notional NUMERIC,
    notional_currency TEXT,
    risk NUMERIC,
    fixed_rate NUMERIC,
    other_payment_amount NUMERIC,
    other_payment_currency TEXT,
    trade_type TEXT,
    rate_index_clean TEXT,
    venue TEXT,
    ccp TEXT,
    platform_identifier TEXT,
    tape_label TEXT,
    leg_tape_label TEXT,
    upi_reset_freq TEXT,
    upi_notional_schedule TEXT,
    upi_delivery_type TEXT,
    is_new_risk BOOLEAN,
    is_unwind BOOLEAN,
    is_compression BOOLEAN,
    is_compression_spec BOOLEAN,
    is_reset_optimization BOOLEAN,
    is_novation BOOLEAN,
    is_novation_born BOOLEAN,
    is_novation_terminated BOOLEAN,
    is_exercise_born BOOLEAN,
    is_clearing_termination BOOLEAN,
    lifecycle_type TEXT,
    lc_n_events INTEGER,
    lc_status TEXT,
    is_ufro BOOLEAN,
    is_off_market BOOLEAN,
    is_capped BOOLEAN,
    is_block BOOLEAN,
    is_off_date BOOLEAN,
    is_mac BOOLEAN,
    is_spreadover BOOLEAN,
    is_asset_swap BOOLEAN,
    is_non_standard_term BOOLEAN,
    quality_flags TEXT[],
    is_fomc_dated BOOLEAN,
    fomc_meeting_label TEXT,
    fomc_proximity TEXT,
    is_month_end BOOLEAN,
    is_quarter_end BOOLEAN,
    cluster_id TEXT,
    cluster_size INTEGER,
    is_multi_meeting_cluster BOOLEAN,
    xd_status TEXT,
    xd_n_events INTEGER,
    xd_notional_pct_remaining NUMERIC,
    xd_is_terminated BOOLEAN,
    xd_has_partial_unwind BOOLEAN,
    manual_link_id UUID,
    enrichment_metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ingestion runs observability table
CREATE TABLE IF NOT EXISTS {RUNS_TABLE} (
    run_id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    as_of_date DATE,
    rows_in INTEGER,
    rows_out INTEGER,
    failed_rows JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'running',
    error_text TEXT,
    cache_hit BOOLEAN
);

-- Indexes per design §4.2 / §4.3
CREATE INDEX IF NOT EXISTS idx_tape_v1_packages_date ON {PACKAGES_TABLE}(as_of_date, execution_start DESC);
CREATE INDEX IF NOT EXISTS idx_tape_v1_packages_type ON {PACKAGES_TABLE}(package_type, as_of_date);
CREATE INDEX IF NOT EXISTS idx_tape_v1_packages_cluster ON {PACKAGES_TABLE}(cluster_id);
CREATE INDEX IF NOT EXISTS idx_tape_v1_packages_fomc ON {PACKAGES_TABLE}(fomc_meeting_label);
CREATE INDEX IF NOT EXISTS idx_tape_v1_packages_metrics_gin ON {PACKAGES_TABLE} USING GIN (package_metrics);

-- Additive migrations for columns added after initial rollout. Safe to run
-- repeatedly because ``ADD COLUMN IF NOT EXISTS`` is idempotent.
ALTER TABLE {LEGS_TABLE} ADD COLUMN IF NOT EXISTS leg_tape_label TEXT;
ALTER TABLE {LEGS_TABLE} ADD COLUMN IF NOT EXISTS other_payment_amount NUMERIC;
ALTER TABLE {LEGS_TABLE} ADD COLUMN IF NOT EXISTS other_payment_currency TEXT;
ALTER TABLE {PACKAGES_TABLE} ADD COLUMN IF NOT EXISTS package_transaction_price NUMERIC;
ALTER TABLE {PACKAGES_TABLE} ADD COLUMN IF NOT EXISTS package_transaction_price_currency TEXT;

CREATE INDEX IF NOT EXISTS idx_tape_v1_legs_package ON {LEGS_TABLE}(package_id);
CREATE INDEX IF NOT EXISTS idx_tape_v1_legs_exec ON {LEGS_TABLE}(execution_timestamp);
CREATE INDEX IF NOT EXISTS idx_tape_v1_legs_lifecycle ON {LEGS_TABLE}(lifecycle_type);
CREATE INDEX IF NOT EXISTS idx_tape_v1_legs_cluster ON {LEGS_TABLE}(cluster_id);
CREATE INDEX IF NOT EXISTS idx_tape_v1_legs_metrics_gin ON {LEGS_TABLE} USING GIN (enrichment_metrics);
CREATE INDEX IF NOT EXISTS idx_tape_v1_legs_flags_gin ON {LEGS_TABLE} USING GIN (quality_flags);

-- Display view: packages with jsonb_agg of legs + manual-link metadata
--
-- Dropped-and-recreated (rather than CREATE OR REPLACE) because Postgres
-- CREATE OR REPLACE VIEW refuses to rename or reorder existing view columns
-- — it can only append new columns at the end of the SELECT list. When we
-- inserted package_transaction_price / _currency before rate_index_clean
-- (PR #257), existing deployments with the prior view shape would error:
--   cannot change name of view column "rate_index_clean"
--     to "package_transaction_price"
-- DROP + CREATE keeps migrations idempotent and order-agnostic.
DROP VIEW IF EXISTS {DISPLAY_VIEW};

CREATE VIEW {DISPLAY_VIEW} AS
SELECT
  p.package_id,
  p.manual_link_id,
  p.as_of_date,
  p.execution_start,
  p.execution_end,
  p.package_structure,
  p.package_type,
  p.package_tenors,
  p.n_package_legs,
  p.legs_count,
  p.total_notional,
  p.gross_notional,
  p.total_risk,
  p.gross_risk,
  p.weighted_fixed_rate,
  p.min_fixed_rate,
  p.max_fixed_rate,
  p.has_spread,
  p.package_transaction_spread,
  p.package_transaction_price,
  p.package_transaction_price_currency,
  p.rate_index_clean,
  p.venue,
  p.ccp,
  p.execution_session,
  p.is_new_risk,
  p.is_unwind,
  p.is_compression_any,
  p.is_ufro_any,
  p.is_block_any,
  p.is_capped_any,
  p.is_off_date_any,
  p.is_termination_any,
  p.is_novation_any,
  p.is_reset_optimization_any,
  p.is_clearing_termination_any,
  p.is_correction_any,
  p.lifecycle_mix,
  p.is_fomc_dated,
  p.fomc_meeting_label,
  p.cluster_id,
  p.cluster_size,
  p.tape_label,
  p.package_metrics,
  l.legs_json,
  ml.manual_package_id,
  ml.user_comment,
  ml.link_reason,
  ml.tags,
  ml.link_metrics,
  ml.created_by AS link_created_by,
  ml.created_at AS link_created_at
FROM {PACKAGES_TABLE} p
LEFT JOIN LATERAL (
    -- to_jsonb(l) serializes the whole row so we dodge the Postgres
    -- jsonb_build_object 100-arg limit (the tape legs table has >50
    -- hoisted columns).
    SELECT jsonb_agg(to_jsonb(l) ORDER BY l.leg_order) AS legs_json
    FROM {LEGS_TABLE} l
    WHERE l.package_id = p.package_id
) l ON TRUE
LEFT JOIN {MANUAL_LINKS_TABLE} ml
  ON ml.link_id = p.manual_link_id AND ml.is_active = TRUE;
"""


__all__ = [
    "TAPE_SCHEMA_SQL",
    "PACKAGES_TABLE",
    "LEGS_TABLE",
    "RUNS_TABLE",
    "DISPLAY_VIEW",
    "MANUAL_LINKS_TABLE",
]
