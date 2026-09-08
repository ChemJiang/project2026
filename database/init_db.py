"""Initialize the MES database: run schema.sql to create tables and insert base data.

Usage:
    python database/init_db.py

Idempotent: repeated runs do not duplicate base data (UNIQUE constraints + INSERT OR IGNORE).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection, DB_PATH

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # Create tables (IF NOT EXISTS allows repeatable execution)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    # --- 1. products ---
    cur.execute(
        "INSERT OR IGNORE INTO products (product_code, product_name, description) VALUES (?, ?, ?)",
        ("AGV-Harvest-Arm", "Agricultural Manipulator", "Agricultural harvesting robotic arm"),
    )
    product_id = cur.execute(
        "SELECT product_id FROM products WHERE product_code = ?", ("AGV-Harvest-Arm",)
    ).fetchone()[0]

    # --- 2. operations: 6 assembly operations 10-60 (triangular time min/base/max + worker + station) ---
    operations = [
        ("10", "Parts Kitting",                   1, 6.0,  8.0,  12.0, "KittingOperator",  "KittingStation"),
        ("20", "Mechanical Pre-assembly",         2, 15.0, 20.0, 28.0, "AssemblyOperator", "MechanicalBench"),
        ("30", "Servo & Joint Assembly",          3, 14.0, 18.0, 25.0, "AssemblyOperator", "ServoBench"),
        ("40", "Gripper Assembly & Calibration",  4, 9.0,  12.0, 18.0, "AssemblyOperator", "CalibrationBench"),
        ("50", "Functional Testing",              5, 7.0,  10.0, 16.0, "TestTechnician",   "TestBench"),
        ("60", "Final Inspection",                6, 4.0,  5.0,  8.0,  "QualityInspector", "InspectionStation"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO operations "
        "(product_id, operation_code, operation_name, sequence, "
        " min_time_min, base_time_min, max_time_min, worker, station) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(product_id, *op) for op in operations],
    )

    # --- 3. parts & bom: DEMO SEED DATA (placeholder only, not a complete BOM) ---
    parts = [
        ("AM-COTS-010", "MG996R Servo Motor", "COTS"),
        ("SG90",         "Gripper Servo",     "COTS"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO parts (part_code, part_name, category) VALUES (?, ?, ?)",
        parts,
    )

    bom = [
        ("AM-COTS-010", 3),
        ("SG90",         1),
    ]
    for part_code, qty in bom:
        part_id = cur.execute(
            "SELECT part_id FROM parts WHERE part_code = ?", (part_code,)
        ).fetchone()[0]
        cur.execute(
            "INSERT OR IGNORE INTO bom (product_id, part_id, quantity) VALUES (?, ?, ?)",
            (product_id, part_id, qty),
        )

    conn.commit()

    # --- Verification output ---
    tables = [
        r[0]
        for r in cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    print(f"[OK] Database generated: {DB_PATH}")
    print(f"[OK] Table count: {len(tables)} -> {tables}")
    for t in tables:
        cnt = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        print(f"    {t:<20} {cnt} rows")

    conn.close()


if __name__ == "__main__":
    init_db()
