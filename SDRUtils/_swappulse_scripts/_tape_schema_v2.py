"""Schema DDL for the USD swap tape **v2** ingest (Phase 4 cutover).

Creates three tables + one display view with ``_v2`` suffix, alongside the
v1 objects (see ``_tape_schema.py``). v1 is preserved frozen as the
rollback target per design §4.11 / implementation §4.11.

New columns over v1:
  - Economic-vs-Admin matrix columns: ``economic_class``,
    ``contributes_to_flow``, ``contributes_to_volume``, ``contributes_to_pnl``,
    ``contributes_to_pnl_as_delta``, ``on_p43``, ``economic_class_reason``.
  - Timestamp split (H1): ``original_execution_timestamp``,
    ``clearing_accepted_timestamp``.
  - Lifecycle quality (Phase 2): ``lc_n_events_economic``,
    ``lc_n_valuation_events``, ``lc_was_amended``, ``lc_was_null_filled``,
    ``lc_was_scheduled_amortization``, ``lc_has_economics_change``,
    ``state_machine_violation``, ``violation_reason``.
"""
from __future__ import annotations


PACKAGES_TABLE_V2 = "arbs_usd_swap_tape_packages_v2"
LEGS_TABLE_V2 = "arbs_usd_swap_tape_legs_v2"
RUNS_TABLE_V2 = "arbs_usd_swap_tape_ingestion_runs_v2"
DISPLAY_VIEW_V2 = "arbs_usd_swap_tape_display_v2"
MANUAL_LINKS_TABLE = "arbs_usd_swap_manual_links_v2"
OVERRIDES_TABLE_V2 = "arbs_usd_swap_tape_overrides_v2"
OVERRIDE_MEMBERS_TABLE_V2 = "arbs_usd_swap_tape_override_members_v2"
OVERRIDE_HISTORY_TABLE_V2 = "arbs_usd_swap_tape_override_history_v2"
NOTES_TABLE_V2 = "arbs_usd_swap_tape_notes_v2"


