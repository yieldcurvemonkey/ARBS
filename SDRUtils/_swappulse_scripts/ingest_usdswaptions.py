"""
Swaption Data Ingestion Script for SwapPulse Backend.

This script generates the Swaption Classification DataFrame and ingests it
into a normalized Postgres schema using a Two-Table Relational Model
(Packages + Legs) for efficient frontend querying.

Usage:
    python -m SDRUtils.swappulse_scripts.ingest_swaptions [--days N] [--start YYYY-MM-DD] [--end YYYY-MM-DD]

Environment Variables:
    SWAPPULSE_DB_HOST - Database host (default: aws-0-us-east-1.pooler.supabase.com)
    SWAPPULSE_DB_PORT - Database port (default: 6543)
    SWAPPULSE_DB_NAME - Database name (default: postgres)
    SWAPPULSE_DB_USER - Database user (default: postgres.rdobtpugtnmefxplgwyp)
    SWAPPULSE_DB_PASSWORD - Database password
    SDR_CACHE_PATH - Path for SDR data caching (default: ./sdr_cache)
"""

from __future__ import annotations

import argparse
import os
import sys
import pytz
from datetime import datetime, timedelta, date
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Global Table Names
PACKAGES_TABLE_NAME = "arbs_swaption_packages_v0"
LEGS_TABLE_NAME = "arbs_swaption_legs_v0"
NY_tz = pytz.timezone("America/New_York")


# Schema definitions
SCHEMA_SQL = f"""
-- 1. Package-level data (One row per classified package)
CREATE TABLE IF NOT EXISTS {PACKAGES_TABLE_NAME} (
    package_id TEXT PRIMARY KEY,
    package_type TEXT NOT NULL,
    platform TEXT,
    expiration_date DATE,
    tenor_years NUMERIC,
    forward_years NUMERIC,
    execution_timestamp TIMESTAMPTZ,
    confidence NUMERIC,
    reason TEXT,
    legs_count INTEGER,
    total_premium NUMERIC,
    total_notional NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Leg-level data (Multiple rows per package)
CREATE TABLE IF NOT EXISTS {LEGS_TABLE_NAME} (
    id SERIAL PRIMARY KEY,
    package_id TEXT REFERENCES {PACKAGES_TABLE_NAME}(package_id),
    trade_id TEXT NOT NULL,
    leg_order INTEGER,
    product_type TEXT,
    strike NUMERIC,
    notional NUMERIC,
    premium NUMERIC,
    execution_timestamp TIMESTAMPTZ,
    UNIQUE(package_id, trade_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_packages_type ON {PACKAGES_TABLE_NAME}(package_type);
CREATE INDEX IF NOT EXISTS idx_packages_date ON {PACKAGES_TABLE_NAME}(execution_timestamp);
CREATE INDEX IF NOT EXISTS idx_packages_platform ON {PACKAGES_TABLE_NAME}(platform);
CREATE INDEX IF NOT EXISTS idx_legs_package ON {LEGS_TABLE_NAME}(package_id);
"""


def get_db_connection_string() -> str:
    """Build database connection string from environment variables."""
    host = os.getenv("SWAPPULSE_DB_HOST", "aws-0-us-east-1.pooler.supabase.com")
    port = os.getenv("SWAPPULSE_DB_PORT", "6543")
    dbname = os.getenv("SWAPPULSE_DB_NAME", "postgres")
    user = os.getenv("SWAPPULSE_DB_USER", "postgres.rdobtpugtnmefxplgwyp")
    password = os.getenv("SWAPPULSE_DB_PASSWORD", "0rbZUh8y0Fsvdlry")

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def create_db_engine() -> Engine:
    """Create SQLAlchemy engine with connection pooling."""
    conn_string = get_db_connection_string()
    return create_engine(
        conn_string,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
    )


def ensure_schema(engine: Engine) -> None:
    """Create tables and indexes if they don't exist."""
    with engine.connect() as conn:
        # Execute each statement separately
        for statement in SCHEMA_SQL.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))
        conn.commit()
    print("Schema verified/created successfully.")


def build_classification_dataframe(
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_path: str,
) -> pd.DataFrame:
    """
    Build the swaption classification DataFrame.

    Uses merge_package_legs=False to get individual leg data for normalization.
    """
    from SDRUtils.products.usd.usd_swaptions import USD_Swaptions

    swaptions = USD_Swaptions()
    df = swaptions.build_classification_dataframe(
        start=start,
        end=end,
        cache_path=cache_path,
        detect_swaption_packages=True,
        merge_package_legs=False,  # Keep individual legs for normalization
        only_newt=True,  # Only NEWT-TRAD events (new trades)
    )
    return df


