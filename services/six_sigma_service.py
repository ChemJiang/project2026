"""Read and validate the EOL-EG-V5 synthetic Six Sigma analysis package."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd


QUALITY_V5_DIR = Path(__file__).resolve().parents[1] / "data" / "quality_v5"
EXPECTED_VERSION = "EOL-EG-V5"
EXPECTED_DATA_LABEL = "Synthetic Data"
EXPECTED_STAGES = ("Before Improvement", "After Improvement")
OPEN_CONTROL_STATUSES = {
    "PASS_SAMPLE_ONLY",
    "PROVISIONAL",
    "WATCH",
    "CONDITIONAL",
    "UNACCEPTABLE",
    "ACTION_REQUIRED",
}


class SixSigmaDataError(ValueError):
    """Raised when the packaged V5 data fails its release contract."""


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SixSigmaDataError(f"Cannot read {path.name}: {exc}") from exc


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except (OSError, pd.errors.ParserError) as exc:
        raise SixSigmaDataError(f"Cannot read {path.name}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_hashes(data_dir: Path, hashes: dict, prefix: str) -> None:
    for relative_name, expected in hashes.items():
        path = data_dir / relative_name
        if not path.is_file():
            raise SixSigmaDataError(f"Required {prefix} file is missing: {relative_name}")
        actual = _sha256(path)
        if actual != expected:
            raise SixSigmaDataError(f"SHA-256 mismatch for {relative_name}")


def _stage_metrics(frame: pd.DataFrame, stage: str, lsl: float, usl: float) -> dict:
    values = pd.to_numeric(
        frame.loc[frame["process_stage"] == stage, "measured_force_n"],
        errors="raise",
    )
    if values.empty:
        raise SixSigmaDataError(f"No rows found for stage: {stage}")
    mean = float(values.mean())
    sd = float(values.std(ddof=1))
    if not math.isfinite(sd) or sd <= 0:
        raise SixSigmaDataError(f"Invalid sample standard deviation for stage: {stage}")
    pp = (usl - lsl) / (6.0 * sd)
    ppk = min((usl - mean) / (3.0 * sd), (mean - lsl) / (3.0 * sd))
    defects = int(
        pd.to_numeric(
            frame.loc[frame["process_stage"] == stage, "defect_flag"],
            errors="raise",
        ).sum()
    )
    return {
        "n": int(len(values)),
        "mean_n": mean,
        "overall_sd_n": sd,
        "defects": defects,
        "defect_rate": defects / len(values),
        "pp": pp,
        "ppk": ppk,
    }


def _assert_close(name: str, actual: float, expected: float) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10):
        raise SixSigmaDataError(
            f"Recomputed {name} does not match validation_report.json: "
            f"{actual} != {expected}"
        )


def load_six_sigma_results(data_dir: str | Path | None = None) -> dict:
    """Return validated V5 inputs and independently recomputed headline metrics."""
    data_dir = Path(data_dir) if data_dir is not None else QUALITY_V5_DIR
    config = _load_json(data_dir / "generation_config.json")
    validation = _load_json(data_dir / "validation_report.json")
    analysis_validation = _load_json(data_dir / "analysis_validation.json")

    release = validation.get("release", {})
    if config.get("version") != EXPECTED_VERSION or release.get("version") != EXPECTED_VERSION:
        raise SixSigmaDataError("Only EOL-EG-V5 data may be displayed.")
    if config.get("release_status") != "CURRENT" or release.get("status") != "CURRENT":
        raise SixSigmaDataError("The Six Sigma package is not marked CURRENT.")
    if config.get("data_label") != EXPECTED_DATA_LABEL or release.get("data_label") != EXPECTED_DATA_LABEL:
        raise SixSigmaDataError("The required Synthetic Data label is missing.")

    _verify_hashes(data_dir, validation.get("sha256", {}), "source")
    _verify_hashes(data_dir, validation.get("source_sha256", {}), "generator")
    _verify_hashes(data_dir, analysis_validation.get("artifact_sha256", {}), "analysis")

    quality = _read_csv(data_dir / "quality_before_after.csv")
    required_columns = {
        "process_stage",
        "measured_force_n",
        "defect_flag",
        "target_n",
        "lsl_n",
        "usl_n",
        "data_label",
        "generation_model_version",
    }
    missing = sorted(required_columns - set(quality.columns))
    if missing:
        raise SixSigmaDataError(f"quality_before_after.csv is missing columns: {missing}")
    if len(quality) != int(config["deliverable_contract"]["combined_rows"]):
        raise SixSigmaDataError("Unexpected row count in quality_before_after.csv.")
    if set(quality["generation_model_version"].dropna().unique()) != {EXPECTED_VERSION}:
        raise SixSigmaDataError("Mixed or unexpected generation model versions detected.")
    if set(quality["data_label"].dropna().unique()) != {EXPECTED_DATA_LABEL}:
        raise SixSigmaDataError("Mixed or unexpected data labels detected.")

    stage_counts = quality["process_stage"].value_counts().to_dict()
    expected_per_stage = int(config["deliverable_contract"]["rows_per_stage"])
    if set(stage_counts) != set(EXPECTED_STAGES) or any(
        stage_counts.get(stage) != expected_per_stage for stage in EXPECTED_STAGES
    ):
        raise SixSigmaDataError(f"Unexpected process-stage counts: {stage_counts}")

    spec = config["specification"]
    target = float(spec["target_n"])
    lsl = float(spec["lsl_n"])
    usl = float(spec["usl_n"])
    for column, expected in (("target_n", target), ("lsl_n", lsl), ("usl_n", usl)):
        actual = pd.to_numeric(quality[column], errors="raise")
        if not (actual == expected).all():
            raise SixSigmaDataError(f"Inconsistent {column} values detected.")

    before = _stage_metrics(quality, EXPECTED_STAGES[0], lsl, usl)
    after = _stage_metrics(quality, EXPECTED_STAGES[1], lsl, usl)
    for stage_key, recomputed in (("before", before), ("after", after)):
        contract = validation[stage_key]
        _assert_close(f"{stage_key}.mean_n", recomputed["mean_n"], float(contract["mean_n"]))
        _assert_close(
            f"{stage_key}.overall_sd_n",
            recomputed["overall_sd_n"],
            float(contract["overall_sd_n"]),
        )
        _assert_close(f"{stage_key}.ppk", recomputed["ppk"], float(contract["Ppk_descriptive"]))
        if recomputed["defects"] != int(contract["defects"]):
            raise SixSigmaDataError(f"Recomputed {stage_key} defect count does not match.")

    msa_frame = _read_csv(data_dir / "quality_msa.csv")
    msa_dimensions = validation["msa"]["dimensions"]
    if len(msa_frame) != (
        int(msa_dimensions["parts"])
        * int(msa_dimensions["appraisers"])
        * int(msa_dimensions["replicates"])
    ):
        raise SixSigmaDataError("Unexpected MSA study size.")

    root_causes = _read_csv(data_dir / "root_cause_analysis.csv")
    control_plan = _read_csv(data_dir / "control_plan.csv")
    chart_manifest = _read_csv(data_dir / "chart_manifest.csv")
    tagged_frames = {
        "quality_msa.csv": msa_frame,
        "root_cause_analysis.csv": root_causes,
        "control_plan.csv": control_plan,
        "chart_manifest.csv": chart_manifest,
    }
    for name, frame in tagged_frames.items():
        if "generation_model_version" not in frame or "data_label" not in frame:
            raise SixSigmaDataError(f"{name} is missing V5 release metadata.")
        if set(frame["generation_model_version"].dropna().unique()) != {EXPECTED_VERSION}:
            raise SixSigmaDataError(f"{name} contains an unexpected model version.")
        if set(frame["data_label"].dropna().unique()) != {EXPECTED_DATA_LABEL}:
            raise SixSigmaDataError(f"{name} contains an unexpected data label.")
    if len(root_causes) != int(analysis_validation["root_cause_analysis"]["row_count"]):
        raise SixSigmaDataError("Unexpected root-cause analysis row count.")
    if len(control_plan) != int(analysis_validation["control_plan"]["row_count"]):
        raise SixSigmaDataError("Unexpected control-plan row count.")
    chart_paths = []
    for chart_file in chart_manifest["chart_file"]:
        chart_path = data_dir / "charts" / str(chart_file)
        if not chart_path.is_file():
            raise SixSigmaDataError(f"Chart file is missing: {chart_file}")
        chart_paths.append(chart_path)
    if len(chart_paths) != int(analysis_validation["chart_count"]):
        raise SixSigmaDataError("Unexpected chart count in chart_manifest.csv.")

    improvement = {
        "mean_shift_toward_target_n": abs(before["mean_n"] - target)
        - abs(after["mean_n"] - target),
        "sd_reduction_pct": (before["overall_sd_n"] - after["overall_sd_n"])
        / before["overall_sd_n"]
        * 100.0,
        "defect_rate_reduction_pp": (before["defect_rate"] - after["defect_rate"])
        * 100.0,
        "ppk_change": after["ppk"] - before["ppk"],
    }

    return {
        "data_dir": data_dir,
        "release": release,
        "specification": {"ctq": spec["ctq"], "target_n": target, "lsl_n": lsl, "usl_n": usl},
        "before": before,
        "after": after,
        "improvement": improvement,
        "msa": validation["msa"],
        "before_control": validation["before"]["control_screen"],
        "after_control": validation["after"]["control_screen"],
        "ppk_reference_min": float(config["analysis"]["ppk_reference_min"]),
        "root_causes": root_causes.sort_values("centering_priority_rank").to_dict("records"),
        "control_plan": control_plan.to_dict("records"),
        "open_control_items": [
            row for row in control_plan.to_dict("records")
            if row["current_status"] in OPEN_CONTROL_STATUSES
        ],
        "chart_manifest": chart_manifest.to_dict("records"),
        "chart_paths": chart_paths,
        "quality_preview": quality,
        "report_path": data_dir / "six_sigma_analysis_report.md",
        "raw_data_path": data_dir / "quality_before_after.csv",
        "control_plan_path": data_dir / "control_plan.csv",
        "validation_path": data_dir / "analysis_validation.json",
    }
