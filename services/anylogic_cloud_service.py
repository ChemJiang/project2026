"""Read-only access to AnyLogic evidence bundled inside the application."""
from pathlib import Path

import pandas as pd


APP_DIR = Path(__file__).resolve().parent.parent
ANYLOGIC_DIR = APP_DIR / "data" / "anylogic"

PROCESS_ROUTING_XLSX = (
    ANYLOGIC_DIR / "robotic_arm_process_routing_2_with_30_replications_checked.xlsx"
)
SCENARIO_IMAGES = {
    "S1": ANYLOGIC_DIR / "anylogic_high_demand_2operators.png",
    "S2": ANYLOGIC_DIR / "anylogic_high_demand_3operators.png",
}
SOURCE_ALP = ANYLOGIC_DIR / "RoboticArmMES.alp"


class AnyLogicDataError(Exception):
    """Raised when the bundled AnyLogic evidence cannot be read."""


def _read_sheet(sheet_name):
    if not PROCESS_ROUTING_XLSX.is_file():
        raise AnyLogicDataError(
            f"AnyLogic source file missing: {PROCESS_ROUTING_XLSX.name}"
        )
    return pd.ExcelFile(PROCESS_ROUTING_XLSX).parse(sheet_name)


def get_process_routing():
    """Return the six operations with times, distributions and resource pools."""
    df = _read_sheet("Sheet1")
    rows = []
    for _, row in df.iterrows():
        operation_no = row.get("No.")
        if pd.isna(operation_no):
            continue
        rows.append(
            {
                "operation_no": int(operation_no),
                "name_zh": str(row.get("工序名称")),
                "name_en": str(row.get("Name")),
                "min_time": float(row.get("Min_Time_min")),
                "base_time": float(row.get("Base_Time_min")),
                "max_time": float(row.get("Max_Time_min")),
                "distribution": str(row.get("AnyLogic_Distribution")),
                "worker_pool": str(row.get("Worker_Pool")),
                "workers_required": int(row.get("Workers_Required")),
                "station_pool": str(row.get("Station_Pool")),
                "stations_required": int(row.get("Stations_Required")),
            }
        )
    return rows


def get_resource_capacity():
    """Return the worker and station resource pools."""
    df = _read_sheet("Resource_Capacity")
    rows = []
    for _, row in df.iterrows():
        rows.append(
            {
                "resource_pool": str(row.get("Resource_Pool")),
                "type": str(row.get("Type")),
                "capacity": int(row.get("Capacity")),
                "used_by": str(row.get("Used_By_Operations")),
                "description": str(row.get("Description")),
            }
        )
    return rows


def get_model_flow():
    """Return the AnyLogic model flow string."""
    try:
        df = _read_sheet("AnyLogic_Setup")
    except AnyLogicDataError:
        return "Source → 10 → 20 → 30 → 40 → 50 → 60 → Sink"
    for _, row in df.iterrows():
        if str(row.get("Item")).strip().lower() == "model flow":
            return str(row.get("Configuration"))
    return "Source → 10 → 20 → 30 → 40 → 50 → 60 → Sink"
