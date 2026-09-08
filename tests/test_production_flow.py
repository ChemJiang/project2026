"""Production reporting loop verification test. Cleans up all test data via finally."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection
from services.work_order_service import create_work_order, release_work_order
from services.production_service import (
    list_units_for_order,
    start_operation,
    complete_operation,
)


def _set_unit_status(unit_id, status):
    conn = get_connection()
    conn.execute("UPDATE units SET status = ? WHERE unit_id = ?", (status, unit_id))
    conn.commit()
    conn.close()


def _get_op_map(product_id):
    conn = get_connection()
    ops = conn.execute(
        "SELECT operation_id, operation_code FROM operations "
        "WHERE product_id = ? ORDER BY sequence",
        (product_id,),
    ).fetchall()
    conn.close()
    return {o["operation_code"]: o["operation_id"] for o in ops}


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
        wid = create_work_order(product_id, 1, "2026-09-10")
        release_work_order(wid)
        units = list_units_for_order(wid)
        assert len(units) == 1
        unit_id = units[0]["unit_id"]
        op = _get_op_map(product_id)

        # 1. Empty operator cannot start
        try:
            start_operation(unit_id, op["10"], "")
            raise AssertionError("Empty operator should not start")
        except ValueError as e:
            print(f"[PASS] 1. Empty operator cannot start: {e}")

        # 2. Whitespace-only operator cannot start
        try:
            start_operation(unit_id, op["10"], "   ")
            raise AssertionError("Whitespace-only operator should not start")
        except ValueError as e:
            print(f"[PASS] 2. Whitespace-only operator cannot start: {e}")

        # 3. queued unit becomes in_production after starting operation 10
        # 4. work order becomes in_progress
        start_operation(unit_id, op["10"], "tester")
        conn = get_connection()
        u = conn.execute("SELECT status FROM units WHERE unit_id = ?", (unit_id,)).fetchone()
        wo = conn.execute(
            "SELECT status FROM work_orders WHERE work_order_id = ?", (wid,)
        ).fetchone()
        conn.close()
        assert u["status"] == "in_production", f"Expected in_production, got {u['status']}"
        assert wo["status"] == "in_progress", f"Expected in_progress, got {wo['status']}"
        print("[PASS] 3. queued unit becomes in_production after starting operation 10")
        print("[PASS] 4. work order becomes in_progress")

        # 5. Cannot start operation 20 before operation 10 completes
        try:
            start_operation(unit_id, op["20"], "tester")
            raise AssertionError("Should not start operation 20 before 10 completes")
        except ValueError as e:
            print(f"[PASS] 5. Cannot start operation 20 before 10 completes: {e}")

        # 6. Operation 10 cannot be started twice
        try:
            start_operation(unit_id, op["10"], "tester")
            raise AssertionError("Operation 10 should not start twice")
        except ValueError as e:
            print(f"[PASS] 6. Operation 10 cannot be started twice: {e}")

        # 7. Cannot complete an operation that was not started
        try:
            complete_operation(unit_id, op["30"], "tester")
            raise AssertionError("Should not complete operation 30 without start")
        except ValueError as e:
            print(f"[PASS] 7. Cannot complete an unstarted operation: {e}")

        # 8. After completing 10, operation 20 can start
        complete_operation(unit_id, op["10"], "tester")
        start_operation(unit_id, op["20"], "tester")
        print("[PASS] 8. Operation 20 can start after 10 completes")

        # 9. Complete 10, 20, 30, 40 in sequence
        complete_operation(unit_id, op["20"], "tester")
        start_operation(unit_id, op["30"], "tester")
        complete_operation(unit_id, op["30"], "tester")
        start_operation(unit_id, op["40"], "tester")
        complete_operation(unit_id, op["40"], "tester")
        conn = get_connection()
        completed = conn.execute(
            "SELECT o.operation_code FROM production_events e "
            "JOIN operations o ON o.operation_id = e.operation_id "
            "WHERE e.unit_id = ? AND e.event_type = 'complete' ORDER BY o.sequence",
            (unit_id,),
        ).fetchall()
        conn.close()
        completed_codes = [r["operation_code"] for r in completed]
        assert completed_codes == ["10", "20", "30", "40"], f"Expected 10-40, got {completed_codes}"
        print(f"[PASS] 9. Completed 10, 20, 30, 40 in sequence: {completed_codes}")

        # 10. Operation 50 cannot be completed normally
        try:
            complete_operation(unit_id, op["50"], "tester")
            raise AssertionError("Operation 50 should not complete normally")
        except ValueError as e:
            print(f"[PASS] 10. Operation 50 cannot be completed normally: {e}")

        # 11. completed unit cannot start
        _set_unit_status(unit_id, "completed")
        try:
            start_operation(unit_id, op["50"], "tester")
            raise AssertionError("completed unit should not start")
        except ValueError as e:
            print(f"[PASS] 11. completed unit cannot start: {e}")

        # 12. scrapped unit cannot start
        _set_unit_status(unit_id, "scrapped")
        try:
            start_operation(unit_id, op["50"], "tester")
            raise AssertionError("scrapped unit should not start")
        except ValueError as e:
            print(f"[PASS] 12. scrapped unit cannot start: {e}")

        # 13. non-in_production unit cannot complete
        _set_unit_status(unit_id, "queued")
        try:
            complete_operation(unit_id, op["40"], "tester")
            raise AssertionError("queued unit should not complete")
        except ValueError as e:
            print(f"[PASS] 13. non-in_production unit cannot complete: {e}")

        # 14. foreign_key_check = 0
        conn = get_connection()
        fks = conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.close()
        assert len(fks) == 0, f"Foreign key violations: {fks}"
        print("[PASS] 14. foreign_key_check = 0")

        print("ALL TESTS PASSED")
    finally:
        if wid is not None:
            conn = get_connection()
            conn.execute(
                "DELETE FROM production_events WHERE unit_id IN "
                "(SELECT unit_id FROM units WHERE work_order_id = ?)",
                (wid,),
            )
            conn.execute("DELETE FROM units WHERE work_order_id = ?", (wid,))
            conn.execute("DELETE FROM work_orders WHERE work_order_id = ?", (wid,))
            conn.commit()
            conn.close()
            print(f"[CLEANUP] Deleted test work order {wid} and its units / production_events")


if __name__ == "__main__":
    main()
