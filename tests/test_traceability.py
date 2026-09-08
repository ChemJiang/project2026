"""Production traceability query verification test. Cleans up all test data via finally."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection
from services.work_order_service import create_work_order, release_work_order
from services.production_service import list_units_for_order, start_operation, complete_operation
from services.quality_service import submit_inspection, start_rework, close_rework, list_defects
from services.traceability_service import list_all_units, get_unit_traceability

CHECK50_FAIL = {"base_rotation_ok": False, "joint_motion_ok": True, "gripper_motion_ok": True, "no_interference": True}
CHECK50_PASS = {"base_rotation_ok": True, "joint_motion_ok": True, "gripper_motion_ok": True, "no_interference": True}
CHECK60_PASS = {"appearance_ok": True, "connections_ok": True, "test_record_complete": True}


def _get_op_map(product_id):
    conn = get_connection()
    ops = conn.execute(
        "SELECT operation_id, operation_code FROM operations "
        "WHERE product_id = ? ORDER BY sequence",
        (product_id,),
    ).fetchall()
    conn.close()
    return {o["operation_code"]: o["operation_id"] for o in ops}


def _complete_10_to_40(unit_id, op):
    complete_operation(unit_id, op["10"], "tester")
    start_operation(unit_id, op["20"], "tester")
    complete_operation(unit_id, op["20"], "tester")
    start_operation(unit_id, op["30"], "tester")
    complete_operation(unit_id, op["30"], "tester")
    start_operation(unit_id, op["40"], "tester")
    complete_operation(unit_id, op["40"], "tester")


def _snapshot():
    conn = get_connection()
    c = {}
    for t in ["work_orders", "units", "production_events", "quality_records", "defects"]:
        c[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    conn.close()
    return c


def main():
    conn = get_connection()
    product = conn.execute(
        "SELECT product_id FROM products WHERE product_code = 'AGV-Harvest-Arm'"
    ).fetchone()
    conn.close()
    assert product is not None, "Product AGV-Harvest-Arm not found. Run init_db.py first."
    product_id = product["product_id"]
    op = _get_op_map(product_id)

    wid = None
    try:
        # Build the full flow: release -> 10-40 -> 50 FAIL -> close rework -> 50 PASS -> 60 PASS
        wid = create_work_order(product_id, 1, "2026-09-10")
        release_work_order(wid)
        unit_id = list_units_for_order(wid)[0]["unit_id"]

        all_units = list_all_units()
        unit_summary = next(u for u in all_units if u["unit_id"] == unit_id)
        serial_number = unit_summary["serial_number"]

        start_operation(unit_id, op["10"], "tester")
        _complete_10_to_40(unit_id, op)

        res = submit_inspection(unit_id, op["50"], "inspector", CHECK50_FAIL,
                                defect_type="joint failure",
                                defect_description="joint motion test failed",
                                severity="major")
        assert res["result"] == "fail"
        defect_id = list_defects(unit_id)[0]["defect_id"]
        start_rework(defect_id)
        close_rework(defect_id, "joint re-aligned and retested")

        res = submit_inspection(unit_id, op["50"], "inspector", CHECK50_PASS)
        assert res["result"] == "pass"
        res = submit_inspection(unit_id, op["60"], "inspector", CHECK60_PASS)
        assert res["result"] == "pass"

        # Query the traceability
        trace = get_unit_traceability(serial_number)

        # 1. Can query a completed unit by serial number
        assert trace["unit"]["status"] == "completed"
        assert trace["unit"]["serial_number"] == serial_number
        print("[PASS] 1. Queried completed unit by serial number")

        # 2. Correctly links product and work order
        assert trace["product"]["product_code"] == "AGV-Harvest-Arm"
        assert trace["product"]["product_name"] == "Agricultural Manipulator"
        assert trace["work_order"]["work_order_code"].startswith("WO-")
        print("[PASS] 2. Correctly linked product and work order")

        # 3. All 6 operations are Completed
        assert len(trace["operations"]) == 6
        assert all(o["state"] == "Completed" for o in trace["operations"])
        print("[PASS] 3. All 6 operations are Completed")

        # 4. Production event count matches the database
        conn = get_connection()
        db_pe = conn.execute(
            "SELECT COUNT(*) AS c FROM production_events WHERE unit_id = ?", (unit_id,)
        ).fetchone()["c"]
        conn.close()
        assert len(trace["production_events"]) == db_pe
        print(f"[PASS] 4. Production event count matches: {len(trace['production_events'])}")

        # 5. Operation 50 has two attempts
        op50_attempts = sorted(q["attempt_no"] for q in trace["quality_records"] if q["operation_code"] == "50")
        assert op50_attempts == [1, 2], f"Expected attempts 1,2, got {op50_attempts}"
        print(f"[PASS] 5. Operation 50 has two attempts: {op50_attempts}")

        # 6. Quality records count is 3
        assert len(trace["quality_records"]) == 3
        print("[PASS] 6. Quality records count is 3")

        # 7. One defect with status closed
        assert len(trace["defects"]) == 1
        assert trace["defects"][0]["status"] == "closed"
        print("[PASS] 7. One defect with status closed")

        # 8. Nonexistent serial number raises ValueError
        try:
            get_unit_traceability("NONEXISTENT-XXX")
            raise AssertionError("Nonexistent serial number should raise ValueError")
        except ValueError as e:
            print(f"[PASS] 8. Nonexistent serial number raises ValueError: {e}")

        # 9. Query does not modify the database
        before = _snapshot()
        get_unit_traceability(serial_number)
        after = _snapshot()
        assert before == after, f"Counts changed after query: {before} vs {after}"
        print("[PASS] 9. Query does not modify the database")

        # 10. foreign_key_check = 0
        conn = get_connection()
        fks = conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.close()
        assert len(fks) == 0, f"Foreign key violations: {fks}"
        print("[PASS] 10. foreign_key_check = 0")

        print("ALL TESTS PASSED")
    finally:
        if wid is not None:
            conn = get_connection()
            conn.execute(
                "DELETE FROM defects WHERE unit_id IN (SELECT unit_id FROM units WHERE work_order_id = ?)",
                (wid,),
            )
            conn.execute(
                "DELETE FROM quality_records WHERE unit_id IN (SELECT unit_id FROM units WHERE work_order_id = ?)",
                (wid,),
            )
            conn.execute(
                "DELETE FROM production_events WHERE unit_id IN (SELECT unit_id FROM units WHERE work_order_id = ?)",
                (wid,),
            )
            conn.execute("DELETE FROM units WHERE work_order_id = ?", (wid,))
            conn.execute("DELETE FROM work_orders WHERE work_order_id = ?", (wid,))
            conn.commit()
            conn.close()
            print(f"[CLEANUP] Deleted test work order {wid} and its related data")


if __name__ == "__main__":
    main()
