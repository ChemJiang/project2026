"""Work order creation/release loop verification test. Cleans up test data via finally."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection
from services.work_order_service import (
    create_work_order,
    release_work_order,
    get_units,
)


def main():
    conn = get_connection()
    product = conn.execute(
        "SELECT product_id FROM products WHERE product_code = 'AGV-Harvest-Arm'"
    ).fetchone()
    conn.close()
    assert product is not None, "Product AGV-Harvest-Arm not found. Run init_db.py first."
    product_id = product["product_id"]

    wid = None
    try:
        # 1. Create a work order of quantity 3
        wid = create_work_order(product_id, 3, "2026-09-10")
        conn = get_connection()
        wo = conn.execute("SELECT * FROM work_orders WHERE work_order_id = ?", (wid,)).fetchone()
        unit_cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM units WHERE work_order_id = ?", (wid,)
        ).fetchone()["c"]
        conn.close()
        assert wo["status"] == "draft", f"Expected DRAFT, got {wo['status']}"
        assert unit_cnt == 0, f"Expected 0 units after creation, got {unit_cnt}"
        print(f"[PASS] 1. Created work order {wo['work_order_code']}: status=DRAFT, units=0")

        # 2. Release
        serials = release_work_order(wid)
        conn = get_connection()
        wo = conn.execute("SELECT * FROM work_orders WHERE work_order_id = ?", (wid,)).fetchone()
        unit_cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM units WHERE work_order_id = ?", (wid,)
        ).fetchone()["c"]
        conn.close()
        assert wo["status"] == "released", f"Expected RELEASED, got {wo['status']}"
        assert wo["released_at"] is not None, "released_at was not recorded"
        assert unit_cnt == 3, f"Expected 3 units after release, got {unit_cnt}"
        print(f"[PASS] 2. Released: status=RELEASED, units=3, released_at={wo['released_at']}")

        # 3. Re-release should be rejected
        try:
            release_work_order(wid)
            raise AssertionError("Re-release should be rejected")
        except ValueError as e:
            print(f"[PASS] 3. Re-release rejected: {e}")
        conn = get_connection()
        unit_cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM units WHERE work_order_id = ?", (wid,)
        ).fetchone()["c"]
        conn.close()
        assert unit_cnt == 3, f"Expected units to remain 3, got {unit_cnt}"

        # 4. Serial numbers are unique
        unit_serials = [u["serial_number"] for u in get_units(wid)]
        assert len(unit_serials) == 3
        assert len(set(unit_serials)) == 3, f"Serial numbers should be unique, got {unit_serials}"
        print(f"[PASS] 4. Serial numbers unique: {unit_serials}")

        # 5. Foreign key integrity
        conn = get_connection()
        fks = conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.close()
        assert len(fks) == 0, f"Foreign key violations: {fks}"
        print("[PASS] 5. foreign_key_check = 0")

        # 6. Persistence (data still present after reconnect)
        conn = get_connection()
        unit_cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM units WHERE work_order_id = ?", (wid,)
        ).fetchone()["c"]
        wo = conn.execute(
            "SELECT status FROM work_orders WHERE work_order_id = ?", (wid,)
        ).fetchone()
        conn.close()
        assert unit_cnt == 3 and wo["status"] == "released"
        print("[PASS] 6. Data persisted after reconnect")

        print("ALL TESTS PASSED")
    finally:
        if wid is not None:
            conn = get_connection()
            conn.execute("DELETE FROM units WHERE work_order_id = ?", (wid,))
            conn.execute("DELETE FROM work_orders WHERE work_order_id = ?", (wid,))
            conn.commit()
            conn.close()
            print(f"[CLEANUP] Deleted test work order {wid} and its units")


if __name__ == "__main__":
    main()
