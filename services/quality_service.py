"""Quality inspection and defect rework logic."""
import json

from database.db import get_connection, now_str

QUALITY_GATE_CODES = ("50", "60")

CHECK_ITEMS = {
    "50": ["base_rotation_ok", "joint_motion_ok", "gripper_motion_ok", "no_interference"],
    "60": ["appearance_ok", "connections_ok", "test_record_complete"],
}

INSPECTION_TYPE = {"50": "functional_test", "60": "final_inspection"}

SEVERITIES = ("minor", "major", "critical")


def _validate_inspector(inspector):
    if inspector is None or not str(inspector).strip():
        raise ValueError("Inspector is required.")
    return str(inspector).strip()


def _has_event(conn, unit_id, operation_id, event_type):
    row = conn.execute(
        "SELECT 1 FROM production_events "
        "WHERE unit_id = ? AND operation_id = ? AND event_type = ?",
        (unit_id, operation_id, event_type),
    ).fetchone()
    return row is not None


def _has_pass(conn, unit_id, operation_id):
    row = conn.execute(
        "SELECT 1 FROM quality_records "
        "WHERE unit_id = ? AND operation_id = ? AND result = 'pass'",
        (unit_id, operation_id),
    ).fetchone()
    return row is not None


def _has_open_defect(conn, unit_id, operation_id):
    row = conn.execute(
        "SELECT 1 FROM defects d "
        "JOIN quality_records q ON q.quality_id = d.quality_id "
        "WHERE d.unit_id = ? AND q.operation_id = ? AND d.status IN ('open', 'in_rework')",
        (unit_id, operation_id),
    ).fetchone()
    return row is not None


def quality_accepted(conn, unit_id, operation_id):
    """Whether a quality operation has been accepted: has a PASS record and no open defect."""
    return _has_pass(conn, unit_id, operation_id) and not _has_open_defect(conn, unit_id, operation_id)


def _validate_check_results(operation_code, check_results):
    """Strictly validate inspection items: dict type, exact key set, strictly boolean values."""
    if not isinstance(check_results, dict):
        raise ValueError("check_results must be a dict.")

    expected_items = CHECK_ITEMS[operation_code]
    expected_set = set(expected_items)
    actual_set = set(check_results.keys())

    if actual_set != expected_set:
        missing = sorted(expected_set - actual_set)
        extra = sorted(actual_set - expected_set)
        msg = []
        if missing:
            msg.append(f"Missing inspection items: {missing}")
        if extra:
            msg.append(f"Unexpected inspection items: {extra}")
        raise ValueError("; ".join(msg))

    for item in expected_items:
        v = check_results[item]
        if type(v) is not bool:
            raise ValueError(f"Inspection item {item} must be a boolean, got {type(v).__name__}.")

    return {item: check_results[item] for item in expected_items}


