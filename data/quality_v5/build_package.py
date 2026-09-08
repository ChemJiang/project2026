"""Build the V5 delivery ZIP from an explicit allowlist, excluding stale and temporary files."""

import argparse
import csv
import hashlib
import json
import math
import zipfile
from pathlib import Path

import pandas as pd

from generate_quality_data import capability, gage_rr, validate_config


CORE_FILES = [
    "README_quality_v5.md",
    "VERSION_STATUS.md",
    "quality_baseline.csv",
    "quality_before_after.csv",
    "quality_msa.csv",
    "six_sigma_data_dictionary.csv",
    "generation_config.json",
    "generate_quality_data.py",
    "validation_report.json",
    "analyze_quality_data.py",
    "build_package.py",
    "chart_manifest.csv",
    "root_cause_analysis.csv",
    "control_plan.csv",
    "six_sigma_analysis_report.md",
    "analysis_validation.json",
]

RETIRED_ROOT_FILES = ["README_quality_v3.md", "README_quality_v4.md", "quality_data_v3.zip", "quality_data_v4.zip"]


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def equivalent(actual, expected, rel_tol=1e-10, abs_tol=1e-12):
    if isinstance(actual, dict) and isinstance(expected, dict):
        return set(actual) == set(expected) and all(equivalent(actual[key], expected[key], rel_tol, abs_tol) for key in actual)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(equivalent(left, right, rel_tol, abs_tol) for left, right in zip(actual, expected))
    if isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return math.isclose(float(actual), float(expected), rel_tol=rel_tol, abs_tol=abs_tol)
    return actual == expected


def verify_release(root, chart_files):
    retired = [name for name in RETIRED_ROOT_FILES if (root / name).exists()]
    if retired:
        raise SystemExit(f"Cannot build package while retired root files remain: {retired}")
    config = json.loads((root / "generation_config.json").read_text(encoding="utf-8"))
    report = json.loads((root / "validation_report.json").read_text(encoding="utf-8"))
    analysis = json.loads((root / "analysis_validation.json").read_text(encoding="utf-8"))
    if report.get("structural_status") != "PASS" or not equivalent(validate_config(config), report.get("configuration_validation")):
        raise SystemExit("Generation configuration or structural validation is not reproducibly PASS")
    expected_csv_hashes = report.get("sha256", {})
    actual_csv_hashes = {name: sha256_file(root / name) for name in expected_csv_hashes}
    if actual_csv_hashes != expected_csv_hashes:
        raise SystemExit("CSV hash verification failed")
    actual_source_hashes = {
        "generation_config.json": sha256_file(root / "generation_config.json"),
        "generate_quality_data.py": sha256_file(root / "generate_quality_data.py"),
    }
    if actual_source_hashes != report.get("source_sha256"):
        raise SystemExit("Generation source hash verification failed")
    combined = pd.read_csv(root / "quality_before_after.csv", encoding="utf-8-sig")
    msa = pd.read_csv(root / "quality_msa.csv", encoding="utf-8-sig")
    before_rows = combined.loc[combined["process_stage"] == "Before Improvement"].to_dict(orient="records")
    after_rows = combined.loc[combined["process_stage"] == "After Improvement"].to_dict(orient="records")
    if not equivalent(capability(before_rows, config), report.get("before")) or not equivalent(capability(after_rows, config), report.get("after")):
        raise SystemExit("Capability recomputation failed")
    if not equivalent(gage_rr(msa.to_dict(orient="records"), config), report.get("msa")):
        raise SystemExit("MSA recomputation failed")
    if not analysis.get("all_chart_files_exist") or analysis.get("chart_count") != 12 or not all(analysis.get("input_checks", {}).values()):
        raise SystemExit("Analysis validation is not fully PASS")
    analysis_sources = analysis.get("source_sha256", {})
    if not analysis_sources or any(not (root / name).is_file() or sha256_file(root / name) != digest for name, digest in analysis_sources.items()):
        raise SystemExit("Analysis input/source hash verification failed")
    expected_artifact_hashes = analysis.get("artifact_sha256", {})
    if not expected_artifact_hashes or any(
        not (root / name).is_file() or sha256_file(root / name) != digest
        for name, digest in expected_artifact_hashes.items()
    ):
        raise SystemExit("Analysis report/table hash verification failed")
    expected_chart_hashes = analysis.get("chart_sha256", {})
    if not expected_chart_hashes:
        raise SystemExit("Analysis chart hash map is missing")
    actual_chart_hashes = {Path(name).name: sha256_file(root / name) for name in chart_files}
    if actual_chart_hashes != expected_chart_hashes:
        raise SystemExit("Chart hash verification failed")
    control_validation = analysis.get("control_plan", {})
    if control_validation.get("row_count", 0) < 10 or not control_validation.get("all_rows_have_reaction_plan") or not control_validation.get("all_rows_have_owner_and_record"):
        raise SystemExit("Control plan validation failed")
    if not control_validation.get("all_statuses_in_enum"):
        raise SystemExit("Control plan statuses are not all within the enumerated set")
    required_generalization_checks = {
        "ppk_below_branch",
        "ppk_meets_branch",
        "gage_pass_branch",
        "gage_conditional_branch",
        "gage_unacceptable_pct_branch",
        "gage_unacceptable_ndc_branch",
        "figure08_pass_text",
        "figure08_conditional_text",
        "figure08_unacceptable_text",
        "figure12_passing_items_not_blockers",
        "figure12_failure_items_are_blockers",
        "figure08_manifest_row_matches",
        "figure12_manifest_row_matches",
        "manifest_roundtrip_matches",
        "figure08_manifest_file_matches",
        "figure12_manifest_file_matches",
    }
    generalization_checks = analysis.get("generalization_checks", {})
    if not required_generalization_checks <= set(generalization_checks) or not all(
        generalization_checks[name] is True for name in required_generalization_checks
    ):
        raise SystemExit("Chart interpretation generalization validation failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.input.resolve()
    output = (args.output or root / "quality_data_v5.zip").resolve()
    temporary = output.with_name(f".{output.stem}.tmp.zip")

    with (root / "chart_manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
        chart_files = [f"charts/{row['chart_file']}" for row in csv.DictReader(stream)]
    members = CORE_FILES + chart_files
    missing = [name for name in members if not (root / name).is_file()]
    if missing:
        raise SystemExit(f"Cannot build package; missing files: {missing}")
    if len(chart_files) != 12 or len(set(chart_files)) != len(chart_files):
        raise SystemExit("Chart manifest must contain exactly 12 unique files")
    if any(Path(name).name.startswith(".") or "V3" in name or "V4" in name for name in members):
        raise SystemExit("Package allowlist contains a temporary or retired-version filename")
    verify_release(root, chart_files)

    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in members:
                archive.write(root / name, arcname=name)
        with zipfile.ZipFile(temporary) as archive:
            corrupt_member = archive.testzip()
            actual_members = archive.namelist()
        if corrupt_member is not None or actual_members != members:
            raise SystemExit(f"ZIP verification failed; corrupt member: {corrupt_member}")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)

    print(json.dumps({"status": "PASS", "output": output.name, "member_count": len(members), "chart_count": len(chart_files), "members": members}, indent=2))


if __name__ == "__main__":
    main()
