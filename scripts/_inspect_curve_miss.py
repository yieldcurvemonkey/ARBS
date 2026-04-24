"""Why wasn't the 10Y/20Y pair detected as a CURVE? Print all detector-
relevant fields for both trade IDs."""
from sqlalchemy import text

from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils._swappulse_scripts._tape_schema import LEGS_TABLE


TRADE_IDS = (
    "2844466371000000101",  # 10Y
    "2844466372000000201",  # 20Y
)


def main() -> None:
    engine = create_db_engine()
    with engine.connect() as conn:
        cols = conn.execute(
            text(
                f"""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = '{LEGS_TABLE}'
                ORDER BY ordinal_position
                """
            )
        ).fetchall()
        col_names = [c[0] for c in cols]
        # Pick the detector-relevant subset.
        interesting = [
            c for c in col_names
            if c in {
                "trade_id", "execution_timestamp", "effective_date",
                "expiration_date", "tenor_label", "tenor_years",
                "fixed_rate", "notional", "notional_currency", "risk",
                "forward_label", "product_type", "package_type",
                "package_id", "package_legs", "package_indicator",
                "package_transaction_spread", "package_transaction_price",
                "upi", "upi_underlier_name", "cleared",
                "rate_index_clean", "venue", "platform_identifier",
            }
        ]
        sel = ", ".join(interesting)
        rows = conn.execute(
            text(
                f"""
                SELECT {sel}
                FROM {LEGS_TABLE}
                WHERE trade_id IN :ids
                """
            ).bindparams(
                __import__("sqlalchemy").bindparam("ids", expanding=True)
            ),
            {"ids": list(TRADE_IDS)},
        ).mappings().fetchall()
        for r in rows:
            print(f"\n--- trade_id={r['trade_id']} ---")
            for k, v in r.items():
                print(f"  {k}: {v}")
    engine.dispose()


if __name__ == "__main__":
    main()
