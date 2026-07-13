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
    dealer_charge          NUMERIC,
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
