from sqlalchemy import text
from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils._swappulse_scripts._tape_schema import LEGS_TABLE, PACKAGES_TABLE

e = create_db_engine()
with e.connect() as c:
    rows = c.execute(
        text(
            f"""
            SELECT l.trade_id, p.package_type, p.package_id,
                   l.tenor_label, l.platform_identifier,
                   l.execution_timestamp
            FROM {LEGS_TABLE} l
            JOIN {PACKAGES_TABLE} p ON p.package_id = l.package_id
            WHERE l.trade_id IN (
              '2844466371000000101', '2844466372000000201'
            )
            ORDER BY l.trade_id
            """
        )
    ).mappings().fetchall()
    for r in rows:
        print(dict(r))
e.dispose()
