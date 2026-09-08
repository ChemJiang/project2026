"""Production traceability query (read-only)."""
from database.db import get_connection
from services.production_service import get_unit_progress


def list_all_units():
    """Return a summary of all units (for the selector)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT u.unit_id, u.serial_number, u.status, u.created_at, "
            "p.product_code, p.product_name, wo.work_order_code "
            "FROM units u "
            "JOIN products p ON p.product_id = u.product_id "
            "JOIN work_orders wo ON wo.work_order_id = u.work_order_id "
            "ORDER BY u.unit_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_unit_traceability(serial_number):
    """Query the complete production history of a single unit.

    Raises ValueError if the serial number does not exist. All SQL is parameterized.
    """
    conn = get_connection()
    try:
        unit_row = conn.execute(
            "SELECT unit_id, serial_number, work_order_id, product_id, status, created_at "
            "FROM units WHERE serial_number = ?",
            (serial_number,),
        ).fetchone()
        if unit_row is None:
            raise ValueError(f"Serial number {serial_number} does not exist.")
        unit_id = unit_row["unit_id"]

        product = conn.execute(
            "SELECT product_id, product_code, product_name FROM products WHERE product_id = ?",
            (unit_row["product_id"],),
        ).fetchone()

        wo = conn.execute(
            "SELECT work_order_id, work_order_code, product_id, quantity, status, "
            "planned_start, planned_end, created_at, released_at "
            "FROM work_orders WHERE work_order_id = ?",
            (unit_row["work_order_id"],),
        ).fetchone()

        operations = get_unit_progress(unit_id)["progress"]

        events = conn.execute(
            "SELECT pe.event_id, pe.attempt_no, pe.event_type, pe.operator, pe.occurred_at, pe.notes, "
            "o.operation_code, o.operation_name "
            "FROM production_events pe "
            "JOIN operations o ON o.operation_id = pe.operation_id "
            "WHERE pe.unit_id = ? "
            "ORDER BY pe.occurred_at, pe.event_id",
            (unit_id,),
        ).fetchall()

        quality = conn.execute(
            "SELECT qr.quality_id, qr.attempt_no, qr.inspection_type, qr.result, "
            "qr.measurement, qr.notes, qr.inspected_at, qr.inspector, "
            "o.operation_code, o.operation_name "
            "FROM quality_records qr "
            "JOIN operations o ON o.operation_id = qr.operation_id "
            "WHERE qr.unit_id = ? "
            "ORDER BY qr.quality_id",
            (unit_id,),
        ).fetchall()

        defects = conn.execute(
            "SELECT d.defect_id, d.defect_type, d.description, d.severity, d.status, "
            "d.created_at, d.closed_at, d.rework_notes, "
            "o.operation_code, o.operation_name "
            "FROM defects d "
            "JOIN quality_records qr ON qr.quality_id = d.quality_id "
            "JOIN operations o ON o.operation_id = qr.operation_id "
            "WHERE d.unit_id = ? "
            "ORDER BY d.defect_id",
            (unit_id,),
        ).fetchall()

        return {
            "unit": dict(unit_row),
            "product": dict(product),
            "work_order": dict(wo),
            "operations": operations,
            "production_events": [dict(e) for e in events],
            "quality_records": [dict(q) for q in quality],
            "defects": [dict(d) for d in defects],
        }
    finally:
        conn.close()