def submit_inspection(unit_id, operation_id, inspector, check_results, notes=None,
                      defect_type=None, defect_description=None, severity="minor"):
    """Submit a quality inspection: automatically determine pass/fail and write quality_records and production_events.

    On failure, automatically create a defect and set the unit to rework; on operation 60 pass,
    complete the unit and work order.
    """
    inspector = _validate_inspector(inspector)
    conn = get_connection()
    try:
        unit = conn.execute(
            "SELECT unit_id, work_order_id, product_id, status FROM units WHERE unit_id = ?",
            (unit_id,),
        ).fetchone()
        if unit is None:
            raise ValueError(f"Unit {unit_id} does not exist.")
        if unit["status"] != "in_production":
            raise ValueError(f"Unit status is {unit['status']}; only in_production can be inspected.")

        op = conn.execute(
            "SELECT operation_id, operation_code, operation_name FROM operations "
            "WHERE operation_id = ? AND product_id = ?",
            (operation_id, unit["product_id"]),
        ).fetchone()
        if op is None:
            raise ValueError(f"Operation {operation_id} does not belong to this product.")
        if op["operation_code"] not in QUALITY_GATE_CODES:
            raise ValueError(f"Operation {op['operation_code']} is not a quality operation.")

        # Unlock validation
        if op["operation_code"] == "50":
            op40 = conn.execute(
                "SELECT operation_id FROM operations WHERE product_id = ? AND operation_code = '40'",
                (unit["product_id"],),
            ).fetchone()
            if op40 is None or not _has_event(conn, unit_id, op40["operation_id"], "complete"):
                raise ValueError("Operation 40 must be completed before operation 50 can be inspected.")
        else:  # 60
            op50 = conn.execute(
                "SELECT operation_id FROM operations WHERE product_id = ? AND operation_code = '50'",
                (unit["product_id"],),
            ).fetchone()
            if op50 is None or not quality_accepted(conn, unit_id, op50["operation_id"]):
                raise ValueError("Operation 50 must pass (with no open defect) before operation 60 can be inspected.")

        if _has_open_defect(conn, unit_id, operation_id):
            raise ValueError("Reinspection is not allowed while an open defect exists.")

        if _has_pass(conn, unit_id, operation_id):
            raise ValueError("This quality operation has already passed and cannot be inspected again.")

        # Compute attempt_no
        row = conn.execute(
            "SELECT MAX(attempt_no) AS m FROM quality_records "
            "WHERE unit_id = ? AND operation_id = ?",
            (unit_id, operation_id),
        ).fetchone()
        attempt_no = (row["m"] or 0) + 1

        # Strictly validate inspection items
        expected_items = CHECK_ITEMS[op["operation_code"]]
        check_results = _validate_check_results(op["operation_code"], check_results)

        # Automatically determine pass/fail
        result = "pass" if all(check_results[item] for item in expected_items) else "fail"
        if result == "fail":
            if not defect_type or not str(defect_type).strip():
                raise ValueError("Defect type is required for a failed inspection.")
            if not defect_description or not str(defect_description).strip():
                raise ValueError("Description is required for a failed inspection.")
            if severity not in SEVERITIES:
                raise ValueError(f"Invalid severity: {severity}")

        measurement = json.dumps(check_results, ensure_ascii=False)
        cur = conn.execute(
            "INSERT INTO quality_records "
            "(unit_id, operation_id, attempt_no, inspection_type, result, measurement, notes, inspected_at, inspector) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (unit_id, operation_id, attempt_no, INSPECTION_TYPE[op["operation_code"]],
             result, measurement, notes, now_str(), inspector),
        )
        quality_id = cur.lastrowid

        # Also write the start and complete production_events for this attempt
        conn.execute(
            "INSERT INTO production_events (unit_id, operation_id, attempt_no, event_type, occurred_at, operator) "
            "VALUES (?, ?, ?, 'start', ?, ?)",
            (unit_id, operation_id, attempt_no, now_str(), inspector),
        )
        conn.execute(
            "INSERT INTO production_events (unit_id, operation_id, attempt_no, event_type, occurred_at, operator) "
            "VALUES (?, ?, ?, 'complete', ?, ?)",
            (unit_id, operation_id, attempt_no, now_str(), inspector),
        )

        if result == "fail":
            conn.execute(
                "INSERT INTO defects (quality_id, unit_id, defect_type, description, severity, status) "
                "VALUES (?, ?, ?, ?, ?, 'open')",
                (quality_id, unit_id, defect_type, defect_description, severity),
            )
            conn.execute("UPDATE units SET status = 'rework' WHERE unit_id = ?", (unit_id,))
        else:
            if op["operation_code"] == "60":
                conn.execute("UPDATE units SET status = 'completed' WHERE unit_id = ?", (unit_id,))
                total = conn.execute(
                    "SELECT COUNT(*) AS c FROM units WHERE work_order_id = ?",
                    (unit["work_order_id"],),
                ).fetchone()["c"]
                done = conn.execute(
                    "SELECT COUNT(*) AS c FROM units WHERE work_order_id = ? AND status = 'completed'",
                    (unit["work_order_id"],),
                ).fetchone()["c"]
                if total == done:
                    conn.execute(
                        "UPDATE work_orders SET status = 'completed' WHERE work_order_id = ?",
                        (unit["work_order_id"],),
                    )

        conn.commit()
        return {"quality_id": quality_id, "attempt_no": attempt_no, "result": result}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_inspection_work_orders():
    """Work orders eligible for inspection: released / in_progress / completed."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT wo.work_order_id, wo.work_order_code, p.product_code, wo.status "
            "FROM work_orders wo JOIN products p ON p.product_id = wo.product_id "
            "WHERE wo.status IN ('released', 'in_progress', 'completed') "
            "ORDER BY wo.work_order_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_quality_records(unit_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT qr.quality_id, qr.attempt_no, qr.inspection_type, qr.result, "
            "qr.measurement, qr.notes, qr.inspected_at, qr.inspector, "
            "o.operation_code, o.operation_name "
            "FROM quality_records qr JOIN operations o ON o.operation_id = qr.operation_id "
            "WHERE qr.unit_id = ? ORDER BY qr.quality_id",
            (unit_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_defects(unit_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT d.defect_id, d.defect_type, d.description, d.severity, d.status, "
            "d.created_at, d.closed_at, d.rework_notes, "
            "o.operation_code, o.operation_name "
            "FROM defects d "
            "JOIN quality_records q ON q.quality_id = d.quality_id "
            "JOIN operations o ON o.operation_id = q.operation_id "
            "WHERE d.unit_id = ? ORDER BY d.defect_id",
            (unit_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def start_rework(defect_id):
    conn = get_connection()
    try:
        d = conn.execute(
            "SELECT defect_id, status FROM defects WHERE defect_id = ?", (defect_id,)
        ).fetchone()
        if d is None:
            raise ValueError(f"Defect {defect_id} does not exist.")
        if d["status"] != "open":
            raise ValueError(f"Defect status is {d['status']}; only open defects can start rework.")
        conn.execute("UPDATE defects SET status = 'in_rework' WHERE defect_id = ?", (defect_id,))
        conn.commit()
        return {"defect_id": defect_id, "status": "in_rework"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def close_rework(defect_id, rework_notes):
    conn = get_connection()
    try:
        d = conn.execute(
            "SELECT defect_id, unit_id, status FROM defects WHERE defect_id = ?", (defect_id,)
        ).fetchone()
        if d is None:
            raise ValueError(f"Defect {defect_id} does not exist.")
        if d["status"] != "in_rework":
            raise ValueError(f"Defect status is {d['status']}; only in_rework defects can be closed.")
        if rework_notes is None or not str(rework_notes).strip():
            raise ValueError("Rework notes are required to close the defect.")

        conn.execute(
            "UPDATE defects SET status = 'closed', closed_at = ?, rework_notes = ? WHERE defect_id = ?",
            (now_str(), str(rework_notes).strip(), defect_id),
        )
        remaining = conn.execute(
            "SELECT 1 FROM defects WHERE unit_id = ? AND status IN ('open', 'in_rework')",
            (d["unit_id"],),
        ).fetchone()
        if remaining is None:
            conn.execute(
                "UPDATE units SET status = 'in_production' WHERE unit_id = ? AND status = 'rework'",
                (d["unit_id"],),
            )
        conn.commit()
        return {"defect_id": defect_id, "status": "closed"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
