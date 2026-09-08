"""MES Dashboard and AnyLogic simulation analysis (read-only)."""
from pathlib import Path

import pandas as pd

from database.db import get_connection

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RUNS_PATH = DATA_DIR / "simulation_repeated_runs.csv"
SUMMARY_PATH = DATA_DIR / "simulation_summary.csv"

REQUIRED_RUN_COLUMNS = [
    "Run_ID", "Scenario_ID", "Scenario_Name", "Seed", "Arrival_Interval_min",
    "Assembly_Capacity", "Planned_Orders", "Input_Units", "Completed_Units",
    "End_WIP", "Throughput_per_hour", "AssemblyOperator_Utilization",
    "Primary_Bottleneck", "Bottleneck_Utilization", "Run_Length_min",
]

REQUIRED_SUMMARY_COLUMNS = [
    "Scenario_ID", "Scenario_Name", "Replications", "Mean_Completed",
    "Completed_CI95_HalfWidth", "Mean_WIP", "Mean_Throughput",
    "Mean_Assembly_Util", "Dominant_Bottleneck", "Mean_Bottleneck_Util",
]

NUMERIC_RUN_COLUMNS = [
    "Seed", "Arrival_Interval_min", "Assembly_Capacity", "Planned_Orders",
    "Input_Units", "Completed_Units", "End_WIP", "Throughput_per_hour",
    "AssemblyOperator_Utilization", "Bottleneck_Utilization", "Run_Length_min",
]

NUMERIC_SUMMARY_COLUMNS = [
    "Replications", "Mean_Completed", "Completed_CI95_HalfWidth",
    "Mean_WIP", "Mean_Throughput", "Mean_Assembly_Util", "Mean_Bottleneck_Util",
]


def calculate_rate(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def get_mes_kpis():
    """Query core KPIs from the MES demonstration database (read-only)."""
    conn = get_connection()
    try:
        # Work orders
        work_order_total = conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0]
        work_order_status_counts = {
            r["status"]: r["c"]
            for r in conn.execute("SELECT status, COUNT(*) AS c FROM work_orders GROUP BY status").fetchall()
        }

        # Units
        unit_total = conn.execute("SELECT COUNT(*) FROM units").fetchone()[0]
        unit_status_counts = {
            r["status"]: r["c"]
            for r in conn.execute("SELECT status, COUNT(*) AS c FROM units GROUP BY status").fetchall()
        }
        completed_units = unit_status_counts.get("completed", 0)
        wip_units = (
            unit_status_counts.get("queued", 0)
            + unit_status_counts.get("in_production", 0)
            + unit_status_counts.get("rework", 0)
        )
        completion_rate = calculate_rate(completed_units, unit_total)

        # Production events (per operation)
        production_event_count = conn.execute("SELECT COUNT(*) FROM production_events").fetchone()[0]
        pe_by_op = {}
        for r in conn.execute(
            "SELECT o.operation_code, o.operation_name, pe.event_type, COUNT(*) AS c "
            "FROM production_events pe JOIN operations o ON o.operation_id = pe.operation_id "
            "GROUP BY o.operation_code, o.operation_name, pe.event_type "
            "ORDER BY o.operation_code"
        ).fetchall():
            key = r["operation_code"]
            entry = pe_by_op.setdefault(key, {
                "operation_code": r["operation_code"],
                "operation_name": r["operation_name"],
                "start_count": 0,
                "complete_count": 0,
            })
            if r["event_type"] == "start":
                entry["start_count"] = r["c"]
            else:
                entry["complete_count"] = r["c"]

        # Quality records
        quality_record_count = conn.execute("SELECT COUNT(*) FROM quality_records").fetchone()[0]
        quality_pass_count = conn.execute(
            "SELECT COUNT(*) FROM quality_records WHERE result = 'pass'"
        ).fetchone()[0]
        quality_fail_count = conn.execute(
            "SELECT COUNT(*) FROM quality_records WHERE result = 'fail'"
        ).fetchone()[0]
        inspection_pass_rate = calculate_rate(quality_pass_count, quality_record_count)

        # Defects
        defect_count = conn.execute("SELECT COUNT(*) FROM defects").fetchone()[0]
        open_defect_count = conn.execute(
            "SELECT COUNT(*) FROM defects WHERE status = 'open'"
        ).fetchone()[0]
        closed_defect_count = conn.execute(
            "SELECT COUNT(*) FROM defects WHERE status = 'closed'"
        ).fetchone()[0]

        return {
            "work_order_total": work_order_total,
            "work_order_status_counts": work_order_status_counts,
            "unit_total": unit_total,
            "unit_status_counts": unit_status_counts,
            "completed_units": completed_units,
            "wip_units": wip_units,
            "completion_rate": completion_rate,
            "production_event_count": production_event_count,
            "production_events_by_operation": list(pe_by_op.values()),
            "quality_record_count": quality_record_count,
            "quality_pass_count": quality_pass_count,
            "quality_fail_count": quality_fail_count,
            "inspection_pass_rate": inspection_pass_rate,
            "defect_count": defect_count,
            "open_defect_count": open_defect_count,
            "closed_defect_count": closed_defect_count,
        }
    finally:
        conn.close()


