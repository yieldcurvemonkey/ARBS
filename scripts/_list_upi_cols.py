from sqlalchemy import text
from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils._swappulse_scripts._tape_schema import LEGS_TABLE

e = create_db_engine()
with e.connect() as c:
    rows = c.execute(
        text(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{LEGS_TABLE}'"
        )
    ).fetchall()
    upi_cols = [
        r[0] for r in rows if "upi" in r[0].lower() or "product" in r[0].lower()
    ]
    print("UPI-ish columns:", upi_cols)

    # Query the two trade ids for all upi columns
    if upi_cols:
        cols_str = ", ".join(upi_cols)
        data = c.execute(
            text(
                f"SELECT trade_id, {cols_str} FROM {LEGS_TABLE} "
                f"WHERE trade_id IN ('2844466371000000101','2844466372000000201')"
            )
        ).mappings().fetchall()
        for r in data:
            print(dict(r))
e.dispose()