TAPE_SCHEMA_SQL_V2 = f"""
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Packages v2: per-package aggregates with matrix + quality columns
CREATE TABLE IF NOT EXISTS {PACKAGES_TABLE_V2} (
    package_id TEXT PRIMARY KEY,
    manual_link_id UUID,
    as_of_date DATE NOT NULL,
    execution_start TIMESTAMPTZ NOT NULL,
    execution_end TIMESTAMPTZ NOT NULL,
    original_execution_start TIMESTAMPTZ,
    clearing_accepted_start TIMESTAMPTZ,
    package_structure TEXT,
    package_type TEXT,
    package_indicator BOOLEAN,
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
    -- Phase 3 economic-class aggregate fields
    economic_class_primary TEXT,
    contributes_to_flow_any BOOLEAN,
    contributes_to_volume_any BOOLEAN,
    contributes_to_pnl_any BOOLEAN,
    on_p43_any BOOLEAN,
    state_machine_violation_any BOOLEAN,
    is_fomc_dated BOOLEAN,
    fomc_meeting_label TEXT,
    cluster_id TEXT,
    cluster_size INTEGER,
    tape_label TEXT,
    package_metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Legs v2: per-trade enrichment with matrix + quality columns
CREATE TABLE IF NOT EXISTS {LEGS_TABLE_V2} (
    trade_id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES {PACKAGES_TABLE_V2}(package_id),
    leg_order INTEGER NOT NULL,
    as_of_date DATE NOT NULL,
    execution_timestamp TIMESTAMPTZ NOT NULL,
    original_execution_timestamp TIMESTAMPTZ,
    clearing_accepted_timestamp TIMESTAMPTZ,
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
    notional_source TEXT,
    is_notional_capped BOOLEAN,
    risk NUMERIC,
    fixed_rate NUMERIC,
    other_payment_amount NUMERIC,
    other_payment_currency TEXT,
    trade_type TEXT,
    rate_index_clean TEXT,
    venue TEXT,
    ccp TEXT,
    platform_identifier TEXT,
    cleared TEXT,
    tape_label TEXT,
    leg_tape_label TEXT,
    -- Per-leg package economics. SPREADOVER_CURVE / MATCHED_MATURITY_FLY
    -- composites carry distinct per-leg PTS / PTP values; the package-level
    -- p.package_transaction_spread is only correct for true single-spread
    -- packages. The dashboard reads l.package_transaction_spread first
    -- and falls back to the package row when it's null.
    package_transaction_spread NUMERIC,
    package_transaction_price NUMERIC,
    package_transaction_price_currency TEXT,
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
    lc_n_events_economic INTEGER,
    lc_n_valuation_events INTEGER,
    lc_status TEXT,
    lc_was_amended BOOLEAN,
    lc_was_null_filled BOOLEAN,
    lc_was_scheduled_amortization BOOLEAN,
    lc_was_partially_terminated BOOLEAN,
    lc_has_partial_unwind BOOLEAN,
    lc_inception_notional NUMERIC,
    lc_current_notional NUMERIC,
    lc_has_past_effective BOOLEAN,
    lc_is_off_market_seasoned BOOLEAN,
    lc_days_seasoned INTEGER,
    lc_has_economics_change BOOLEAN,
    state_machine_violation BOOLEAN,
    violation_reason TEXT,
    economic_class TEXT,
    contributes_to_flow BOOLEAN,
    contributes_to_volume BOOLEAN,
    contributes_to_pnl BOOLEAN,
    contributes_to_pnl_as_delta BOOLEAN,
    on_p43 BOOLEAN,
    economic_class_reason TEXT,
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
    xd_was_partially_terminated BOOLEAN,
    xd_has_past_effective BOOLEAN,
    xd_is_off_market_seasoned BOOLEAN,
    xd_days_seasoned INTEGER,
    -- Phase 5 structural columns
    schedule_truncated BOOLEAN,
    schedule_row_count INTEGER,
    schedule_notional_series NUMERIC[],
    missing_required_fields TEXT[],
    cap_band_violation BOOLEAN,
    rc_timeline_json TEXT,
    other_payment_ufro NUMERIC,
    other_payment_uwin NUMERIC,
    other_payment_pexh NUMERIC,
    frequency_anomaly BOOLEAN,
    d2_missing BOOLEAN,
    manual_link_id UUID,
    enrichment_metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {RUNS_TABLE_V2} (
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

CREATE INDEX IF NOT EXISTS idx_tape_v2_packages_date ON {PACKAGES_TABLE_V2}(as_of_date, execution_start DESC);
CREATE INDEX IF NOT EXISTS idx_tape_v2_packages_orig_date ON {PACKAGES_TABLE_V2}(as_of_date, original_execution_start DESC);
-- Pagination scan: the main tape route does
-- ``WHERE d.execution_start < $cursor ORDER BY d.execution_start DESC
-- NULLS LAST LIMIT 201`` with no as_of_date filter, so the composite
-- index above can't lead. A single-column DESC NULLS LAST index turns
-- cursor pages into a fast btree range scan instead of a seq-scan on
-- the packages table.
--
-- NB: the route's ORDER BY MUST spell out ``DESC NULLS LAST``. Postgres
-- matches ORDER BY pathkeys to index ordering syntactically (NOT NULL is
-- not consulted), and plain ``DESC`` means NULLS FIRST — which matches
-- neither scan direction of this index. With plain DESC the planner falls
-- back to a parallel seq-scan + external-merge sort of the full packages
-- table (~29s at 1.3M rows) and the dashboard's initial tape fetch blows
-- through the client's 15s abort timeout. See
-- dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts (buildTapeQuery).
CREATE INDEX IF NOT EXISTS idx_tape_v2_packages_exec_start
  ON {PACKAGES_TABLE_V2}(execution_start DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_tape_v2_packages_type ON {PACKAGES_TABLE_V2}(package_type, as_of_date);
CREATE INDEX IF NOT EXISTS idx_tape_v2_packages_cluster ON {PACKAGES_TABLE_V2}(cluster_id);
CREATE INDEX IF NOT EXISTS idx_tape_v2_packages_fomc ON {PACKAGES_TABLE_V2}(fomc_meeting_label);
CREATE INDEX IF NOT EXISTS idx_tape_v2_packages_flow ON {PACKAGES_TABLE_V2}(contributes_to_flow_any, as_of_date);
CREATE INDEX IF NOT EXISTS idx_tape_v2_packages_violation ON {PACKAGES_TABLE_V2}(state_machine_violation_any);
CREATE INDEX IF NOT EXISTS idx_tape_v2_packages_metrics_gin ON {PACKAGES_TABLE_V2} USING GIN (package_metrics);
CREATE INDEX IF NOT EXISTS idx_tape_v2_packages_tape_label_upper
  ON {PACKAGES_TABLE_V2}(UPPER(COALESCE(tape_label, '')), original_execution_start DESC NULLS LAST);

-- Idempotent migrations for tables that pre-date the v2 columns
-- introduced after the initial deploy. ADD COLUMN IF NOT EXISTS keeps
-- this DDL safe to re-run on every ensure_schema() call. Per-leg
-- package economics were added so SPREADOVER_CURVE / MATCHED_MATURITY_FLY
-- composites can persist distinct per-leg PTS / PTP values.
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS package_transaction_spread NUMERIC;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS package_transaction_price NUMERIC;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS package_transaction_price_currency TEXT;

CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_package ON {LEGS_TABLE_V2}(package_id);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_exec ON {LEGS_TABLE_V2}(execution_timestamp);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_orig_exec ON {LEGS_TABLE_V2}(original_execution_timestamp);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_lifecycle ON {LEGS_TABLE_V2}(lifecycle_type);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_class ON {LEGS_TABLE_V2}(economic_class);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_flow ON {LEGS_TABLE_V2}(contributes_to_flow);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_violation ON {LEGS_TABLE_V2}(state_machine_violation);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_cluster ON {LEGS_TABLE_V2}(cluster_id);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_metrics_gin ON {LEGS_TABLE_V2} USING GIN (enrichment_metrics);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_flags_gin ON {LEGS_TABLE_V2} USING GIN (quality_flags);

-- Phase 2 perf indexes for the analytics-dock routes. Each route filters
-- on a category column ({{rate_index_clean | tape_label | canonical_underlier_key}})
-- and orders / range-scans by the original-execution timestamp. A composite
-- (filter, ts DESC) index turns those queries into a single index range
-- scan instead of a seq-scan + sort. NULLS LAST keeps the descending
-- range scan tight on the recent-end of the data, which is what
-- DAILY_CLOSE / INTRADAY / extremes queries actually want.
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_rate_idx_orig
  ON {LEGS_TABLE_V2}(rate_index_clean, original_execution_timestamp DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_tape_label_orig
  ON {LEGS_TABLE_V2}(tape_label, original_execution_timestamp DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_trade_type_orig
  ON {LEGS_TABLE_V2}(trade_type, original_execution_timestamp DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_tenor_orig
  ON {LEGS_TABLE_V2}(tenor_label, original_execution_timestamp DESC NULLS LAST);

-- Phase 4 canonical underlier key: per-row collapse of SDR underlier-name
-- variations ('USD-SOFR-OIS Compound 1D Constant' vs 'USD-SOFR-COMPOUND
-- 1D Constant', etc.) into a single comparable key. Persisted by the
-- ingest pipeline (see SDRUtils/core/underlier_canonical.py); read by
-- the rarity / traded-levels / package-analytics routes. Additive
-- ALTER + IF NOT EXISTS keeps re-runs idempotent.
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS canonical_underlier_key TEXT;
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_canonical_orig
  ON {LEGS_TABLE_V2}(canonical_underlier_key, original_execution_timestamp DESC NULLS LAST);

-- Phase 7: frontend-to-backend logic port
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS off_market_reason TEXT;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS normalized_tape_label TEXT;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS tape_tags TEXT;

ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS is_off_market_any BOOLEAN;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS confidence_score INTEGER;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS confidence_total INTEGER;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS confidence_tone TEXT;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS confidence_signals JSONB;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS summary_rate NUMERIC;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS summary_risk NUMERIC;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS summary_opa NUMERIC;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS is_ccp_switch BOOLEAN;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS ccp_switch_from TEXT;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS ccp_switch_to TEXT;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS package_adjusted_dv01 NUMERIC;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS normalized_tape_label TEXT;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS tape_tags TEXT;

-- PTP/OPA package-level columns (package-detection enhancement)
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS ptp_group_id TEXT;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS ptp_group_size INTEGER;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS opa_signed_net NUMERIC;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS opa_ptp_residual NUMERIC;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS opa_sign_confidence TEXT;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS opa_constrained_net NUMERIC;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS opa_constrained_residual NUMERIC;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS dealer_spread_est NUMERIC;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS dealer_spread_bps NUMERIC;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS ptp_sub_structures JSONB;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS ptp_price_notation SMALLINT;

ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS basis_type TEXT;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS basis_spread_bps NUMERIC;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS leg1_rate_index TEXT;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS leg2_rate_index TEXT;

-- PTP/OPA per-leg columns (package-detection enhancement)
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS ptp_group_id TEXT;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS opa_sign SMALLINT;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS opa_signed_amount NUMERIC;

-- Phase 7: lifecycle partial-unwind + seasoned-trade columns
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS lc_was_partially_terminated BOOLEAN;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS lc_has_partial_unwind BOOLEAN;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS lc_inception_notional NUMERIC;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS lc_current_notional NUMERIC;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS lc_has_past_effective BOOLEAN;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS lc_is_off_market_seasoned BOOLEAN;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS lc_days_seasoned INTEGER;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS xd_was_partially_terminated BOOLEAN;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS xd_has_past_effective BOOLEAN;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS xd_is_off_market_seasoned BOOLEAN;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS xd_days_seasoned INTEGER;

CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_norm_label_orig
  ON {LEGS_TABLE_V2}(normalized_tape_label, original_execution_timestamp DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_tape_v2_packages_norm_label
  ON {PACKAGES_TABLE_V2}(normalized_tape_label, original_execution_start DESC NULLS LAST);

-- =====================================================================
-- Manual regrouping + trader notes (2026-07-08). Dashboard-owned tables;
-- the ingest pipeline NEVER writes them. Overrides re-cluster tape rows
-- (GROUP/SPLIT/DETACH); the member table is index-probed by the display
-- view; history is an append-only audit trail; notes attach free text to
-- a TRADE or a PACKAGE. All DDL idempotent (IF NOT EXISTS) so
-- ensure_schema() can re-run safely. These tables MUST be declared before
-- the CREATE VIEW below, which references the member + notes tables.
-- =====================================================================
CREATE TABLE IF NOT EXISTS {OVERRIDES_TABLE_V2} (
    override_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    override_type TEXT NOT NULL
      CHECK (override_type IN ('GROUP','SPLIT','DETACH')),
    manual_package_id TEXT,
    trade_ids TEXT[] NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT,
    updated_at TIMESTAMPTZ,
    reason TEXT,
    tags TEXT[],
    metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    superseded_by UUID REFERENCES {OVERRIDES_TABLE_V2}(override_id),
    CONSTRAINT chk_tape_v2_override_group_min_trades
      CHECK (override_type <> 'GROUP' OR array_length(trade_ids, 1) >= 2)
);

CREATE INDEX IF NOT EXISTS idx_tape_v2_overrides_trade_ids_gin
  ON {OVERRIDES_TABLE_V2} USING GIN (trade_ids);
CREATE INDEX IF NOT EXISTS idx_tape_v2_overrides_active
  ON {OVERRIDES_TABLE_V2} (is_active) WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_tape_v2_overrides_manual_pkg
  ON {OVERRIDES_TABLE_V2} (manual_package_id);
CREATE INDEX IF NOT EXISTS idx_tape_v2_overrides_created_at
  ON {OVERRIDES_TABLE_V2} (created_at);

CREATE TABLE IF NOT EXISTS {OVERRIDE_MEMBERS_TABLE_V2} (
    trade_id TEXT NOT NULL,
    override_id UUID NOT NULL REFERENCES {OVERRIDES_TABLE_V2}(override_id),
    override_type TEXT NOT NULL,
    manual_package_id TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Backstop invariant: at most one ACTIVE override per trade. The partial
-- UNIQUE index is ALSO the btree the display view index-probes on
-- (m.trade_id = l.trade_id AND m.is_active) — no separate probe index needed.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tape_v2_override_members_active_trade
  ON {OVERRIDE_MEMBERS_TABLE_V2} (trade_id) WHERE is_active;

CREATE TABLE IF NOT EXISTS {OVERRIDE_HISTORY_TABLE_V2} (
    history_id BIGSERIAL PRIMARY KEY,
    override_id UUID NOT NULL REFERENCES {OVERRIDES_TABLE_V2}(override_id),
    action TEXT NOT NULL
      CHECK (action IN ('CREATED','UPDATED','DEACTIVATED','SUPERSEDED')),
    changed_by TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    change_details JSONB,
    previous_state JSONB
);

CREATE TABLE IF NOT EXISTS {NOTES_TABLE_V2} (
    note_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_type TEXT NOT NULL CHECK (target_type IN ('TRADE','PACKAGE')),
    target_id TEXT NOT NULL,
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_tape_v2_notes_target_active
  ON {NOTES_TABLE_V2} (target_type, target_id) WHERE is_active;

DROP VIEW IF EXISTS {DISPLAY_VIEW_V2};
CREATE OR REPLACE VIEW {DISPLAY_VIEW_V2} AS
SELECT
  p.package_id,
  p.manual_link_id,
  p.as_of_date,
  p.execution_start,
  p.execution_end,
  p.original_execution_start,
  p.clearing_accepted_start,
  p.package_structure,
  p.package_type,
  p.package_indicator,
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
  p.economic_class_primary,
  p.contributes_to_flow_any,
  p.contributes_to_volume_any,
  p.contributes_to_pnl_any,
  p.on_p43_any,
  p.state_machine_violation_any,
  p.is_fomc_dated,
  p.fomc_meeting_label,
  p.cluster_id,
  p.cluster_size,
  p.tape_label,
  p.is_off_market_any,
  p.confidence_score,
  p.confidence_total,
  p.confidence_tone,
  p.confidence_signals,
  p.summary_rate,
  p.summary_risk,
  p.summary_opa,
  p.is_ccp_switch,
  p.ccp_switch_from,
  p.ccp_switch_to,
  p.package_adjusted_dv01,
  p.normalized_tape_label,
  p.tape_tags,
  p.ptp_group_id,
  p.ptp_group_size,
  p.ptp_price_notation,
  p.opa_signed_net,
  p.opa_ptp_residual,
  p.opa_sign_confidence,
  p.dealer_spread_est,
  p.dealer_spread_bps,
  p.ptp_sub_structures,
  p.package_metrics,
  l.legs_json,
  ml.manual_package_id,
  ml.user_comment,
  ml.link_reason,
  ml.tags,
  ml.link_metrics,
  ml.created_by AS link_created_by,
  ml.created_at AS link_created_at
FROM {PACKAGES_TABLE_V2} p
LEFT JOIN LATERAL (
    SELECT jsonb_agg(to_jsonb(l) ORDER BY l.leg_order) AS legs_json
    FROM {LEGS_TABLE_V2} l
    WHERE l.package_id = p.package_id
) l ON TRUE
LEFT JOIN {MANUAL_LINKS_TABLE} ml
  ON ml.link_id = p.manual_link_id AND ml.is_active = TRUE;

-- Phase 7: swap spread VWAP daily aggregate table
CREATE TABLE IF NOT EXISTS arbs_usd_swap_vwap_daily_v2 (
    as_of_date DATE NOT NULL,
    ticker TEXT NOT NULL,
    vwap_bps NUMERIC,
    total_risk NUMERIC,
    total_notional NUMERIC,
    trade_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_vwap_v2_ticker
  ON arbs_usd_swap_vwap_daily_v2(ticker, as_of_date DESC);
"""

