-- Agricultural robotic arm MES database schema
-- 9 tables: products, parts, bom, work_orders, units, operations,
--           production_events, quality_records, defects

PRAGMA foreign_keys = ON;

-- 1. Product master data
CREATE TABLE IF NOT EXISTS products (
    product_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code    TEXT    NOT NULL UNIQUE,
    product_name    TEXT    NOT NULL,
    description     TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 2. Part master data
CREATE TABLE IF NOT EXISTS parts (
    part_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    part_code       TEXT    NOT NULL UNIQUE,
    part_name       TEXT    NOT NULL,
    category        TEXT,
    specification   TEXT,
    unit            TEXT    NOT NULL DEFAULT 'pcs',
    supplier        TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 3. BOM (parts and quantities required by a product)
CREATE TABLE IF NOT EXISTS bom (
    bom_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(product_id),
    part_id         INTEGER NOT NULL REFERENCES parts(part_id),
    quantity        INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    UNIQUE (product_id, part_id)
);

-- 4. Production work orders
CREATE TABLE IF NOT EXISTS work_orders (
    work_order_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    work_order_code TEXT    NOT NULL UNIQUE,
    product_id      INTEGER NOT NULL REFERENCES products(product_id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    status          TEXT    NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'released', 'in_progress', 'completed', 'cancelled')),
    planned_start   TEXT,
    planned_end     TEXT,
    released_at     TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 5. Product instances (each physical robotic arm and its serial number)
CREATE TABLE IF NOT EXISTS units (
    unit_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    serial_number   TEXT    NOT NULL UNIQUE,
    work_order_id   INTEGER NOT NULL REFERENCES work_orders(work_order_id),
    product_id      INTEGER NOT NULL REFERENCES products(product_id),
    status          TEXT    NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'in_production', 'rework', 'completed', 'scrapped')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 6. Process route (the 6 defined assembly operations)
CREATE TABLE IF NOT EXISTS operations (
    operation_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id          INTEGER NOT NULL REFERENCES products(product_id),
    operation_code      TEXT    NOT NULL,
    operation_name      TEXT    NOT NULL,
    sequence            INTEGER NOT NULL,
    min_time_min        REAL,
    base_time_min       REAL,
    max_time_min        REAL,
    worker              TEXT,
    station             TEXT,
    description         TEXT,
    UNIQUE (product_id, operation_code)
);

-- 7. Production events (start/complete records per unit per operation)
CREATE TABLE IF NOT EXISTS production_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id         INTEGER NOT NULL REFERENCES units(unit_id),
    operation_id    INTEGER NOT NULL REFERENCES operations(operation_id),
    attempt_no      INTEGER NOT NULL DEFAULT 1,
    event_type      TEXT    NOT NULL CHECK (event_type IN ('start', 'complete')),
    occurred_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    operator        TEXT,
    notes           TEXT,
    UNIQUE (unit_id, operation_id, attempt_no, event_type)
);

-- 8. Quality records (functional test, final inspection and measurement results)
CREATE TABLE IF NOT EXISTS quality_records (
    quality_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id         INTEGER NOT NULL REFERENCES units(unit_id),
    operation_id    INTEGER NOT NULL REFERENCES operations(operation_id),
    attempt_no      INTEGER NOT NULL DEFAULT 1,
    inspection_type TEXT    NOT NULL CHECK (inspection_type IN ('functional_test', 'final_inspection')),
    result          TEXT    NOT NULL CHECK (result IN ('pass', 'fail')),
    measurement     TEXT,
    notes           TEXT,
    inspected_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    inspector       TEXT,
    UNIQUE (unit_id, operation_id, attempt_no)
);

-- 9. Defect records (nonconformances, rework, and closure status)
CREATE TABLE IF NOT EXISTS defects (
    defect_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    quality_id      INTEGER NOT NULL REFERENCES quality_records(quality_id),
    unit_id         INTEGER NOT NULL REFERENCES units(unit_id),
    defect_type     TEXT,
    description     TEXT,
    severity        TEXT    NOT NULL DEFAULT 'minor'
                    CHECK (severity IN ('minor', 'major', 'critical')),
    status          TEXT    NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'in_rework', 'closed')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    closed_at       TEXT,
    rework_notes    TEXT
);
