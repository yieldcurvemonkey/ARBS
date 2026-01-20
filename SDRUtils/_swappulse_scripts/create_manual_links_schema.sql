-- Manual Links Schema for Swaption Trade Tape
-- Purpose: Allow users to manually link trades into packages via the frontend

-- Main table: stores user-created linkages between trades
CREATE TABLE IF NOT EXISTS arbs_swaption_manual_links_v1 (
    link_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Linked trades (can be trade_ids or package_ids)
    linked_trade_ids TEXT[] NOT NULL,

    -- User metadata
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,

    -- User annotations (frontend interprets these)
    user_comment TEXT,
    tags JSONB DEFAULT '[]'::jsonb,

    -- Simple status flag
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT min_two_trades CHECK (array_length(linked_trade_ids, 1) >= 2)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_manual_links_trades
    ON arbs_swaption_manual_links_v1 USING GIN (linked_trade_ids);

CREATE INDEX IF NOT EXISTS idx_manual_links_active
    ON arbs_swaption_manual_links_v1 (is_active)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_manual_links_created
    ON arbs_swaption_manual_links_v1 (created_at DESC);

-- Function to get manual links for a set of trade IDs
CREATE OR REPLACE FUNCTION get_manual_links_for_trades(trade_ids_param TEXT[])
RETURNS TABLE (
    link_id UUID,
    linked_trade_ids TEXT[],
    created_by TEXT,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    user_comment TEXT,
    tags JSONB,
    is_active BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        ml.link_id,
        ml.linked_trade_ids,
        ml.created_by,
        ml.created_at,
        ml.updated_at,
        ml.user_comment,
        ml.tags,
        ml.is_active
    FROM arbs_swaption_manual_links_v1 ml
    WHERE ml.is_active = TRUE
      AND ml.linked_trade_ids && trade_ids_param;  -- Overlaps operator
END;
$$ LANGUAGE plpgsql;

-- Function to check if a trade is already linked
CREATE OR REPLACE FUNCTION is_trade_already_linked(trade_id_param TEXT)
RETURNS TABLE (
    link_id UUID,
    linked_trade_ids TEXT[],
    created_by TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        ml.link_id,
        ml.linked_trade_ids,
        ml.created_by
    FROM arbs_swaption_manual_links_v1 ml
    WHERE ml.is_active = TRUE
      AND trade_id_param = ANY(ml.linked_trade_ids);
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE arbs_swaption_manual_links_v1 IS
'User-created manual linkages between swaption trades. Frontend-driven with minimal backend logic.';

COMMENT ON COLUMN arbs_swaption_manual_links_v1.linked_trade_ids IS
'Array of trade_id values that should be displayed as a linked group';

COMMENT ON COLUMN arbs_swaption_manual_links_v1.tags IS
'User-defined tags as JSON array, e.g. ["vega_hedge", "customer_flow"]';

COMMENT ON COLUMN arbs_swaption_manual_links_v1.is_active IS
'Soft delete flag. Frontend only shows active links.';
