"""
Apply manual links schema migration to SwapPulse database.

Run this script to create the manual links table and supporting functions.
"""

import os
from pathlib import Path
from sqlalchemy import create_engine, text


def get_db_connection_string() -> str:
    """Build database connection string from environment variables."""
    host = os.getenv("SWAPPULSE_DB_HOST", "aws-0-us-east-1.pooler.supabase.com")
    port = os.getenv("SWAPPULSE_DB_PORT", "6543")
    dbname = os.getenv("SWAPPULSE_DB_NAME", "postgres")
    user = os.getenv("SWAPPULSE_DB_USER", "postgres.rdobtpugtnmefxplgwyp")
    password = os.getenv("SWAPPULSE_DB_PASSWORD", "0rbZUh8y0Fsvdlry")

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def apply_migration():
    """Apply the manual links schema migration."""
    script_dir = Path(__file__).parent
    migration_file = script_dir / "create_manual_links_schema.sql"

    if not migration_file.exists():
        raise FileNotFoundError(f"Migration file not found: {migration_file}")

    print(f"Reading migration from: {migration_file}")
    sql = migration_file.read_text()

    conn_string = get_db_connection_string()
    engine = create_engine(conn_string)

    print("Applying migration...")
    with engine.begin() as conn:
        # Execute the entire SQL script
        conn.execute(text(sql))

    print("✅ Migration applied successfully!")
    print("\nCreated:")
    print("  - Table: arbs_swaption_manual_links_v1")
    print("  - Indexes: idx_manual_links_trades, idx_manual_links_active, idx_manual_links_created")
    print("  - Functions: get_manual_links_for_trades, is_trade_already_linked")


if __name__ == "__main__":
    apply_migration()
