"""Work order creation, release, serial number generation, and query logic."""
from datetime import datetime

from database.db import get_connection, now_str


def _next_work_order_code(conn, date_str):
    """Generate a unique work order code in the format WO-YYYYMMDD-001."""
    prefix = f"WO-{date_str}-"
    row = conn.execute(
        "SELECT work_order_code FROM work_orders "
        "WHERE work_order_code LIKE ? ORDER BY work_order_code DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    seq = 1 if row is None else int(row["work_order_code"][len(prefix):]) + 1
    return f"{prefix}{seq:03d}"


def _next_serial_batch(conn, count, date_str):
    """Generate `count` consecutive unique serial numbers in the format AM-YYYYMMDD-001."""
    prefix = f"AM-{date_str}-"
    row = conn.execute(
        "SELECT serial_number FROM units "
        "WHERE serial_number LIKE ? ORDER BY serial_number DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    seq = 1 if row is None else int(row["serial_number"][len(prefix):]) + 1
    return [f"{prefix}{seq + i:03d}" for i in range(count)]


def create_work_order(product_id, planned_quantity, due_date):
    """Create a DRAFT work order (without generating units) and return its work_order_id."""
    conn = get_connection()
    try:
        date_str = datetime.now().strftime("%Y%m%d")
        code = _next_work_order_code(conn, date_str)
        cur = conn.execute(
            "INSERT INTO work_orders (work_order_code, product_id, quantity, status, planned_end) "
            "VALUES (?, ?, ?, 'draft', ?)",
            (code, product_id, planned_quantity, due_date),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def release_work_order(work_order_id):
    """Release a DRAFT work order: set status to RELEASED and generate units (single transaction).

    Returns the list of generated serial numbers.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT status, quantity, product_id FROM work_orders WHERE work_order_id = ?",
            (work_order_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Work order {work_order_id} does not exist.")
        if row["status"] != "draft":
            raise ValueError(f"Only DRAFT work orders can be released. Current status: {row['status']}.")

        date_str = datetime.now().strftime("%Y%m%d")
        serials = _next_serial_batch(conn, row["quantity"], date_str)

        conn.execute(
            "UPDATE work_orders SET status = 'released', released_at = ? WHERE work_order_id = ?",
            (now_str(), work_order_id),
        )
        for sn in serials:
            conn.execute(
                "INSERT INTO units (serial_number, work_order_id, product_id, status) "
                "VALUES (?, ?, ?, 'queued')",
                (sn, work_order_id, row["product_id"]),
            )
        conn.commit()
        return serials
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_products():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT product_id, product_code, product_name FROM products ORDER BY product_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_work_orders():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT wo.work_order_id, wo.work_order_code, wo.quantity, wo.status, "
            "       wo.planned_end, wo.created_at, wo.released_at, "
            "       p.product_code, p.product_name, "
            "       (SELECT COUNT(*) FROM units u WHERE u.work_order_id = wo.work_order_id) AS unit_count "
            "FROM work_orders wo "
            "JOIN products p ON p.product_id = wo.product_id "
            "ORDER BY wo.work_order_id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_units(work_order_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT serial_number, status, created_at FROM units "
            "WHERE work_order_id = ? ORDER BY unit_id",
            (work_order_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
