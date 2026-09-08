"""Dashboard and simulation analysis verification test (read-only; does not create/clean work orders)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection
from services.dashboard_service import (
    get_mes_kpis,
    calculate_rate,
    load_simulation_runs,
    load_simulation_summary,
    validate_simulation_data,
    get_scenario_comparison,
)


def _snapshot():
    conn = get_connection()
    c = {}
    for t in ["work_orders", "units", "production_events", "quality_records", "defects"]:
        c[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    conn.close()
    return c


def main():
    # 1. MES KPI query does not modify the database
    before = _snapshot()
    kpis = get_mes_kpis()
    after = _snapshot()
    assert before == after, f"KPI query modified the database: {before} -> {after}"
    print("[PASS] 1. MES KPI query does not modify the database")

    # 2. Division by zero handled via calculate_rate
    assert calculate_rate(0, 0) == 0.0
    assert calculate_rate(2, 3) == 2 / 3
    assert isinstance(kpis["completion_rate"], float)
    assert isinstance(kpis["inspection_pass_rate"], float)
    assert 0.0 <= kpis["completion_rate"] <= 1.0
    assert 0.0 <= kpis["inspection_pass_rate"] <= 1.0
    print("[PASS] 2. Division by zero handled")

    # 3. CSV has 30 runs and 3 scenarios
    runs = load_simulation_runs()
    summary = load_simulation_summary()
    assert len(runs) == 30, f"runs should have 30 rows, got {len(runs)}"
    assert len(summary) == 3, f"summary should have 3 rows, got {len(summary)}"
    print("[PASS] 3. CSV has 30 runs and 3 scenarios")

    # 4. Each scenario has exactly 10 runs
    for s in ("S0", "S1", "S2"):
        assert int((runs["Scenario_ID"] == s).sum()) == 10, f"{s} should have 10 runs"
    print("[PASS] 4. Each scenario has exactly 10 runs")

    validate_simulation_data()
    print("[PASS] validate_simulation_data passed")

    # Exception scenario: Completed_Units injected with "bad" must raise a ValueError containing the field name
    from unittest.mock import patch
    bad_runs = load_simulation_runs().copy()
    bad_runs["Completed_Units"] = bad_runs["Completed_Units"].astype(object)
    bad_runs.loc[0, "Completed_Units"] = "bad"
    with patch("services.dashboard_service.load_simulation_runs", return_value=bad_runs):
        try:
            validate_simulation_data()
            raise AssertionError("Completed_Units with invalid value should raise ValueError")
        except ValueError as e:
            assert "Completed_Units" in str(e), f"Error should mention Completed_Units, got: {e}"
            assert "agg function failed" not in str(e), "Should not expose pandas agg exception"
            print(f"[PASS] Completed_Units invalid value raises ValueError (field name included)")

    # Exception scenario: Mean_Completed injected with "bad" must raise a ValueError containing the field name
    bad_summary = load_simulation_summary().copy()
    bad_summary["Mean_Completed"] = bad_summary["Mean_Completed"].astype(object)
    bad_summary.loc[0, "Mean_Completed"] = "bad"
    with patch("services.dashboard_service.load_simulation_summary", return_value=bad_summary):
        try:
            validate_simulation_data()
            raise AssertionError("Mean_Completed with invalid value should raise ValueError")
        except ValueError as e:
            assert "Mean_Completed" in str(e), f"Error should mention Mean_Completed, got: {e}"
            print(f"[PASS] Mean_Completed invalid value raises ValueError (field name included)")

    # 5. S0 mean throughput is 1.75
    s0 = summary[summary["Scenario_ID"] == "S0"].iloc[0]
    assert abs(float(s0["Mean_Throughput"]) - 1.75) < 0.001
    print("[PASS] 5. S0 mean throughput is 1.75")

    # 6. S1 mean WIP is 11.5
    s1 = summary[summary["Scenario_ID"] == "S1"].iloc[0]
    assert abs(float(s1["Mean_WIP"]) - 11.5) < 0.001
    print("[PASS] 6. S1 mean WIP is 11.5")

    # 7. S2 mean completed is 18.7
    s2 = summary[summary["Scenario_ID"] == "S2"].iloc[0]
    assert abs(float(s2["Mean_Completed"]) - 18.7) < 0.001
    print("[PASS] 7. S2 mean completed is 18.7")

    # 8. S2 vs S1 throughput increase is about 49.6% (computed from CSV)
    s1_t = float(s1["Mean_Throughput"])
    s2_t = float(s2["Mean_Throughput"])
    pct = (s2_t - s1_t) / s1_t * 100
    assert abs(pct - 49.6) < 0.1, f"S2 vs S1 throughput should be about +49.6%, got {pct:.2f}%"
    print(f"[PASS] 8. S2 vs S1 throughput increase about 49.6% (got {pct:.2f}%)")

    # 9. S2 vs S1 WIP decrease is about 53.9% (computed from CSV)
    s1_w = float(s1["Mean_WIP"])
    s2_w = float(s2["Mean_WIP"])
    pct = (s2_w - s1_w) / s1_w * 100
    assert abs(pct - (-53.9)) < 0.1, f"S2 vs S1 WIP should be about -53.9%, got {pct:.2f}%"
    print(f"[PASS] 9. S2 vs S1 WIP decrease about 53.9% (got {pct:.2f}%)")

    # Scenario comparison function works
    comparison = get_scenario_comparison()
    assert len(comparison) == 3
    print("[PASS] get_scenario_comparison returns 3 scenarios")

    # 10. foreign_key_check = 0
    conn = get_connection()
    fks = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    assert len(fks) == 0, f"Foreign key violations: {fks}"
    print("[PASS] 10. foreign_key_check = 0")

    # 11. Test does not create/clean work orders; existing demo data is preserved
    final = _snapshot()
    assert final == before, f"Test modified the database: {before} -> {final}"
    print(f"[PASS] 11. Preserved existing demo work orders (work_orders={kpis['work_order_total']})")

    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