def transform_to_relational(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Transform flat classification DataFrame into normalized Package and Leg tables.

    Args:
        df: Flat classification DataFrame with individual trade rows

    Returns:
        Tuple of (packages_df, legs_df)
    """
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    # Ensure package_id exists - assign single-leg packages for trades without one
    if "package_id" not in df.columns:
        df["package_id"] = None

    # For trades without a package_id, create one from trade_id
    mask_no_pkg = df["package_id"].isna() | (df["package_id"] == "")
    if mask_no_pkg.any():
        df.loc[mask_no_pkg, "package_id"] = df.loc[mask_no_pkg, "trade_id"].apply(lambda x: f"single_{x}")
        df.loc[mask_no_pkg, "package_type"] = "OUTRIGHT"

    # Group by package_id to build package-level records
    package_groups = df.groupby("package_id")

    packages = []
    legs = []

    for package_id, group in package_groups:
        if pd.isna(package_id) or package_id == "":
            continue

        first_row = group.iloc[0]

        # Safe extraction helper
        def safe_get(row, col, default=None):
            val = row.get(col, default)
            if pd.isna(val):
                return default
            return val

        # 1. Construct Package Object (Header)
        package_record = {
            "package_id": package_id,
            "package_type": safe_get(first_row, "package_type", "OUTRIGHT"),
            "platform": safe_get(first_row, "platform_identifier"),
            "expiration_date": safe_get(first_row, "expiration_date"),
            "tenor_years": safe_get(first_row, "tenor_years"),
            "forward_years": safe_get(first_row, "forward_start_years"),
            "execution_timestamp": group["execution_timestamp"].min(),
            "confidence": safe_get(first_row, "package_confidence"),
            "reason": safe_get(first_row, "package_reason"),
            "legs_count": len(group),
            # Aggregates for fast display
            "total_premium": group["premium"].sum() if "premium" in group.columns else 0,
            "total_notional": group["notional"].sum() if "notional" in group.columns else 0,
        }
        packages.append(package_record)

        # 2. Construct Leg Objects (Details)
        # Sort legs by timestamp or strike to ensure consistent ordering
        sort_cols = []
        for col in ["execution_timestamp", "strike", "trade_id"]:
            if col in group.columns:
                sort_cols.append(col)

        if sort_cols:
            sorted_group = group.sort_values(sort_cols)
        else:
            sorted_group = group

        for i, (_, row) in enumerate(sorted_group.iterrows()):
            leg_record = {
                "package_id": package_id,
                "trade_id": str(safe_get(row, "trade_id", "")),
                "leg_order": i,
                "product_type": safe_get(row, "product_type"),
                "strike": safe_get(row, "strike"),
                "notional": safe_get(row, "notional"),
                "premium": safe_get(row, "premium"),
                "execution_timestamp": safe_get(row, "execution_timestamp"),
            }
            legs.append(leg_record)

    packages_df = pd.DataFrame(packages)
    legs_df = pd.DataFrame(legs)

    return packages_df, legs_df


def get_existing_package_ids(engine: Engine) -> set:
    """Get set of existing package_ids from the database."""
    query = f"SELECT package_id FROM {PACKAGES_TABLE_NAME}"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            return {row[0] for row in result}
    except Exception:
        return set()


def ingest_to_postgres(
    packages_df: pd.DataFrame,
    legs_df: pd.DataFrame,
    engine: Engine,
    skip_existing: bool = True,
) -> tuple[int, int]:
    """
    Ingest package and leg DataFrames into Postgres.

    Args:
        packages_df: DataFrame with package-level data
        legs_df: DataFrame with leg-level data
        engine: SQLAlchemy engine
        skip_existing: If True, skip packages that already exist

    Returns:
        Tuple of (packages_inserted, legs_inserted)
    """
    if packages_df.empty:
        print("No packages to ingest.")
        return 0, 0

    packages_inserted = 0
    legs_inserted = 0

    # Filter out existing packages if requested
    if skip_existing:
        existing_ids = get_existing_package_ids(engine)
        if existing_ids:
            new_mask = ~packages_df["package_id"].isin(existing_ids)
            new_package_ids = set(packages_df.loc[new_mask, "package_id"])
            packages_df = packages_df[new_mask]
            legs_df = legs_df[legs_df["package_id"].isin(new_package_ids)]

            if packages_df.empty:
                print("All packages already exist in database. Skipping.")
                return 0, 0

            print(f"Filtered to {len(packages_df)} new packages (skipped {len(existing_ids)} existing).")

    # Insert packages first (due to foreign key constraint)
    with engine.begin() as conn:
        # Use pandas to_sql for bulk insert
        packages_df.to_sql(
            PACKAGES_TABLE_NAME,
            conn,
            if_exists="append",
            index=False,
            method="multi",
        )
        packages_inserted = len(packages_df)

        if not legs_df.empty:
            # Remove the 'id' column if present (let Postgres generate it)
            if "id" in legs_df.columns:
                legs_df = legs_df.drop(columns=["id"])

            legs_df.to_sql(
                LEGS_TABLE_NAME,
                conn,
                if_exists="append",
                index=False,
                method="multi",
            )
            legs_inserted = len(legs_df)

    return packages_inserted, legs_inserted


def print_summary(
    df: pd.DataFrame,
    packages_df: pd.DataFrame,
    legs_df: pd.DataFrame,
    packages_inserted: int,
    legs_inserted: int,
) -> None:
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("INGESTION SUMMARY")
    print("=" * 60)

    print(f"\nClassification DataFrame:")
    print(f"  - Total rows: {len(df)}")

    if not df.empty and "package_type" in df.columns:
        print(f"  - Package types found:")
        for ptype, count in df["package_type"].value_counts().items():
            print(f"      {ptype}: {count}")

    print(f"\nTransformed Data:")
    print(f"  - Packages: {len(packages_df)}")
    print(f"  - Legs: {len(legs_df)}")

    print(f"\nDatabase Insertion:")
    print(f"  - Packages inserted: {packages_inserted}")
    print(f"  - Legs inserted: {legs_inserted}")

    if not packages_df.empty:
        print(f"\nPackage Statistics:")
        print(f"  - Total notional: ${packages_df['total_notional'].sum():,.0f}")
        print(f"  - Total premium: ${packages_df['total_premium'].sum():,.0f}")
        print(f"  - Avg legs per package: {packages_df['legs_count'].mean():.2f}")

        print(f"\n  - Package types:")
        for ptype, count in packages_df["package_type"].value_counts().items():
            print(f"      {ptype}: {count}")

    print("\n" + "=" * 60)


def main(
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    days: int = 7,
    cache_path: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """
    Main entry point for swaption ingestion.

    Args:
        start: Start timestamp (defaults to N days ago)
        end: End timestamp (defaults to now)
        days: Number of days to look back if start not specified
        cache_path: Path for SDR data caching
        dry_run: If True, skip actual database insertion
    """
    # Set defaults
    if end is None:
        end = pd.Timestamp.now(tz="UTC")
    if start is None:
        start = end - timedelta(days=days)
    if cache_path is None:
        cache_path = os.getenv("SDR_CACHE_PATH", "./sdr_cache")

    print(f"Swaption Ingestion Script")
    print(f"Date range: {start} to {end}")
    print(f"Cache path: {cache_path}")
    print(f"Dry run: {dry_run}")
    print()

    # Step 1: Create DB engine and ensure schema
    if not dry_run:
        print("Connecting to database...")
        engine = create_db_engine()
        ensure_schema(engine)
    else:
        engine = None
        print("Dry run mode - skipping database connection.")

    # Step 2: Build classification DataFrame
    print("\nBuilding classification DataFrame...")
    df = build_classification_dataframe(start, end, cache_path)

    if df.empty:
        print("No swaption trades found in date range.")
        return

    print(f"Found {len(df)} classified trades.")

    # Step 3: Transform to relational model
    print("\nTransforming to relational model...")
    packages_df, legs_df = transform_to_relational(df)
    print(f"Created {len(packages_df)} packages with {len(legs_df)} legs.")

    # Step 4: Ingest to Postgres
    if dry_run:
        print("\nDry run - skipping database insertion.")
        packages_inserted = 0
        legs_inserted = 0
    else:
        print("\nIngesting to Postgres...")
        packages_inserted, legs_inserted = ingest_to_postgres(packages_df, legs_df, engine)

    # Step 5: Print summary
    print_summary(df, packages_df, legs_df, packages_inserted, legs_inserted)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Ingest swaption classification data into SwapPulse database.")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)",
    )
    parser.add_argument(
        "--start",
        type=str,
        help="Start date (YYYY-MM-DD format)",
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End date (YYYY-MM-DD format)",
    )
    parser.add_argument(
        "--cache-path",
        type=str,
        help="Path for SDR data caching",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without inserting to database",
    )
    return parser.parse_args()


if __name__ == "__main__":
    # args = parse_args()

    # # Parse dates if provided
    # start = None
    # end = None
    # if args.start:
    #     start = pd.Timestamp(args.start, tz="UTC")
    # if args.end:
    #     end = pd.Timestamp(args.end, tz="UTC")

    cache_path = r"C:\Users\chris\clee\project-oasis\private\sdranalytics\.cache"

    as_of = date(2026, 1, 15)
    start = NY_tz.localize(datetime(as_of.year, as_of.month, as_of.day, 0, 0))
    end = NY_tz.localize(datetime(as_of.year, as_of.month, as_of.day, 23, 59))

    main(
        start=start,
        end=end,
        # days=args.days,
        cache_path=cache_path,
        dry_run=True,
    )