VWAP_TABLE_V2 = "arbs_usd_swap_vwap_daily_v2"

SIGNAL_TABLE_V2 = "arbs_usd_swap_tape_signal_v2"

SIGNAL_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {SIGNAL_TABLE_V2} (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    as_of_date DATE,
    packages_written INTEGER DEFAULT 0,
    legs_written INTEGER DEFAULT 0,
    cycle_ms INTEGER DEFAULT 0
);
INSERT INTO {SIGNAL_TABLE_V2} (id) VALUES (1) ON CONFLICT DO NOTHING;
"""

SIGNAL_REALTIME_DDL = f"""
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE {SIGNAL_TABLE_V2};
  END IF;
EXCEPTION WHEN duplicate_object THEN
  NULL;
END $$;
"""


# Runbook DDL — freezes v1 as the rollback target per §4.11. NOT executed
# automatically by ensure_schema; run manually in a change window after
# the v2 cutover is verified live.
FREEZE_V1_SQL = """
-- §4.11 freeze: revoke writes on v1, keep SELECT for instant rollback.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON
    arbs_usd_swap_tape_packages_v1,
    arbs_usd_swap_tape_legs_v1
FROM PUBLIC;

COMMENT ON TABLE arbs_usd_swap_tape_packages_v1
  IS 'FROZEN — v2 cutover. Rollback target until Phase 6 sign-off.';
COMMENT ON TABLE arbs_usd_swap_tape_legs_v1
  IS 'FROZEN — v2 cutover. Rollback target until Phase 6 sign-off.';
"""


__all__ = [
    "TAPE_SCHEMA_SQL_V2",
    "PACKAGES_TABLE_V2",
    "LEGS_TABLE_V2",
    "RUNS_TABLE_V2",
    "DISPLAY_VIEW_V2",
    "MANUAL_LINKS_TABLE",
    "OVERRIDES_TABLE_V2",
    "OVERRIDE_MEMBERS_TABLE_V2",
    "OVERRIDE_HISTORY_TABLE_V2",
    "NOTES_TABLE_V2",
    "VWAP_TABLE_V2",
    "SIGNAL_TABLE_V2",
    "SIGNAL_TABLE_DDL",
    "SIGNAL_REALTIME_DDL",
    "FREEZE_V1_SQL",
]