def load_simulation_runs():
    return pd.read_csv(RUNS_PATH)


def load_simulation_summary():
    return pd.read_csv(SUMMARY_PATH)


def validate_simulation_data():
    """Validate the AnyLogic CSV data; raise a clear ValueError on failure.

    Order: required fields -> numeric conversion (write back) -> fail fast on numeric errors
    -> row/scenario/Run_Length -> grouped-mean consistency.
    """
    runs = load_simulation_runs()
    summary = load_simulation_summary()
    errors = []

    # 1. Check required fields
    for col in REQUIRED_RUN_COLUMNS:
        if col not in runs.columns:
            errors.append(f"repeated runs is missing field: {col}")
    for col in REQUIRED_SUMMARY_COLUMNS:
        if col not in summary.columns:
            errors.append(f"summary is missing field: {col}")
    if errors:
        raise ValueError("; ".join(errors))

    # 2. Convert numeric fields and write back; record NaN as an error
    for col in NUMERIC_RUN_COLUMNS:
        converted = pd.to_numeric(runs[col], errors="coerce")
        if converted.isna().any():
            errors.append(f"repeated runs field {col} contains a non-numeric value.")
        else:
            runs[col] = converted
    for col in NUMERIC_SUMMARY_COLUMNS:
        converted = pd.to_numeric(summary[col], errors="coerce")
        if converted.isna().any():
            errors.append(f"summary field {col} contains a non-numeric value.")
        else:
            summary[col] = converted

    # 3. Fail fast on numeric errors to avoid confusing groupby/float exceptions
    if errors:
        raise ValueError("; ".join(errors))

    # 4. Row and scenario checks
    if len(runs) != 30:
        errors.append(f"repeated runs must have 30 rows, got {len(runs)}.")
    if len(summary) != 3:
        errors.append(f"summary must have 3 rows, got {len(summary)}.")
    for scenario in ("S0", "S1", "S2"):
        cnt = int((runs["Scenario_ID"] == scenario).sum())
        if cnt != 10:
            errors.append(f"{scenario} must have 10 runs, got {cnt}.")

    # 5. Run_Length check (values already converted)
    if not (runs["Run_Length_min"] == 480).all():
        errors.append("Run_Length_min must be 480 for all runs.")

    if errors:
        raise ValueError("; ".join(errors))

    # 6. Summary Mean_* must match grouped means from repeated runs
    for summary_col, run_col in [
        ("Mean_Completed", "Completed_Units"),
        ("Mean_WIP", "End_WIP"),
        ("Mean_Throughput", "Throughput_per_hour"),
        ("Mean_Assembly_Util", "AssemblyOperator_Utilization"),
    ]:
        group_means = runs.groupby("Scenario_ID")[run_col].mean()
        for _, row in summary.iterrows():
            sid = row["Scenario_ID"]
            if sid not in group_means.index:
                errors.append(f"summary scenario {sid} does not exist in repeated runs.")
                continue
            if abs(float(group_means[sid]) - float(row[summary_col])) > 0.001:
                errors.append(
                    f"{sid} {summary_col} mismatch: summary={row[summary_col]}, "
                    f"grouped mean={group_means[sid]:.6f}"
                )

    if errors:
        raise ValueError("; ".join(errors))

    return {"runs": runs, "summary": summary}


def get_scenario_comparison():
    """Return comparison data for the three scenarios (list)."""
    validated = validate_simulation_data()
    runs = validated["runs"]
    summary = validated["summary"]

    config = runs.groupby("Scenario_ID").agg(
        arrival_interval=("Arrival_Interval_min", "first"),
        assembly_capacity=("Assembly_Capacity", "first"),
    )
    config = {sid: row for sid, row in config.iterrows()}

    rows = []
    for _, r in summary.iterrows():
        sid = r["Scenario_ID"]
        rows.append({
            "scenario_id": sid,
            "scenario_name": r["Scenario_Name"],
            "arrival_interval": int(config[sid]["arrival_interval"]),
            "assembly_capacity": int(config[sid]["assembly_capacity"]),
            "mean_completed": float(r["Mean_Completed"]),
            "completed_ci95_half_width": float(r["Completed_CI95_HalfWidth"]),
            "mean_wip": float(r["Mean_WIP"]),
            "mean_throughput": float(r["Mean_Throughput"]),
            "mean_assembly_util": float(r["Mean_Assembly_Util"]),
            "dominant_bottleneck": r["Dominant_Bottleneck"],
            "mean_bottleneck_util": float(r["Mean_Bottleneck_Util"]),
        })
    return rows
