"""Production reporting logic: start / complete operations in sequence order."""
from database.db import get_connection, now_str
from services.quality_service import quality_accepted

# Quality gates (Functional Testing / Final Inspection): completed via quality_records
# in this phase, not through the regular complete_operation, to avoid bypassing quality checks.
QUALITY_GATE_CODES = ("50", "60")


def _validate_operator(operator):
    """Validate and normalize the operator: must not be None, empty, or whitespace-only."""
    if operator is None or not str(operator).strip():
        raise ValueError("Operator is required.")
    return str(operator).strip()


def _get_product_operations(conn, product_id):
    rows = conn.execute(
        "SELECT operation_id, operation_code, operation_name, sequence, "
        "       min_time_min, base_time_min, max_time_min, worker, station "
        "FROM operations WHERE product_id = ? ORDER BY sequence",
        (product_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _has_event(conn, unit_id, operation_id, event_type):
    row = conn.execute(
        "SELECT 1 FROM production_events "
        "WHERE unit_id = ? AND operation_id = ? AND event_type = ?",
        (unit_id, operation_id, event_type),
    ).fetchone()
    return row is not None


def list_active_work_orders():
    """Work orders that are released or in progress."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT wo.work_order_id, wo.work_order_code, p.product_code, wo.status "
            "FROM work_orders wo JOIN products p ON p.product_id = wo.product_id "
            "WHERE wo.status IN ('released', 'in_progress') "
            "ORDER BY wo.work_order_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_units_for_order(work_order_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT unit_id, serial_number, status FROM units "
            "WHERE work_order_id = ? ORDER BY unit_id",
            (work_order_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _has_pass(conn, unit_id, operation_id):
    row = conn.execute(
        "SELECT 1 FROM quality_records "
        "WHERE unit_id = ? AND operation_id = ? AND result = 'pass'",
        (unit_id, operation_id),
    ).fetchone()
    return row is not None


def _open_defect(conn, unit_id, operation_id):
    row = conn.execute(
        "SELECT d.status FROM defects d "
        "JOIN quality_records q ON q.quality_id = d.quality_id "
        "WHERE d.unit_id = ? AND q.operation_id = ? AND d.status IN ('open', 'in_rework') "
        "ORDER BY d.defect_id DESC LIMIT 1",
        (unit_id, operation_id),
    ).fetchone()
    return dict(row) if row else None


def get_unit_progress(unit_id):
    """Return the unit information and the progress state of its operations."""
    conn = get_connection()
    try:
        unit = conn.execute(
            "SELECT unit_id, serial_number, work_order_id, product_id, status "
            "FROM units WHERE unit_id = ?",
            (unit_id,),
        ).fetchone()
        if unit is None:
            raise ValueError(f"Unit {unit_id} does not exist.")

        ops = _get_product_operations(conn, unit["product_id"])
        progress = []
        for i, op in enumerate(ops):
            if op["operation_code"] in QUALITY_GATE_CODES:
                state = _quality_state(conn, unit_id, op, ops, i)
            else:
                state = _normal_state(conn, unit_id, op, ops, i)
            progress.append({**op, "state": state})

        return {"unit": dict(unit), "progress": progress}
    finally:
        conn.close()


def _normal_state(conn, unit_id, op, ops, i):
    if _has_event(conn, unit_id, op["operation_id"], "complete"):
        return "Completed"
    if _has_event(conn, unit_id, op["operation_id"], "start"):
        return "In Progress"
    prev_done = True if i == 0 else _has_event(conn, unit_id, ops[i - 1]["operation_id"], "complete")
    return "Ready" if prev_done else "Locked"


def _quality_state(conn, unit_id, op, ops, i):
    prev_op = ops[i - 1]
    if prev_op["operation_code"] in QUALITY_GATE_CODES:
        prev_accepted = quality_accepted(conn, unit_id, prev_op["operation_id"])
    else:
        prev_accepted = _has_event(conn, unit_id, prev_op["operation_id"], "complete")

    if not prev_accepted:
        return "Locked"

    defect = _open_defect(conn, unit_id, op["operation_id"])
    if defect:
        return "Rework" if defect["status"] == "in_rework" else "Defect Open"

    if _has_pass(conn, unit_id, op["operation_id"]):
        return "Completed"

    return "Quality Required"


def start_operation(unit_id, operation_id, operator):
    """Start an operation: write a start event; the first operation also advances unit/work order status."""
    operator = _validate_operator(operator)
    conn = get_connection()
    try:
        unit = conn.execute(
            "SELECT unit_id, work_order_id, product_id, status FROM units WHERE unit_id = ?",
            (unit_id,),
        ).fetchone()
        if unit is None:
            raise ValueError(f"Unit {unit_id} does not exist.")
        if unit["status"] not in ("queued", "in_production"):
            raise ValueError(
                f"Unit status is {unit['status']}; only queued/in_production can be started."
            )

        ops = _get_product_operations(conn, unit["product_id"])
        idx = next((i for i, o in enumerate(ops) if o["operation_id"] == operation_id), None)
        if idx is None:
            raise ValueError(f"Operation {operation_id} does not belong to this product.")
        op = ops[idx]

        # Sequence constraint: the previous operation must be completed.
        if idx > 0 and not _has_event(conn, unit_id, ops[idx - 1]["operation_id"], "complete"):
            raise ValueError(
                f"Operation {ops[idx - 1]['operation_code']} must be completed before "
                f"operation {op['operation_code']} can start."
            )
        if _has_event(conn, unit_id, operation_id, "complete"):
            raise ValueError(f"Operation {op['operation_code']} has already been completed.")
        if _has_event(conn, unit_id, operation_id, "start"):
            raise ValueError(f"Operation {op['operation_code']} has already been started.")

        conn.execute(
            "INSERT INTO production_events (unit_id, operation_id, event_type, occurred_at, operator) "
            "VALUES (?, ?, 'start', ?, ?)",
            (unit_id, operation_id, now_str(), operator),
        )

        if idx == 0:
            conn.execute(
                "UPDATE units SET status = 'in_production' WHERE unit_id = ? AND status = 'queued'",
                (unit_id,),
            )
        conn.execute(
            "UPDATE work_orders SET status = 'in_progress' "
            "WHERE work_order_id = ? AND status = 'released'",
            (unit["work_order_id"],),
        )

        conn.commit()
        return op
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def complete_operation(unit_id, operation_id, operator):
    """Complete an operation: write a complete event. Quality gates 50/60 cannot be completed normally."""
    operator = _validate_operator(operator)
    conn = get_connection()
    try:
        unit = conn.execute(
            "SELECT product_id, status FROM units WHERE unit_id = ?", (unit_id,)
        ).fetchone()
        if unit is None:
            raise ValueError(f"Unit {unit_id} does not exist.")
        if unit["status"] != "in_production":
            raise ValueError(
                f"Unit status is {unit['status']}; only in_production can be completed."
            )

        op = conn.execute(
            "SELECT operation_id, operation_code, operation_name FROM operations "
            "WHERE operation_id = ? AND product_id = ?",
            (operation_id, unit["product_id"]),
        ).fetchone()
        if op is None:
            raise ValueError(f"Operation {operation_id} does not belong to this product.")

        if op["operation_code"] in QUALITY_GATE_CODES:
            raise ValueError(
                f"Operation {op['operation_code']} {op['operation_name']} requires a quality "
                "record and cannot be completed normally."
            )
        if not _has_event(conn, unit_id, operation_id, "start"):
            raise ValueError(f"Operation {op['operation_code']} has not been started.")
        if _has_event(conn, unit_id, operation_id, "complete"):
            raise ValueError(f"Operation {op['operation_code']} has already been completed.")

        conn.execute(
            "INSERT INTO production_events (unit_id, operation_id, event_type, occurred_at, operator) "
            "VALUES (?, ?, 'complete', ?, ?)",
            (unit_id, operation_id, now_str(), operator),
        )
        conn.commit()
        return op
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
