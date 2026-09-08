"""Regression checks for the integrated EOL-EG-V5 Six Sigma page data."""

import json
import math
import shutil
import sqlite3
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT))

from services.six_sigma_service import (  # noqa: E402
    QUALITY_V5_DIR,
    SixSigmaDataError,
    load_six_sigma_results,
)


def assert_close(actual, expected, tolerance=1e-10):
    assert math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance), (
        actual,
        expected,
    )


def database_counts():
    connection = sqlite3.connect(ROOT / "database" / "mes.db")
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in tables
        }
    finally:
        connection.close()


before_counts = database_counts()
results = load_six_sigma_results()

assert results["release"]["version"] == "EOL-EG-V5"
assert results["release"]["status"] == "CURRENT"
assert results["release"]["data_label"] == "Synthetic Data"
print("[PASS] 1. Only the CURRENT EOL-EG-V5 Synthetic Data release is loaded")

assert results["before"]["n"] == 200
assert results["after"]["n"] == 200
assert len(results["quality_preview"]) == 400
print("[PASS] 2. Before/After row counts are 200/200")

assert_close(results["before"]["mean_n"], 11.66295)
assert_close(results["after"]["mean_n"], 12.00560)
assert_close(results["before"]["overall_sd_n"], 0.7693518759613355)
assert_close(results["after"]["overall_sd_n"], 0.5140318899831002)
print("[PASS] 3. Means and sample standard deviations were independently recomputed")

assert_close(results["before"]["ppk"], 0.7204982323257824)
assert_close(results["after"]["ppk"], 1.2933049737864644)
assert results["after"]["ppk"] < results["ppk_reference_min"]
print("[PASS] 4. Ppk values match V5 and After remains below the 1.33 reference")

assert results["before"]["defects"] == 3
assert results["after"]["defects"] == 0
assert_close(results["improvement"]["sd_reduction_pct"], 33.18637335604113)
assert_close(results["improvement"]["defect_rate_reduction_pp"], 1.5)
print("[PASS] 5. Defects and improvement metrics match V5")

assert_close(results["msa"]["pct_tolerance"], 11.556293379222744)
assert results["msa"]["ndc"] == 14
assert results["msa"]["acceptance"] == "CONDITIONAL"
print("[PASS] 6. MSA result is 11.56% tolerance, ndc 14, CONDITIONAL")

assert results["after_control"]["phase_i_in_control"] is False
assert results["after_control"]["phase_ii_status"] == "NOT_ESTABLISHED"
assert results["after_control"]["mr_flags"] == ["AF-118", "AF-158"]
print("[PASS] 7. Stability limitations and MR alarms are preserved")

assert len(results["root_causes"]) == 8
assert results["root_causes"][0]["factor"] == "jaw_alignment_error_mm"
assert len(results["control_plan"]) == 10
assert len(results["open_control_items"]) == 10
print("[PASS] 8. Root-cause and control-plan outputs are complete")

assert len(results["chart_paths"]) == 12
assert all(path.is_file() for path in results["chart_paths"])
print("[PASS] 9. All 12 validated V5 charts are available")

with tempfile.TemporaryDirectory() as temp_dir:
    invalid_dir = Path(temp_dir) / "quality_v5"
    shutil.copytree(QUALITY_V5_DIR, invalid_dir)
    config_path = invalid_dir / "generation_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["version"] = "EOL-EG-V4"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    try:
        load_six_sigma_results(invalid_dir)
    except SixSigmaDataError as exc:
        assert "EOL-EG-V5" in str(exc)
    else:
        raise AssertionError("A non-V5 release was accepted")
print("[PASS] 10. Non-V5 data is rejected")

with tempfile.TemporaryDirectory() as temp_dir:
    invalid_dir = Path(temp_dir) / "quality_v5"
    shutil.copytree(QUALITY_V5_DIR, invalid_dir)
    source_path = invalid_dir / "quality_before_after.csv"
    source_path.write_bytes(source_path.read_bytes() + b"\n")
    try:
        load_six_sigma_results(invalid_dir)
    except SixSigmaDataError as exc:
        assert "SHA-256 mismatch" in str(exc)
    else:
        raise AssertionError("A modified source CSV was accepted")
print("[PASS] 11. Source hash changes are rejected")

with tempfile.TemporaryDirectory() as temp_dir:
    portable_dir = Path(temp_dir) / "quality_v5"
    shutil.copytree(QUALITY_V5_DIR, portable_dir)
    portable_manifest = portable_dir / "chart_manifest.csv"
    portable_manifest.write_bytes(portable_manifest.read_bytes().replace(b"\r\n", b"\n"))
    portable_results = load_six_sigma_results(portable_dir)
    assert len(portable_results["chart_manifest"]) == 12
print("[PASS] 12. LF/CRLF normalization preserves cross-platform validation")

assert database_counts() == before_counts
print("[PASS] 13. Six Sigma reads do not modify the MES database")
print("ALL TESTS PASSED")
