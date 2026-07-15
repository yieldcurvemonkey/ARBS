"""DDL for the dealer positioning ladder tables (ladder spec sections 4-5)."""

LADDER_PRINTS_TABLE = "arbs_stir_ladder_prints_v1"
BOOK_MARKS_TABLE = "arbs_stir_book_marks_v1"

DDL_STATEMENTS = [
    f"""
CREATE TABLE IF NOT EXISTS {LADDER_PRINTS_TABLE} (
    unit_key              TEXT NOT NULL,
    bucket_space          TEXT NOT NULL,
    bucket_key            TEXT NOT NULL,
    delta_dv01            NUMERIC NOT NULL,
    as_of_date            DATE NOT NULL,
    execution_timestamp   TIMESTAMPTZ NOT NULL,
    visibility_timestamp  TIMESTAMPTZ NOT NULL,
    p_flip                NUMERIC,
    direction_confidence  TEXT,
    curve_suspect_trade   BOOLEAN DEFAULT FALSE,
    is_block              BOOLEAN DEFAULT FALSE,
    dv01                  NUMERIC,
    projected_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (unit_key, bucket_space, bucket_key)
)""",
    f"CREATE INDEX IF NOT EXISTS idx_ladder_prints_vis ON {LADDER_PRINTS_TABLE} (bucket_space, bucket_key, visibility_timestamp)",
    f"CREATE INDEX IF NOT EXISTS idx_ladder_prints_asof ON {LADDER_PRINTS_TABLE} (as_of_date)",
    f"""
CREATE TABLE IF NOT EXISTS {BOOK_MARKS_TABLE} (
    unit_key              TEXT NOT NULL,
    mark_ts               TIMESTAMPTZ NOT NULL,
    mark_kind             TEXT NOT NULL,
    npv_usd               NUMERIC,
    pnl_since_entry_usd   NUMERIC,
    curve_name            TEXT,
    marked_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (unit_key, mark_ts)
)""",
    f"CREATE INDEX IF NOT EXISTS idx_book_marks_ts ON {BOOK_MARKS_TABLE} (mark_ts)",
    f"CREATE INDEX IF NOT EXISTS idx_book_marks_kind ON {BOOK_MARKS_TABLE} (mark_kind, mark_ts)",
]


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        for stmt in DDL_STATEMENTS:
            cur.execute(stmt)
    conn.commit()
