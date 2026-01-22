#!/usr/bin/env python3
"""
Quick script to update the database views with is_notional_capped field.
"""

import sys
import os

# Add parent directory to path to import the module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from SDRUtils._swappulse_scripts.ingest_usdswaptions import create_db_engine, ensure_schema

def main():
    print("Updating database views to include is_notional_capped field...")
    engine = create_db_engine()
    ensure_schema(engine)
    print("Views updated successfully!")

if __name__ == "__main__":
    main()
