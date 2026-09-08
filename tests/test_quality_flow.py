"""Quality inspection and defect rework loop verification test. Cleans up all test data via finally."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection
from services.work_order_service import create_work_order, release_work_order
from services.production_service import (
    list_units_for_order,
    get_unit_progress,
    start_operation,
    complete_operation,
)
from services.quality_service import (
    submit_inspection,
    list_quality_records,
    start_rework,
    close_rework,
)

CHECK50_PASS = {"base_rotation_ok": True, "joint_motion_ok": True, "gripper_motion_ok": True, "no_interference": True}
CHECK50_FAIL = {"base_rotation_ok": False, "joint_motion_ok": True, "gripper_motion_ok": True, "no_interference": True}
CHECK60_PASS = {"appearance_ok": True, "connections_ok": True, "test_record_complete": True}


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


def _counts(unit_id, op50_id):
    conn = get_connection()
    qr = conn.execute("SELECT COUNT(*) AS c FROM quality_records WHERE unit_id = ?", (unit_id,)).fetchone()["c"]
    pe = conn.execute("SELECT COUNT(*) AS c FROM production_events WHERE unit_id = ? AND operation_id = ?", (unit_id, op50_id)).fetchone()["c"]
    d = conn.execute("SELECT COUNT(*) AS c FROM defects WHERE unit_id = ?", (unit_id,)).fetchone()["c"]
    conn.close()
    return qr, pe, d


def _complete_10_to_40(unit_id, op):
    complete_operation(unit_id, op["10"], "tester")
    start_operation(unit_id, op["20"], "tester")
    complete_operation(unit_id, op["20"], "tester")
    start_operation(unit_id, op["30"], "tester")
    complete_operation(unit_id, op["30"], "tester")
    start_operation(unit_id, op["40"], "tester")
    complete_operation(unit_id, op["40"], "tester")


def _cleanup(wids):
    for wid in wids:
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


def main():
    conn = get_connection()
    product = conn.execute(
        "SELECT product_id FROM products WHERE product_code = 'AGV-Harvest-Arm'"
    ).fetchone()
    conn.close()
    assert product is not None, "Product AGV-Harvest-Arm not found. Run init_db.py first."
    product_id = product["product_id"]
    op = _get_op_map(product_id)

    wids = []
    try:
        # ===== Scenario 1: fail -> rework -> pass -> 60 -> completed =====
        wid1 = create_work_order(product_id, 1, "2026-09-10")
        wids.append(wid1)
        release_work_order(wid1)
        unit1 = list_units_for_order(wid1)[0]["unit_id"]

        # 1. Empty inspector cannot submit
        try:
            submit_inspection(unit1, op["50"], "", CHECK50_PASS)
            raise AssertionError("Empty inspector should not submit")
        except ValueError as e:
            print(f"[PASS] 1. Empty inspector cannot submit: {e}")

        # 2. Operation 40 must complete before inspecting 50
        start_operation(unit1, op["10"], "tester")
        try:
            submit_inspection(unit1, op["50"], "inspector", CHECK50_PASS)
            raise AssertionError("Should not inspect 50 before 40 completes")
        except ValueError as e:
            print(f"[PASS] 2. Operation 40 must complete before inspecting 50: {e}")

        _complete_10_to_40(unit1, op)

        # 3-8. Invalid check_results are all rejected
        invalid_cases = [
            ("empty dict", {}),
            ("missing item", {"base_rotation_ok": True, "joint_motion_ok": True, "gripper_motion_ok": True}),
            ("extra item", {"base_rotation_ok": True, "joint_motion_ok": True, "gripper_motion_ok": True, "no_interference": True, "extra_item": True}),
            ("string false", {"base_rotation_ok": "false", "joint_motion_ok": True, "gripper_motion_ok": True, "no_interference": True}),
            ("number 1", {"base_rotation_ok": 1, "joint_motion_ok": True, "gripper_motion_ok": True, "no_interference": True}),
            ("None", {"base_rotation_ok": None, "joint_motion_ok": True, "gripper_motion_ok": True, "no_interference": True}),
        ]
        for name, cr in invalid_cases:
            try:
                submit_inspection(unit1, op["50"], "inspector", cr)
                raise AssertionError(f"{name} should not pass inspection")
            except ValueError as e:
                print(f"[PASS] Invalid input rejected ({name}): {e}")

        # 9. Invalid input produces no records
        qr, pe, d = _counts(unit1, op["50"])
        assert qr == 0 and pe == 0 and d == 0, f"Expected zero records, got qr={qr} pe={pe} d={d}"
        print("[PASS] 9. Invalid input produces no records")

        # 10. Valid all-bool (with False) -> fail, create open defect, unit rework
        res = submit_inspection(unit1, op["50"], "inspector", CHECK50_FAIL,
                                defect_type="joint failure",
                                defect_description="joint motion test failed",
                                severity="major")
        assert res["result"] == "fail"
        print(f"[PASS] 10. Valid all-bool input judged fail (attempt {res['attempt_no']})")

        conn = get_connection()
        defects = conn.execute("SELECT defect_id, status FROM defects WHERE unit_id = ?", (unit1,)).fetchall()
        u = conn.execute("SELECT status FROM units WHERE unit_id = ?", (unit1,)).fetchone()
        conn.close()
        assert len(defects) == 1 and defects[0]["status"] == "open"
        assert u["status"] == "rework", f"Expected rework, got {u['status']}"
        defect_id = defects[0]["defect_id"]
        print("[PASS] fail automatically creates an open defect")
        print("[PASS] unit becomes rework")

        # 11. Operation 50 is Defect Open and operation 60 stays Locked after FAIL
        progress = get_unit_progress(unit1)["progress"]
        state_50 = next(p["state"] for p in progress if p["operation_code"] == "50")
        state_60 = next(p["state"] for p in progress if p["operation_code"] == "60")
        assert state_50 == "Defect Open", f"Expected Defect Open, got {state_50}"
        assert state_60 == "Locked", f"Expected Locked, got {state_60}"
        print("[PASS] 11. Operation 50 is Defect Open and operation 60 stays Locked after FAIL")

        # 12. Cannot reinspect while an open defect exists
        _set_unit_status(unit1, "in_production")
        try:
            submit_inspection(unit1, op["50"], "inspector", CHECK50_PASS)
            raise AssertionError("Should not reinspect with an open defect")
        except ValueError as e:
            print(f"[PASS] 12. Cannot reinspect with an open defect: {e}")

        # 13. start_rework sets status to in_rework
        start_rework(defect_id)
        conn = get_connection()
        drow = conn.execute("SELECT status FROM defects WHERE defect_id = ?", (defect_id,)).fetchone()
        conn.close()
        assert drow["status"] == "in_rework"
        print("[PASS] 13. start_rework sets status to in_rework")

        # 14. Cannot close without rework_notes
        try:
            close_rework(defect_id, "")
            raise AssertionError("Should not close without rework_notes")
        except ValueError as e:
            print(f"[PASS] 14. Cannot close without rework_notes: {e}")

        # 15. Closing restores unit to in_production
        close_rework(defect_id, "joint re-aligned and retested")
        conn = get_connection()
        drow = conn.execute("SELECT status FROM defects WHERE defect_id = ?", (defect_id,)).fetchone()
        u = conn.execute("SELECT status FROM units WHERE unit_id = ?", (unit1,)).fetchone()
        conn.close()
        assert drow["status"] == "closed"
        assert u["status"] == "in_production", f"Expected in_production, got {u['status']}"
        print("[PASS] 15. Closing restores unit to in_production")

        # 16. Second inspection has attempt_no=2
        res2 = submit_inspection(unit1, op["50"], "inspector", CHECK50_PASS)
        assert res2["result"] == "pass"
        assert res2["attempt_no"] == 2, f"Expected attempt_no 2, got {res2['attempt_no']}"
        attempts_50 = [r["attempt_no"] for r in list_quality_records(unit1) if r["operation_code"] == "50"]
        assert attempts_50 == [1, 2], f"Expected attempts 1,2, got {attempts_50}"
        print(f"[PASS] 16. Second inspection has attempt_no=2: {attempts_50}")

        # 17. Operation 50 pass unlocks 60
        res3 = submit_inspection(unit1, op["60"], "inspector", CHECK60_PASS)
        assert res3["result"] == "pass"
        print("[PASS] 17. Operation 50 pass unlocks 60 (inspection 60 succeeded)")

        # 18. Operation 60 pass completes the unit
        conn = get_connection()
        u = conn.execute("SELECT status FROM units WHERE unit_id = ?", (unit1,)).fetchone()
        conn.close()
        assert u["status"] == "completed", f"Expected completed, got {u['status']}"
        print("[PASS] 18. Operation 60 pass completes the unit")

        # 19. Work order completes when all units are done
        conn = get_connection()
        wo = conn.execute("SELECT status FROM work_orders WHERE work_order_id = ?", (wid1,)).fetchone()
        conn.close()
        assert wo["status"] == "completed", f"Expected completed, got {wo['status']}"
        print("[PASS] 19. Work order completes when all units are done")

        # ===== Scenario 2: first PASS + duplicate submission rejected + state priority =====
        wid2 = create_work_order(product_id, 1, "2026-09-10")
        wids.append(wid2)
        release_work_order(wid2)
        unit2 = list_units_for_order(wid2)[0]["unit_id"]

        start_operation(unit2, op["10"], "tester")
        _complete_10_to_40(unit2, op)

        # 20. Operation 50 first PASS succeeds
        res = submit_inspection(unit2, op["50"], "inspector", CHECK50_PASS)
        assert res["result"] == "pass" and res["attempt_no"] == 1
        print("[PASS] 20. Operation 50 first PASS succeeds (attempt 1)")

        # 21. Re-submitting operation 50 must raise ValueError
        try:
            submit_inspection(unit2, op["50"], "inspector", CHECK50_PASS)
            raise AssertionError("Operation 50 should not be reinspected after PASS")
        except ValueError as e:
            print(f"[PASS] 21. Re-submitting operation 50 after PASS rejected: {e}")

        # 22. Operation 50 has only 1 quality_record after rejection
        records50 = [r for r in list_quality_records(unit2) if r["operation_code"] == "50"]
        assert len(records50) == 1, f"Expected 1 record, got {len(records50)}"
        print("[PASS] 22. Operation 50 has only 1 quality_record after rejection")

        # 23. Operation 50 has only one start/complete pair for attempt 1
        conn = get_connection()
        pe = conn.execute(
            "SELECT event_type FROM production_events WHERE unit_id = ? AND operation_id = ? ORDER BY event_id",
            (unit2, op["50"]),
        ).fetchall()
        conn.close()
        events = [r["event_type"] for r in pe]
        assert events == ["start", "complete"], f"Expected one start/complete pair, got {events}"
        print("[PASS] 23. Operation 50 has only one start/complete pair for attempt 1")

        # 24. attempt_no of a passed operation cannot increase
        conn = get_connection()
        max_attempt = conn.execute(
            "SELECT MAX(attempt_no) AS m FROM quality_records WHERE unit_id = ? AND operation_id = ?",
            (unit2, op["50"]),
        ).fetchone()["m"]
        conn.close()
        assert max_attempt == 1, f"attempt_no should not increase, got {max_attempt}"
        print("[PASS] 24. attempt_no of a passed operation cannot increase")

        # 25. With a PASS and an open defect, operation 50 is Defect Open and 60 stays Locked
        conn = get_connection()
        qr50 = conn.execute(
            "SELECT quality_id FROM quality_records WHERE unit_id = ? AND operation_id = ? ORDER BY quality_id DESC LIMIT 1",
            (unit2, op["50"]),
        ).fetchone()
        conn.execute(
            "INSERT INTO defects (quality_id, unit_id, defect_type, description, severity, status) "
            "VALUES (?, ?, 'anomaly', 'post-pass defect', 'minor', 'open')",
            (qr50["quality_id"], unit2),
        )
        conn.commit()
        conn.close()

        progress = get_unit_progress(unit2)["progress"]
        state_50 = next(p["state"] for p in progress if p["operation_code"] == "50")
        state_60 = next(p["state"] for p in progress if p["operation_code"] == "60")
        assert state_50 == "Defect Open", f"Expected Defect Open, got {state_50}"
        assert state_60 == "Locked", f"Expected Locked, got {state_60}"
        print("[PASS] 25. With a PASS and an open defect, operation 50 is Defect Open and 60 stays Locked")

        # 26. foreign_key_check = 0
        conn = get_connection()
        fks = conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.close()
        assert len(fks) == 0, f"Foreign key violations: {fks}"
        print("[PASS] 26. foreign_key_check = 0")

        print("ALL TESTS PASSED")
    finally:
        _cleanup(wids)
        print(f"[CLEANUP] Deleted test work orders {wids} and their related data")


if __name__ == "__main__":
    main()
