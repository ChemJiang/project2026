"""Generate reproducible synthetic electric-gripper Define/Measure/Improve data."""

import argparse
import csv
import hashlib
import io
import json
import math
import os
import shutil
import statistics as st
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path


class RNG:
    """Unsigned Mulberry32 plus Box-Muller cosine, with no cached variate."""

    def __init__(self, seed):
        self.state = int(seed) & 0xFFFFFFFF

    def uniform(self):
        self.state = (self.state + 0x6D2B79F5) & 0xFFFFFFFF
        value = self.state
        value = ((value ^ (value >> 15)) * (value | 1)) & 0xFFFFFFFF
        value ^= (value + (((value ^ (value >> 7)) * (value | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((value ^ (value >> 14)) & 0xFFFFFFFF) / 4294967296

    def normal(self, mean=0.0, sd=1.0):
        u = self.uniform()
        while u == 0:
            u = self.uniform()
        v = self.uniform()
        while v == 0:
            v = self.uniform()
        return mean + sd * math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * v)

    def shuffle(self, values):
        values = list(values)
        for i in range(len(values) - 1, 0, -1):
            j = math.floor(self.uniform() * (i + 1))
            values[i], values[j] = values[j], values[i]
        return values


def rnd(value, digits=3):
    """Match JavaScript Math.round for the non-tie values used here."""
    return math.floor(value * 10**digits + 0.5) / 10**digits


# Single source of truth for Control-plan status vocabulary and which statuses
# leave the Control phase open (blocking closure).
CONTROL_STATUSES = (
    "PASS",
    "PASS_SAMPLE_ONLY",
    "PROVISIONAL",
    "WATCH",
    "CONDITIONAL",
    "UNACCEPTABLE",
    "ACTION_REQUIRED",
)
OPEN_CONTROL_STATUSES = frozenset(status for status in CONTROL_STATUSES if status != "PASS")


def gage_rr_acceptance(pct_tolerance, ndc, analysis):
    """Three-level measurement-system acceptance from configured thresholds."""
    pass_pct = analysis["gage_rr_tolerance_pass_pct"]
    fail_pct = analysis["gage_rr_tolerance_fail_pct"]
    ndc_min = analysis["gage_rr_ndc_min"]
    if ndc < ndc_min or pct_tolerance > fail_pct:
        return "UNACCEPTABLE"
    if pct_tolerance > pass_pct:
        return "CONDITIONAL"
    return "PASS"


def validate_config(config):
    """Validate the complete generation contract before any random draw or file write."""
    if not isinstance(config, dict):
        raise ValueError("Invalid generation_config.json:\n- top-level value must be an object")
    errors = []
    check_count = 0

    def require(condition, message):
        nonlocal check_count
        check_count += 1
        if not condition:
            errors.append(message)

    def positive_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0

    def nonnegative_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0

    require(config.get("version") == "EOL-EG-V5", "version must be EOL-EG-V5")
    require(config.get("release_status") == "CURRENT", "release_status must be CURRENT")
    require(config.get("data_label") == "Synthetic Data", "data_label must be exactly 'Synthetic Data'")
    require(isinstance(config.get("source_system"), str) and config["source_system"].strip(), "source_system is required")
    require(isinstance(config.get("sampler_max_attempts"), int) and config["sampler_max_attempts"] > 0, "sampler_max_attempts must be a positive integer")
    require(all(isinstance(config.get(key), str) and config[key].strip() for key in ("rng", "rounding", "bounds_method")), "rng, rounding and bounds_method descriptions are required")
    contract = config.get("deliverable_contract", {})
    require(isinstance(contract, dict), "deliverable_contract must be an object")
    if not isinstance(contract, dict):
        contract = {}
    require(isinstance(contract.get("rows_per_stage"), int) and contract["rows_per_stage"] > 0, "deliverable_contract.rows_per_stage must be a positive integer")
    require(isinstance(contract.get("combined_rows"), int) and contract["combined_rows"] == 2 * contract.get("rows_per_stage", -1), "deliverable_contract.combined_rows must equal twice rows_per_stage")
    require(isinstance(contract.get("msa_parts"), int) and contract["msa_parts"] >= 2, "deliverable_contract.msa_parts must be at least 2")

    seeds = config.get("seeds", {})
    require(isinstance(seeds, dict), "seeds must be an object")
    if not isinstance(seeds, dict):
        seeds = {}
    required_seed_keys = {"before_process", "before_measurement", "after_process", "after_measurement", "msa"}
    require(required_seed_keys <= set(seeds), "all five declared seed keys are required")
    require(all(isinstance(seeds.get(key), int) and not isinstance(seeds.get(key), bool) for key in required_seed_keys), "all seeds must be integers")
    require(len({seeds.get(key) for key in required_seed_keys}) == len(required_seed_keys), "process, measurement and MSA seeds must be distinct")

    specification = config.get("specification", {})
    require(isinstance(specification, dict), "specification must be an object")
    if not isinstance(specification, dict):
        specification = {}
    target = specification.get("target_n")
    lower = specification.get("lsl_n")
    upper = specification.get("usl_n")
    require(all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in (target, lower, upper)), "target_n, lsl_n and usl_n must be finite numbers")
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (target, lower, upper)):
        require(lower < target < upper, "specification must satisfy LSL < Target < USL")
    require(specification.get("limits_inclusive") is True, "limits_inclusive must be true for the documented acceptance rule")

    measurement = config.get("measurement", {})
    require(isinstance(measurement, dict), "measurement must be an object")
    if not isinstance(measurement, dict):
        measurement = {}
    resolution = measurement.get("resolution_n")
    force_digits = measurement.get("force_record_digits")
    require(positive_number(resolution), "measurement.resolution_n must be positive")
    require(isinstance(force_digits, int) and not isinstance(force_digits, bool) and force_digits >= 0, "force_record_digits must be a nonnegative integer")
    if positive_number(resolution) and isinstance(force_digits, int) and force_digits >= 0:
        require(abs(resolution * 10**force_digits - round(resolution * 10**force_digits)) < 1e-9, "resolution_n must be representable at force_record_digits")
    require(positive_number(measurement.get("repeatability_sd_n")), "repeatability_sd_n must be positive")
    require(positive_number(measurement.get("zero_offset_sd_n")), "zero_offset_sd_n must be positive")
    zero_bounds = measurement.get("zero_offset_bounds_n", [])
    require(isinstance(zero_bounds, list) and len(zero_bounds) == 2 and all(isinstance(value, (int, float)) for value in zero_bounds) and zero_bounds[0] < 0 < zero_bounds[1], "zero_offset_bounds_n must straddle zero")
    require(isinstance(measurement.get("zero_offset_record_digits"), int) and measurement["zero_offset_record_digits"] >= 0, "zero_offset_record_digits must be a nonnegative integer")
    require(all(isinstance(measurement.get(key), str) and measurement[key].strip() for key in ("device_id", "protocol_id", "test_block_id", "force_definition", "zero_policy")), "measurement IDs and method descriptions are required")
    require(all(positive_number(measurement.get(key)) for key in ("test_block_diameter_mm", "closing_speed_mm_s", "hold_time_s", "contact_distance_from_jaw_root_mm")), "measurement geometry, speed and hold values must be positive")
    appraisers = measurement.get("appraisers", [])
    require(isinstance(appraisers, list) and len(appraisers) >= 2, "at least two appraisers are required")
    if isinstance(appraisers, list):
        appraiser_ids = [item.get("id") for item in appraisers if isinstance(item, dict)]
        require(len(appraiser_ids) == len(appraisers) and len(set(appraiser_ids)) == len(appraiser_ids) and all(isinstance(value, str) and value for value in appraiser_ids), "appraiser IDs must be nonempty and unique")
        require(all(isinstance(item.get("bias_n"), (int, float)) and not isinstance(item.get("bias_n"), bool) and math.isfinite(item["bias_n"]) for item in appraisers if isinstance(item, dict)), "each appraiser bias_n must be finite")

    sampling = config.get("sampling", {})
    require(isinstance(sampling, dict), "sampling must be an object")
    if not isinstance(sampling, dict):
        sampling = {}
    offsets = sampling.get("production_day_offsets", [])
    require(isinstance(offsets, list) and offsets and all(isinstance(value, int) and value >= 0 for value in offsets) and offsets == sorted(set(offsets)), "production_day_offsets must be sorted unique nonnegative integers")
    shifts = sampling.get("shifts", [])
    require(isinstance(shifts, list) and shifts, "at least one shift is required")
    if isinstance(shifts, list) and shifts:
        names = [item.get("name") for item in shifts if isinstance(item, dict)]
        require(len(names) == len(shifts) and len(set(names)) == len(names) and all(isinstance(value, str) and value for value in names), "shift names must be nonempty and unique")
        require(all(isinstance(item.get("start_hour"), int) and 0 <= item["start_hour"] <= 23 for item in shifts if isinstance(item, dict)), "shift start_hour must be an integer from 0 to 23")
    require(isinstance(sampling.get("samples_per_shift"), int) and sampling["samples_per_shift"] > 0, "samples_per_shift must be a positive integer")
    require(isinstance(sampling.get("interval_minutes"), int) and sampling["interval_minutes"] > 0, "sampling.interval_minutes must be a positive integer")
    require(isinstance(sampling.get("operator_rotation_block_size"), int) and sampling["operator_rotation_block_size"] > 0, "operator_rotation_block_size must be a positive integer")
    require(isinstance(sampling.get("utc_offset_hours"), (int, float)) and -12 <= sampling["utc_offset_hours"] <= 14, "utc_offset_hours must be between -12 and +14")
    require(isinstance(sampling.get("timezone_name"), str) and sampling["timezone_name"].strip(), "sampling.timezone_name is required")
    if offsets and shifts and isinstance(sampling.get("samples_per_shift"), int):
        calculated_stage_rows = len(offsets) * len(shifts) * sampling["samples_per_shift"]
        require(calculated_stage_rows == contract.get("rows_per_stage"), "sampling configuration must produce deliverable_contract.rows_per_stage rows")

    stages = config.get("stages", {})
    require(isinstance(stages, dict), "stages must be an object")
    if not isinstance(stages, dict):
        stages = {}
    require({"before", "after"} <= set(stages), "before and after stage configurations are required")
    required_variables = {
        "motor_current_a",
        "jaw_alignment_error_mm",
        "gear_backlash_deg",
        "pad_thickness_mm",
        "fastener_torque_nm",
    }
    stage_names = []
    stage_prefixes = []
    for stage_key in ("before", "after"):
        stage = stages.get(stage_key, {})
        require(isinstance(stage, dict), f"stages.{stage_key} must be an object")
        if not isinstance(stage, dict):
            stage = {}
        stage_names.append(stage.get("process_stage"))
        stage_prefixes.extend([stage.get("record_prefix"), stage.get("part_prefix"), stage.get("batch_prefix")])
        try:
            datetime.fromisoformat(stage.get("start_date", ""))
            valid_date = True
        except (TypeError, ValueError):
            valid_date = False
        require(valid_date, f"stages.{stage_key}.start_date must be ISO 8601")
        require(stage.get("process_seed_key") in seeds and stage.get("measurement_seed_key") in seeds, f"stages.{stage_key} must reference declared seeds")
        require(all(isinstance(stage.get(key), str) and stage[key].strip() for key in ("process_stage", "record_prefix", "part_prefix", "batch_prefix", "improvement_plan_id", "improvement_actions")), f"stages.{stage_key} identifiers and improvement metadata are required")
        operators = stage.get("operators", [])
        require(isinstance(operators, list) and operators, f"stages.{stage_key}.operators must be nonempty")
        if isinstance(operators, list) and operators:
            operator_ids = [item.get("id") for item in operators if isinstance(item, dict)]
            require(len(operator_ids) == len(operators) and len(set(operator_ids)) == len(operator_ids) and all(isinstance(value, str) and value for value in operator_ids), f"stages.{stage_key} operator IDs must be nonempty and unique")
            require(all(all(isinstance(item.get(key), (int, float)) and not isinstance(item.get(key), bool) and math.isfinite(item[key]) for key in ("current_bias_a", "alignment_mean_mm", "torque_mean_nm")) for item in operators if isinstance(item, dict)), f"stages.{stage_key} operator numeric parameters must be finite")
        variables = stage.get("variables", {})
        require(isinstance(variables, dict), f"stages.{stage_key}.variables must be an object")
        if not isinstance(variables, dict):
            variables = {}
        require(set(variables) == required_variables, f"stages.{stage_key}.variables must contain the five declared process factors exactly")
        for field in required_variables:
            spec = variables.get(field, {})
            if not isinstance(spec, dict):
                spec = {}
            bounds = spec.get("bounds", [])
            require(positive_number(spec.get("sd")), f"stages.{stage_key}.variables.{field}.sd must be positive")
            require(isinstance(spec.get("digits"), int) and spec.get("digits") >= 0, f"stages.{stage_key}.variables.{field}.digits must be a nonnegative integer")
            require(isinstance(bounds, list) and len(bounds) == 2 and all(isinstance(value, (int, float)) for value in bounds) and bounds[0] < bounds[1], f"stages.{stage_key}.variables.{field}.bounds must be increasing numeric bounds")
        motor = variables.get("motor_current_a", {})
        alignment = variables.get("jaw_alignment_error_mm", {})
        if not isinstance(motor, dict):
            motor = {}
        if not isinstance(alignment, dict):
            alignment = {}
        require(isinstance(motor.get("base_mean"), (int, float)) and math.isfinite(motor["base_mean"]), f"stages.{stage_key} motor_current_a.base_mean must be finite")
        require(isinstance(motor.get("night_effect"), (int, float)) and math.isfinite(motor["night_effect"]), f"stages.{stage_key} motor_current_a.night_effect must be finite")
        require(isinstance(alignment.get("night_effect"), (int, float)) and math.isfinite(alignment["night_effect"]), f"stages.{stage_key} jaw_alignment_error_mm.night_effect must be finite")
        batch = stage.get("batch", {})
        require(isinstance(batch, dict), f"stages.{stage_key}.batch must be an object")
        if not isinstance(batch, dict):
            batch = {}
        require(positive_number(batch.get("current_drift_sd_a")), f"stages.{stage_key}.batch.current_drift_sd_a must be positive")
        require(positive_number(batch.get("backlash_mean_sd_deg")), f"stages.{stage_key}.batch.backlash_mean_sd_deg must be positive")
        require(positive_number(batch.get("pad_mean_sd_mm")), f"stages.{stage_key}.batch.pad_mean_sd_mm must be positive")
        require(all(isinstance(batch.get(key), (int, float)) and math.isfinite(batch[key]) for key in ("backlash_mean_deg", "pad_mean_mm")), f"stages.{stage_key} batch means must be finite")
        if set(variables) == required_variables and isinstance(operators, list):
            require(variables["motor_current_a"]["bounds"][0] < motor.get("base_mean", float("inf")) < variables["motor_current_a"]["bounds"][1], f"stages.{stage_key} motor-current base mean must lie within bounds")
            require(variables["gear_backlash_deg"]["bounds"][0] < batch.get("backlash_mean_deg", float("inf")) < variables["gear_backlash_deg"]["bounds"][1], f"stages.{stage_key} backlash batch mean must lie within bounds")
            require(variables["pad_thickness_mm"]["bounds"][0] < batch.get("pad_mean_mm", float("inf")) < variables["pad_thickness_mm"]["bounds"][1], f"stages.{stage_key} pad batch mean must lie within bounds")
            require(all(variables["jaw_alignment_error_mm"]["bounds"][0] < item.get("alignment_mean_mm", float("inf")) < variables["jaw_alignment_error_mm"]["bounds"][1] for item in operators if isinstance(item, dict)), f"stages.{stage_key} operator alignment means must lie within bounds")
            require(all(variables["fastener_torque_nm"]["bounds"][0] < item.get("torque_mean_nm", float("inf")) < variables["fastener_torque_nm"]["bounds"][1] for item in operators if isinstance(item, dict)), f"stages.{stage_key} operator torque means must lie within bounds")
        require(positive_number(stage.get("part_residual_sd_n")), f"stages.{stage_key}.part_residual_sd_n must be positive")
    require(stage_names == ["Before Improvement", "After Improvement"], "process_stage labels must be Before Improvement and After Improvement")
    require(len(set(stage_prefixes)) == len(stage_prefixes) and all(isinstance(value, str) and value for value in stage_prefixes), "all stage record, part and batch prefixes must be nonempty and unique")
    if "before" in stages and "after" in stages and isinstance(stages["before"], dict) and isinstance(stages["after"], dict):
        require(stages["before"].get("part_residual_sd_n") == stages["after"].get("part_residual_sd_n"), "unobserved part_residual_sd_n must remain unchanged across stages in V5")

    response = config.get("response", {})
    require(isinstance(response, dict), "response must be an object")
    if not isinstance(response, dict):
        response = {}
    response_keys = {"intercept", "current_coefficient", "current_center", "alignment_coefficient", "backlash_coefficient", "pad_coefficient", "pad_center", "torque_coefficient", "torque_center"}
    require(response_keys <= set(response) and all(isinstance(response[key], (int, float)) and math.isfinite(response[key]) for key in response_keys), "all response coefficients and centers must be finite numbers")

    msa = config.get("msa", {})
    require(isinstance(msa, dict), "msa must be an object")
    if not isinstance(msa, dict):
        msa = {}
    quantiles = msa.get("selection_quantiles", [])
    require(isinstance(quantiles, list) and len(quantiles) >= 2 and quantiles == sorted(set(quantiles)) and all(isinstance(value, (int, float)) and 0 < value < 1 for value in quantiles), "MSA selection_quantiles must be sorted, unique and strictly between 0 and 1")
    require(msa.get("source_stage_key") == "before", "MSA source_stage_key must be before")
    require(isinstance(msa.get("replicates"), int) and msa["replicates"] >= 2, "MSA replicates must be an integer of at least 2")
    require(isinstance(msa.get("reference_record_digits"), int) and msa["reference_record_digits"] >= 0, "MSA reference_record_digits must be a nonnegative integer")
    require(msa.get("randomization") == "All part-appraiser-replicate combinations shuffled in one complete sequence", "MSA randomization statement must match the implemented complete shuffle")
    require(isinstance(msa.get("interval_minutes"), int) and msa["interval_minutes"] > 0, "MSA interval_minutes must be a positive integer")
    try:
        msa_start = datetime.fromisoformat(msa.get("start_timestamp_sgt", ""))
        valid_msa_time = msa_start.utcoffset() is not None
    except (TypeError, ValueError):
        valid_msa_time = False
    require(valid_msa_time, "MSA start_timestamp_sgt must be timezone-aware ISO 8601")
    if valid_msa_time and isinstance(sampling.get("utc_offset_hours"), (int, float)):
        require(
            msa_start.utcoffset() == timedelta(hours=sampling["utc_offset_hours"]),
            "MSA timestamp UTC offset must equal sampling.utc_offset_hours",
        )
    if offsets and shifts and isinstance(sampling.get("samples_per_shift"), int) and quantiles:
        stage_count = len(offsets) * len(shifts) * sampling["samples_per_shift"]
        positions = [math.floor(value * (stage_count - 1)) for value in quantiles]
        require(len(set(positions)) == len(positions), "MSA quantiles must select distinct part positions at the configured stage count")
        require(len(quantiles) == contract.get("msa_parts"), "MSA selection_quantiles count must equal deliverable_contract.msa_parts")

    analysis = config.get("analysis", {})
    require(isinstance(analysis, dict), "analysis must be an object")
    if not isinstance(analysis, dict):
        analysis = {}
    require(positive_number(analysis.get("imr_d2")), "analysis.imr_d2 must be positive")
    require(positive_number(analysis.get("mr_ucl_factor")), "analysis.mr_ucl_factor must be positive")
    require(positive_number(analysis.get("control_sigma_multiplier")), "analysis.control_sigma_multiplier must be positive")
    require(analysis.get("capability_sigma_multiplier") == 3.0, "analysis.capability_sigma_multiplier must equal 3.0 because Cp/Pp use the standard 6-sigma width")
    require(positive_number(analysis.get("gage_study_sigma_multiplier")), "analysis.gage_study_sigma_multiplier must be positive")
    require(positive_number(analysis.get("ndc_multiplier")), "analysis.ndc_multiplier must be positive")
    require(positive_number(analysis.get("ppk_reference_min")), "analysis.ppk_reference_min must be positive")
    pass_pct = analysis.get("gage_rr_tolerance_pass_pct")
    fail_pct = analysis.get("gage_rr_tolerance_fail_pct")
    require(
        isinstance(pass_pct, (int, float)) and not isinstance(pass_pct, bool) and math.isfinite(pass_pct) and 0 <= pass_pct <= 100,
        "analysis.gage_rr_tolerance_pass_pct must be a finite percentage from 0 to 100",
    )
    require(
        isinstance(fail_pct, (int, float)) and not isinstance(fail_pct, bool) and math.isfinite(fail_pct) and 0 <= fail_pct <= 100
        and isinstance(pass_pct, (int, float)) and not isinstance(pass_pct, bool) and math.isfinite(pass_pct) and pass_pct < fail_pct,
        "analysis.gage_rr_tolerance_fail_pct must be a finite percentage strictly greater than gage_rr_tolerance_pass_pct and not exceeding 100",
    )
    require(
        isinstance(analysis.get("gage_rr_ndc_min"), int) and not isinstance(analysis.get("gage_rr_ndc_min"), bool) and analysis["gage_rr_ndc_min"] >= 1,
        "analysis.gage_rr_ndc_min must be an integer of at least 1",
    )

    if errors:
        raise ValueError("Invalid generation_config.json:\n- " + "\n- ".join(errors))
    residual_sd_n = None
    before_stage = config.get("stages", {}).get("before") if isinstance(config.get("stages"), dict) else None
    if isinstance(before_stage, dict):
        candidate = before_stage.get("part_residual_sd_n")
        if positive_number(candidate):
            residual_sd_n = candidate
    residual_sd_text = f"{residual_sd_n:g}" if residual_sd_n is not None else "(unset)"
    return {
        "status": "PASS",
        "check_count": check_count,
        "capability_definition": "Pp/Cp denominator = 6 sigma; Ppk/Cpk one-sided denominator = 3 sigma",
        "control_limit_independence": "I-MR control_sigma_multiplier is not used in capability indices",
        "residual_sd_decision": f"UNCHANGED: part_residual_sd_n is {residual_sd_text} N in both stages",
    }


def bounded_normal(rng, mean, sd, bounds, digits, max_attempts):
    """Reject until the rounded value lies strictly inside the configured bounds."""
    lower, upper = bounds
    for _ in range(max_attempts):
        candidate = rnd(rng.normal(mean, sd), digits)
        if lower < candidate < upper:
            return candidate
    raise RuntimeError(f"Bounded-normal sampler exceeded {max_attempts} attempts; inspect configuration")


def measurement_common(config):
    measurement = config["measurement"]
    specification = config["specification"]
    keys = [
        "device_id",
        "protocol_id",
        "test_block_id",
        "test_block_diameter_mm",
        "closing_speed_mm_s",
        "hold_time_s",
        "contact_distance_from_jaw_root_mm",
    ]
    result = {key: measurement[key] for key in keys}
    result.update(
        device_resolution_n=measurement["resolution_n"],
        ctq=specification["ctq"],
        data_label=config["data_label"],
        generation_model_version=config["version"],
    )
    return result


def measure(true_force, appraiser, rng, config):
    measurement = config["measurement"]
    zero = bounded_normal(
        rng,
        0.0,
        measurement["zero_offset_sd_n"],
        measurement["zero_offset_bounds_n"],
        measurement["zero_offset_record_digits"],
        config["sampler_max_attempts"],
    )
    unrounded = (
        true_force
        + zero
        + appraiser["bias_n"]
        + rng.normal(0.0, measurement["repeatability_sd_n"])
    )
    resolution = measurement["resolution_n"]
    reading = rnd(
        rnd(unrounded / resolution, 0) * resolution,
        measurement["force_record_digits"],
    )
    return reading, zero


def expected_timestamps(config, stage):
    sampling = config["sampling"]
    tz = timezone(timedelta(hours=sampling["utc_offset_hours"]))
    start = datetime.fromisoformat(stage["start_date"]).replace(tzinfo=tz)
    result = []
    for offset in sampling["production_day_offsets"]:
        for shift in sampling["shifts"]:
            for within_shift in range(sampling["samples_per_shift"]):
                timestamp = start + timedelta(
                    days=offset,
                    hours=shift["start_hour"],
                    minutes=within_shift * sampling["interval_minutes"],
                )
                result.append(timestamp.isoformat(timespec="seconds"))
    return result


def build_stage(stage_key, config):
    stage = config["stages"][stage_key]
    sampling = config["sampling"]
    response = config["response"]
    specification = config["specification"]
    apps = config["measurement"]["appraisers"]
    process_seed = config["seeds"][stage["process_seed_key"]]
    measurement_seed = config["seeds"][stage["measurement_seed_key"]]
    process_rng = RNG(process_seed)
    measurement_rng = RNG(measurement_seed)
    tz = timezone(timedelta(hours=sampling["utc_offset_hours"]))
    start = datetime.fromisoformat(stage["start_date"]).replace(tzinfo=tz)
    rows = []
    truths = {}
    variables = stage["variables"]
    operators = stage["operators"]

    for production_day_index, offset in enumerate(sampling["production_day_offsets"]):
        batch = stage["batch"]
        current_drift = process_rng.normal(0.0, batch["current_drift_sd_a"])
        backlash_mean = process_rng.normal(batch["backlash_mean_deg"], batch["backlash_mean_sd_deg"])
        pad_mean = process_rng.normal(batch["pad_mean_mm"], batch["pad_mean_sd_mm"])
        production_date = (start + timedelta(days=offset)).date().isoformat()

        for shift_index, shift in enumerate(sampling["shifts"]):
            night_multiplier = 1 if shift["name"].lower() == "night" else 0
            for within_shift in range(sampling["samples_per_shift"]):
                sample_index = len(rows) + 1
                operator = operators[
                    (
                        production_day_index
                        + shift_index
                        + within_shift // sampling["operator_rotation_block_size"]
                    )
                    % len(operators)
                ]
                current_spec = variables["motor_current_a"]
                current = bounded_normal(
                    process_rng,
                    current_spec["base_mean"]
                    + operator["current_bias_a"]
                    + current_drift
                    + night_multiplier * current_spec["night_effect"],
                    current_spec["sd"],
                    current_spec["bounds"],
                    current_spec["digits"],
                    config["sampler_max_attempts"],
                )
                alignment_spec = variables["jaw_alignment_error_mm"]
                alignment = bounded_normal(
                    process_rng,
                    operator["alignment_mean_mm"]
                    + night_multiplier * alignment_spec["night_effect"],
                    alignment_spec["sd"],
                    alignment_spec["bounds"],
                    alignment_spec["digits"],
                    config["sampler_max_attempts"],
                )
                backlash_spec = variables["gear_backlash_deg"]
                backlash = bounded_normal(
                    process_rng,
                    backlash_mean,
                    backlash_spec["sd"],
                    backlash_spec["bounds"],
                    backlash_spec["digits"],
                    config["sampler_max_attempts"],
                )
                pad_spec = variables["pad_thickness_mm"]
                pad = bounded_normal(
                    process_rng,
                    pad_mean,
                    pad_spec["sd"],
                    pad_spec["bounds"],
                    pad_spec["digits"],
                    config["sampler_max_attempts"],
                )
                torque_spec = variables["fastener_torque_nm"]
                torque = bounded_normal(
                    process_rng,
                    operator["torque_mean_nm"],
                    torque_spec["sd"],
                    torque_spec["bounds"],
                    torque_spec["digits"],
                    config["sampler_max_attempts"],
                )
                part_residual = process_rng.normal(0.0, stage["part_residual_sd_n"])
                true_force = (
                    response["intercept"]
                    + response["current_coefficient"] * (current - response["current_center"])
                    + response["alignment_coefficient"] * alignment
                    + response["backlash_coefficient"] * backlash
                    + response["pad_coefficient"] * (pad - response["pad_center"])
                    + response["torque_coefficient"] * (torque - response["torque_center"])
                    + part_residual
                )
                appraiser = apps[(sample_index - 1) % len(apps)]
                force, zero = measure(true_force, appraiser, measurement_rng, config)
                target = specification["target_n"]
                lower = specification["lsl_n"]
                upper = specification["usl_n"]
                defect = force < lower or force > upper
                timestamp = start + timedelta(
                    days=offset,
                    hours=shift["start_hour"],
                    minutes=within_shift * sampling["interval_minutes"],
                )
                record_id = f"{stage['record_prefix']}-{sample_index:03d}"
                part_id = f"{stage['part_prefix']}-{sample_index:03d}"
                row = {
                    "record_id": record_id,
                    "sample_index": sample_index,
                    "part_id": part_id,
                    "measurement_timestamp_sgt": timestamp.isoformat(timespec="seconds"),
                    "production_date_sgt": production_date,
                    "batch_id": f"{stage['batch_prefix']}-{production_day_index + 1:02d}",
                    "process_stage": stage["process_stage"],
                    "shift": shift["name"],
                    "assembly_operator_id": operator["id"],
                    "appraiser_id": appraiser["id"],
                    "improvement_plan_id": stage["improvement_plan_id"],
                    "improvement_actions": stage["improvement_actions"],
                    "source_system": config["source_system"],
                    "motor_current_a": current,
                    "jaw_alignment_error_mm": alignment,
                    "gear_backlash_deg": backlash,
                    "pad_thickness_mm": pad,
                    "fastener_torque_nm": torque,
                    "sensor_zero_offset_n": zero,
                    "measured_force_n": force,
                    "target_n": target,
                    "lsl_n": lower,
                    "usl_n": upper,
                    "deviation_from_target_n": rnd(
                        force - target,
                        config["measurement"]["force_record_digits"],
                    ),
                    "spec_status": "Out of Specification" if defect else "Within Specification",
                    "defect_type": (
                        "Under Force" if force < lower else "Over Force" if force > upper else "No Defect"
                    ),
                    "defect_flag": int(defect),
                    **measurement_common(config),
                    "process_seed": process_seed,
                    "measurement_seed": measurement_seed,
                }
                rows.append(row)
                truths[part_id] = true_force
    return rows, truths


def build_msa(source_rows, source_truths, config):
    msa_config = config["msa"]
    appraisers = config["measurement"]["appraisers"]
    ranked = sorted(source_rows, key=lambda row: (row["measured_force_n"], row["part_id"]))
    selected = [
        ranked[math.floor(quantile * (len(ranked) - 1))]
        for quantile in msa_config["selection_quantiles"]
    ]
    seed = config["seeds"]["msa"]
    rng = RNG(seed)
    combinations = [
        (source, appraiser, replicate)
        for source in selected
        for appraiser in appraisers
        for replicate in range(1, msa_config["replicates"] + 1)
    ]
    combinations = rng.shuffle(combinations)
    start = datetime.fromisoformat(msa_config["start_timestamp_sgt"])
    rows = []
    for order, (source, appraiser, replicate) in enumerate(combinations, 1):
        true_force = source_truths[source["part_id"]]
        force, zero = measure(true_force, appraiser, rng, config)
        reference = rnd(true_force, msa_config["reference_record_digits"])
        timestamp = start + timedelta(minutes=(order - 1) * msa_config["interval_minutes"])
        rows.append(
            {
                "msa_record_id": f"MSA-{order:03d}",
                "measurement_order": order,
                "measurement_timestamp_sgt": timestamp.isoformat(timespec="seconds"),
                "part_id": source["part_id"],
                "source_baseline_record_id": source["record_id"],
                "source_process_stage": source["process_stage"],
                "appraiser_id": appraiser["id"],
                "replicate": replicate,
                "reference_force_n": reference,
                "reference_kind": "Synthetic latent truth; not a measurement",
                "measured_force_n": force,
                "measurement_error_n": rnd(
                    force - reference,
                    msa_config["reference_record_digits"],
                ),
                "sensor_zero_offset_n": zero,
                **measurement_common(config),
                "study_design": (
                    f"{len(selected)} source grippers x {len(appraisers)} appraisers x "
                    f"{msa_config['replicates']} full-cycle repeats; fully randomized"
                ),
                "synthetic_seed": seed,
            }
        )
    return rows


def definitions(config):
    return {
        "record_id": ("", "Unique EOL inspection record ID across the combined dataset."),
        "sample_index": ("", "Sequential sample number within each process stage; not a matched-pair identifier."),
        "part_id": ("", "Unique assembled electric-gripper ID; Before and After are independent production cohorts."),
        "measurement_timestamp_sgt": ("ISO 8601 UTC+08:00", "Synthetic timezone-aware inspection timestamp."),
        "production_date_sgt": ("YYYY-MM-DD", "Shift-start production date; remains fixed when a Night sample passes midnight."),
        "batch_id": ("", "Synthetic component batch ID; one batch covers both shifts of one production date."),
        "process_stage": ("", "Before Improvement or After Improvement."),
        "shift": ("", "Configured Day or Night production shift."),
        "assembly_operator_id": ("", "Assembly/setup attribution; not attendance evidence and not the measurement appraiser."),
        "appraiser_id": ("", "Synthetic person performing the force measurement."),
        "improvement_plan_id": ("", "NOT-APPLIED for baseline; IMP-EG-01 for the encoded After intervention package."),
        "improvement_actions": ("", "Stage-level intervention description; actions are assumed, not physically verified."),
        "source_system": ("", "Explicit synthetic origin; not a real MES export."),
        "motor_current_a": ("A", "Motor current under the stage-specific model; rejection-sampled bounded normal."),
        "jaw_alignment_error_mm": ("mm", "Post-assembly jaw alignment error; rejection-sampled bounded normal."),
        "gear_backlash_deg": ("degree", "Assumed transmission backlash; rejection-sampled bounded normal."),
        "pad_thickness_mm": ("mm", "Installed jaw-pad thickness; rejection-sampled bounded normal."),
        "fastener_torque_nm": ("N*m", "Assumed critical fastener torque; rejection-sampled bounded normal."),
        "sensor_zero_offset_n": ("N", "Synthetic pre-cycle zero residual generated by the shared measurement model."),
        "measured_force_n": ("N", "Single full-cycle load-cell reading quantized to the configured device resolution."),
        "target_n": ("N", "Demonstration target from configuration; not a validated product requirement."),
        "lsl_n": ("N", "Inclusive demonstration lower specification limit from configuration."),
        "usl_n": ("N", "Inclusive demonstration upper specification limit from configuration."),
        "deviation_from_target_n": ("N", "Quantized measured force minus target."),
        "spec_status": ("", "Within Specification when LSL <= force <= USL; otherwise Out of Specification."),
        "defect_type": ("", "No Defect, Under Force, or Over Force; outcome label rather than root cause."),
        "defect_flag": ("", "0 for within specification; 1 for outside specification."),
        "device_id": ("", "Same hypothetical measurement device across Before, MSA, and After."),
        "protocol_id": ("", "Same full-cycle measurement protocol across all datasets."),
        "test_block_id": ("", "Fixed hypothetical instrumented test block."),
        "test_block_diameter_mm": ("mm", "Assumed fixed nominal test-block diameter."),
        "closing_speed_mm_s": ("mm/s", "Assumed fixed commanded closing speed."),
        "hold_time_s": (
            "s",
            f"Assumed {config['measurement']['hold_time_s']} s hold before one reading; no time averaging.",
        ),
        "contact_distance_from_jaw_root_mm": ("mm", "Assumed fixed contact location; not CAD-verified."),
        "device_resolution_n": ("N", "Quantization step for measured_force_n in every dataset."),
        "ctq": ("", "Gripping Force; one compressive sensor reading, not a two-jaw sum."),
        "data_label": ("", f"{config['data_label']}; every observation and relationship is simulated."),
        "generation_model_version": ("", f"{config['version']}; code and configuration jointly define generation."),
        "process_seed": ("", "Stage-specific deterministic seed for synthetic process factors and latent part residuals."),
        "measurement_seed": ("", "Stage-specific deterministic seed for zero residuals and repeatability noise."),
        "msa_record_id": ("", "Unique synthetic MSA reading ID."),
        "measurement_order": ("", "Fully randomized synthetic MSA sequence number."),
        "source_baseline_record_id": ("", "Foreign key to the selected Before record."),
        "source_process_stage": ("", "Process stage from which the retained MSA part was selected."),
        "replicate": ("", "Full opening, removal, refixture, closing, and hold repeat number."),
        "reference_force_n": (
            "N",
            f"Latent model force rounded to {config['msa']['reference_record_digits']} decimals; audit-only and not traceably measured.",
        ),
        "reference_kind": ("", "Identifies the unmeasured synthetic reference."),
        "measurement_error_n": ("N", "Measured minus latent reference force; audit-only."),
        "study_design": ("", "Configuration-derived crossed MSA dimensions and randomization statement."),
        "synthetic_seed": ("", "Deterministic seed for MSA selection-order randomization and measurement simulation."),
    }


def data_dictionary(datasets, config):
    field_definitions = definitions(config)
    rows = []
    audit_only = {"reference_force_n", "reference_kind", "measurement_error_n"}
    outcomes = {
        "measured_force_n",
        "defect_flag",
        "spec_status",
        "defect_type",
        "deviation_from_target_n",
    }
    for filename, dataset in datasets:
        for key, value in dataset[0].items():
            unit, definition = field_definitions[key]
            data_type = "Integer" if isinstance(value, int) else "Numeric" if isinstance(value, float) else "Text"
            if key == "measurement_timestamp_sgt":
                data_type = "Datetime"
            elif key == "production_date_sgt":
                data_type = "Date"
            analysis_role = (
                "audit_only" if key in audit_only else "outcome_or_derived" if key in outcomes else "input_or_metadata"
            )
            rows.append(
                {
                    "dataset": filename,
                    "field_name": key,
                    "data_type": data_type,
                    "unit": unit,
                    "definition": definition,
                    "analysis_role": analysis_role,
                    "generation_reference": f"generation_config.json + generate_quality_data.py; {key}",
                    "data_label": config["data_label"],
                }
            )
    return rows


def csv_bytes(rows, config):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        output = dict(row)
        for key in ("measured_force_n", "target_n", "lsl_n", "usl_n", "deviation_from_target_n", "device_resolution_n"):
            if key in output:
                output[key] = f"{output[key]:.{config['measurement']['force_record_digits']}f}"
        for key in ("reference_force_n", "measurement_error_n"):
            if key in output:
                output[key] = f"{output[key]:.{config['msa']['reference_record_digits']}f}"
        if "sensor_zero_offset_n" in output:
            output["sensor_zero_offset_n"] = f"{output['sensor_zero_offset_n']:.3f}"
        writer.writerow(output)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def transactional_write_files(output_dir, payloads):
    """Replace a related file set as one transaction, restoring originals on failure."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.stage-", dir=output_dir.parent))
    backup_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.backup-", dir=output_dir.parent))
    committed = []
    backed_up = []
    try:
        for name, payload in payloads.items():
            staged = stage_dir / name
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(payload)
        for name in payloads:
            target = output_dir / name
            backup = backup_dir / name
            if target.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
                backed_up.append(name)
            os.replace(stage_dir / name, target)
            committed.append(name)
    except Exception:
        for name in reversed(committed):
            target = output_dir / name
            if target.exists():
                target.unlink()
        for name in reversed(backed_up):
            backup = backup_dir / name
            if backup.exists():
                os.replace(backup, output_dir / name)
        raise
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)
        shutil.rmtree(backup_dir, ignore_errors=True)


def capability(rows, config):
    values = [row["measured_force_n"] for row in rows]
    mean = st.mean(values)
    overall_sd = st.stdev(values)
    moving_ranges = [abs(current - previous) for previous, current in zip(values, values[1:])]
    mr_mean = st.mean(moving_ranges)
    analysis = config["analysis"]
    within_sd = mr_mean / analysis["imr_d2"]
    specification = config["specification"]
    lower = specification["lsl_n"]
    upper = specification["usl_n"]
    width = upper - lower
    control_multiplier = analysis["control_sigma_multiplier"]
    capability_multiplier = analysis["capability_sigma_multiplier"]
    i_lower = mean - control_multiplier * within_sd
    i_upper = mean + control_multiplier * within_sd
    mr_upper = analysis["mr_ucl_factor"] * mr_mean
    i_flags = [row["record_id"] for row in rows if row["measured_force_n"] < i_lower or row["measured_force_n"] > i_upper]
    mr_flags = [rows[index + 1]["record_id"] for index, value in enumerate(moving_ranges) if value > mr_upper]
    phase_i_in_control = not i_flags and not mr_flags
    return {
        "n": len(values),
        "mean_n": mean,
        "overall_sd_n": overall_sd,
        "observed_range_n": [min(values), max(values)],
        "defects": sum(row["defect_flag"] for row in rows),
        "defect_rate": st.mean(row["defect_flag"] for row in rows),
        "defect_types": dict(Counter(row["defect_type"] for row in rows)),
        "Pp_descriptive": width / (2 * capability_multiplier * overall_sd),
        "Ppk_descriptive": min(mean - lower, upper - mean) / (capability_multiplier * overall_sd),
        "Cp_MR_provisional": width / (2 * capability_multiplier * within_sd),
        "Cpk_MR_provisional": min(mean - lower, upper - mean) / (capability_multiplier * within_sd),
        "control_screen": {
            "method": "Phase I retrospective I-MR; configured sigma point rule only",
            "phase": "PHASE_I",
            "phase_i_in_control": phase_i_in_control,
            "phase_ii_status": "READY_TO_ESTABLISH" if phase_i_in_control else "NOT_ESTABLISHED",
            "phase_ii_note": (
                "Phase II prospective monitoring limits may only be carried forward from a "
                "demonstrably in-control Phase I; this sample has point-rule alarms."
                if not phase_i_in_control
                else "Phase I is in control under the configured point rule; Phase II limits can be carried forward."
            ),
            "i_lcl_n": i_lower,
            "i_ucl_n": i_upper,
            "mr_ucl_n": mr_upper,
            "i_flags": i_flags,
            "mr_flags": mr_flags,
        },
    }


def gage_rr(msa_rows, config):
    parts = sorted({row["part_id"] for row in msa_rows})
    appraisers = sorted({row["appraiser_id"] for row in msa_rows})
    replicates = sorted({row["replicate"] for row in msa_rows})
    values = {
        (row["part_id"], row["appraiser_id"], row["replicate"]): row["measured_force_n"]
        for row in msa_rows
    }
    part_count = len(parts)
    appraiser_count = len(appraisers)
    replicate_count = len(replicates)
    grand = st.mean(values.values())
    part_means = {
        part: st.mean(values[part, appraiser, replicate] for appraiser in appraisers for replicate in replicates)
        for part in parts
    }
    appraiser_means = {
        appraiser: st.mean(values[part, appraiser, replicate] for part in parts for replicate in replicates)
        for appraiser in appraisers
    }
    cell_means = {
        (part, appraiser): st.mean(values[part, appraiser, replicate] for replicate in replicates)
        for part in parts
        for appraiser in appraisers
    }
    ms_part = (
        appraiser_count
        * replicate_count
        * sum((value - grand) ** 2 for value in part_means.values())
        / (part_count - 1)
    )
    ms_appraiser = (
        part_count
        * replicate_count
        * sum((value - grand) ** 2 for value in appraiser_means.values())
        / (appraiser_count - 1)
    )
    ms_interaction = (
        replicate_count
        * sum(
            (cell_means[part, appraiser] - part_means[part] - appraiser_means[appraiser] + grand) ** 2
            for part in parts
            for appraiser in appraisers
        )
        / ((part_count - 1) * (appraiser_count - 1))
    )
    ms_repeatability = (
        sum(
            (value - cell_means[part, appraiser]) ** 2
            for (part, appraiser, replicate), value in values.items()
        )
        / (part_count * appraiser_count * (replicate_count - 1))
    )
    part_variance = max(0.0, (ms_part - ms_interaction) / (appraiser_count * replicate_count))
    appraiser_variance = max(0.0, (ms_appraiser - ms_interaction) / (part_count * replicate_count))
    interaction_variance = max(0.0, (ms_interaction - ms_repeatability) / replicate_count)
    repeatability_variance = ms_repeatability
    grr_variance = appraiser_variance + interaction_variance + repeatability_variance
    grr_sd = math.sqrt(grr_variance)
    part_sd = math.sqrt(part_variance)
    total_sd = math.sqrt(part_variance + grr_variance)
    specification = config["specification"]
    analysis = config["analysis"]
    pct_tolerance = (
        100
        * analysis["gage_study_sigma_multiplier"]
        * grr_sd
        / (specification["usl_n"] - specification["lsl_n"])
    )
    ndc = max(1, math.floor(analysis["ndc_multiplier"] * part_sd / grr_sd))
    return {
        "method": "Balanced crossed random-effects ANOVA; interaction retained; negative variance estimates floored at zero",
        "dimensions": {"parts": part_count, "appraisers": appraiser_count, "replicates": replicate_count},
        "reference_range_n": [
            min(row["reference_force_n"] for row in msa_rows),
            max(row["reference_force_n"] for row in msa_rows),
        ],
        "variance_components_n2": {
            "part": part_variance,
            "appraiser": appraiser_variance,
            "part_appraiser_interaction": interaction_variance,
            "repeatability": repeatability_variance,
            "total_gage_rr": grr_variance,
        },
        "part_sd_n": part_sd,
        "grr_sd_n": grr_sd,
        "pct_tolerance": pct_tolerance,
        "pct_study_variation": 100 * grr_sd / total_sd,
        "ndc": ndc,
        "acceptance": gage_rr_acceptance(pct_tolerance, ndc, analysis),
    }


def audit(before, after, combined, msa_rows, dictionary_rows, config, config_validation):
    checks = {}

    def check(name, condition):
        checks[name] = bool(condition)

    sampling = config["sampling"]
    expected_per_stage = (
        len(sampling["production_day_offsets"])
        * len(sampling["shifts"])
        * sampling["samples_per_shift"]
    )
    expected_msa = (
        len(config["msa"]["selection_quantiles"])
        * len(config["measurement"]["appraisers"])
        * config["msa"]["replicates"]
    )
    check("row_counts", len(before) == expected_per_stage and len(after) == expected_per_stage and len(combined) == 2 * expected_per_stage and len(msa_rows) == expected_msa)
    check("combined_exact", combined == before + after)
    check("unique_ids", len({row["record_id"] for row in combined}) == len(combined) and len({row["part_id"] for row in combined}) == len(combined))
    check("no_blank_main_cells", all(all(value != "" and value is not None for value in row.values()) for row in combined + msa_rows))
    check("synthetic_labels", all(row["data_label"] == config["data_label"] for row in combined + msa_rows + dictionary_rows))
    check("current_version", all(row["generation_model_version"] == config["version"] for row in combined + msa_rows))
    expected_before_times = expected_timestamps(config, config["stages"]["before"])
    expected_after_times = expected_timestamps(config, config["stages"]["after"])
    check("stage_timestamps", [row["measurement_timestamp_sgt"] for row in before] == expected_before_times and [row["measurement_timestamp_sgt"] for row in after] == expected_after_times)
    expected_offset = timedelta(hours=sampling["utc_offset_hours"])
    check("timezone_offsets", all(datetime.fromisoformat(row["measurement_timestamp_sgt"]).utcoffset() == expected_offset for row in combined + msa_rows))
    expected_production_dates = []
    expected_batches = []
    for stage_key in ("before", "after"):
        stage = config["stages"][stage_key]
        stage_start = datetime.fromisoformat(stage["start_date"])
        for production_day_index, offset in enumerate(sampling["production_day_offsets"]):
            for _shift in sampling["shifts"]:
                for _sample in range(sampling["samples_per_shift"]):
                    expected_production_dates.append((stage_start + timedelta(days=offset)).date().isoformat())
                    expected_batches.append(f"{stage['batch_prefix']}-{production_day_index + 1:02d}")
    check(
        "production_dates",
        [row["production_date_sgt"] for row in combined] == expected_production_dates
        and [row["batch_id"] for row in combined] == expected_batches,
    )
    resolution = Decimal(str(config["measurement"]["resolution_n"]))
    check("resolution", all(Decimal(str(row["measured_force_n"])) % resolution == 0 for row in combined + msa_rows))
    factor_fields = ["motor_current_a", "jaw_alignment_error_mm", "gear_backlash_deg", "pad_thickness_mm", "fastener_torque_nm"]
    boundaries_ok = True
    for stage_key, rows in (("before", before), ("after", after)):
        for field in factor_fields:
            lower, upper = config["stages"][stage_key]["variables"][field]["bounds"]
            boundaries_ok &= all(lower < row[field] < upper for row in rows)
            boundaries_ok &= not any(row[field] == lower or row[field] == upper for row in rows)
    check("no_boundary_pileup", boundaries_ok)
    specification = config["specification"]
    target, lower, upper = specification["target_n"], specification["lsl_n"], specification["usl_n"]
    check("specification", all((row["target_n"], row["lsl_n"], row["usl_n"]) == (target, lower, upper) for row in combined))
    check("outcomes", all(
        row["defect_flag"] == int(not lower <= row["measured_force_n"] <= upper)
        and row["spec_status"] == ("Out of Specification" if row["defect_flag"] else "Within Specification")
        and row["defect_type"] == ("Under Force" if row["measured_force_n"] < lower else "Over Force" if row["measured_force_n"] > upper else "No Defect")
        and abs(row["deviation_from_target_n"] - (row["measured_force_n"] - target)) < 1e-12
        for row in combined
    ))
    check("improvement_metadata", all(row["improvement_plan_id"] == config["stages"]["before"]["improvement_plan_id"] for row in before) and all(row["improvement_plan_id"] == config["stages"]["after"]["improvement_plan_id"] for row in after))
    before_by_record = {row["record_id"]: row for row in before}
    check("msa_foreign_keys", all(row["source_baseline_record_id"] in before_by_record and before_by_record[row["source_baseline_record_id"]]["part_id"] == row["part_id"] for row in msa_rows))
    check("msa_unique_ids_and_timestamps", len({row["msa_record_id"] for row in msa_rows}) == len(msa_rows) and len({row["measurement_timestamp_sgt"] for row in msa_rows}) == len(msa_rows))
    check("msa_source_stage", all(row["source_process_stage"] == config["stages"]["before"]["process_stage"] for row in msa_rows))
    cells = Counter((row["part_id"], row["appraiser_id"], row["replicate"]) for row in msa_rows)
    check("msa_crossed", len(cells) == expected_msa and set(cells.values()) == {1})
    check("msa_order_integrity", [row["measurement_order"] for row in msa_rows] == list(range(1, expected_msa + 1)) and config["msa"]["randomization"] == "All part-appraiser-replicate combinations shuffled in one complete sequence")
    check("msa_fixed_references", all(len({row["reference_force_n"] for row in msa_rows if row["part_id"] == part}) == 1 for part in {row["part_id"] for row in msa_rows}))
    common = measurement_common(config)
    check("shared_protocol", all(all(row[key] == value for key, value in common.items()) for row in combined + msa_rows))
    datasets = {"quality_baseline.csv": before, "quality_before_after.csv": combined, "quality_msa.csv": msa_rows}
    check("dictionary_coverage", all({row["field_name"] for row in dictionary_rows if row["dataset"] == filename} == set(rows[0]) for filename, rows in datasets.items()))
    check("dictionary_unique_keys", len({(row["dataset"], row["field_name"]) for row in dictionary_rows}) == len(dictionary_rows))
    check("dictionary_required_metadata", all(row["definition"] and row["analysis_role"] and row["generation_reference"] and row["data_label"] == config["data_label"] for row in dictionary_rows))
    check("residual_sd_unchanged", config["stages"]["before"]["part_residual_sd_n"] == config["stages"]["after"]["part_residual_sd_n"])

    before_metrics = capability(before, config)
    after_metrics = capability(after, config)
    width = upper - lower
    check(
        "capability_standard_formula",
        abs(before_metrics["Pp_descriptive"] - width / (6 * before_metrics["overall_sd_n"])) < 1e-12
        and abs(after_metrics["Pp_descriptive"] - width / (6 * after_metrics["overall_sd_n"])) < 1e-12
        and abs(before_metrics["Ppk_descriptive"] - min(before_metrics["mean_n"] - lower, upper - before_metrics["mean_n"]) / (3 * before_metrics["overall_sd_n"])) < 1e-12
        and abs(after_metrics["Ppk_descriptive"] - min(after_metrics["mean_n"] - lower, upper - after_metrics["mean_n"]) / (3 * after_metrics["overall_sd_n"])) < 1e-12,
    )
    alternate_config = json.loads(json.dumps(config))
    alternate_config["analysis"]["control_sigma_multiplier"] += 0.5
    alternate_before_metrics = capability(before, alternate_config)
    check(
        "capability_independent_of_control_multiplier",
        before_metrics["Pp_descriptive"] == alternate_before_metrics["Pp_descriptive"]
        and before_metrics["Ppk_descriptive"] == alternate_before_metrics["Ppk_descriptive"]
        and before_metrics["control_screen"]["i_lcl_n"] != alternate_before_metrics["control_screen"]["i_lcl_n"],
    )
    return {
        "release": {
            "version": config["version"],
            "status": config["release_status"],
            "v3_status": "RETIRED",
            "v4_status": "SUPERSEDED",
            "data_label": config["data_label"],
        },
        "configuration_validation": config_validation,
        "structural_checks": checks,
        "structural_status": "PASS" if all(checks.values()) else "FAIL",
        "expected_counts_from_config": {
            "per_process_stage": expected_per_stage,
            "before_after_total": 2 * expected_per_stage,
            "msa": expected_msa,
        },
        "before": before_metrics,
        "after": after_metrics,
        "improvement_comparison": {
            "mean_shift_toward_target_n": abs(before_metrics["mean_n"] - target) - abs(after_metrics["mean_n"] - target),
            "overall_sd_reduction_pct": 100 * (1 - after_metrics["overall_sd_n"] / before_metrics["overall_sd_n"]),
            "defect_rate_reduction_percentage_points": 100 * (before_metrics["defect_rate"] - after_metrics["defect_rate"]),
            "Ppk_change": after_metrics["Ppk_descriptive"] - before_metrics["Ppk_descriptive"],
            "interpretation": "Synthetic scenario comparison only; not evidence that real interventions caused these effects.",
        },
        "msa": gage_rr(msa_rows, config),
        "limitations": [
            "All physics, ranges, coefficients, interventions, identities, timestamps and measurement behavior are synthetic assumptions.",
            "Before and After are independent production cohorts, not repeated measurements of the same grippers.",
            "The After improvement is encoded in model parameters, so statistical improvement is scenario output rather than discovered causal evidence.",
            f"The unobserved part residual has the same {config['stages']['before']['part_residual_sd_n']:g} N SD in Before and After; only observable process-factor distributions encode improvement.",
            "Capability indices remain descriptive or provisional until control-chart assumptions and all relevant stability checks are accepted.",
            "No rows were deleted and the declared seeds were not searched for favorable statistical results.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("generation_config.json"))
    parser.add_argument("--output", type=Path, default=Path("regenerated"))
    parser.add_argument("--check", action="store_true", help="Compare all four CSV files and the validation report to regeneration without writing.")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    try:
        config_validation = validate_config(config)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    before, before_truths = build_stage("before", config)
    after, _ = build_stage("after", config)
    combined = before + after
    msa_rows = build_msa(before, before_truths, config)
    datasets = [
        ("quality_baseline.csv", before),
        ("quality_before_after.csv", combined),
        ("quality_msa.csv", msa_rows),
    ]
    dictionary_rows = data_dictionary(datasets, config)
    files = {
        filename: csv_bytes(rows, config)
        for filename, rows in datasets + [("six_sigma_data_dictionary.csv", dictionary_rows)]
    }
    report = audit(before, after, combined, msa_rows, dictionary_rows, config, config_validation)
    report["sha256"] = {filename: sha256_bytes(content) for filename, content in files.items()}
    report["source_sha256"] = {
        "generation_config.json": sha256_bytes(args.config.read_bytes()),
        "generate_quality_data.py": sha256_bytes(Path(__file__).read_bytes()),
    }
    if report["structural_status"] != "PASS":
        raise SystemExit("Structural audit failed before commit; no output files were changed")
    report_bytes = (json.dumps(report, indent=2) + "\n").encode("utf-8")
    deliverables = {**files, "validation_report.json": report_bytes}

    if args.check:
        reproduction = {
            filename: (args.output / filename).read_bytes() == content
            for filename, content in deliverables.items()
        }
        if not all(reproduction.values()):
            raise SystemExit("Reproduction mismatch")
        display_report = {**report, "byte_reproduction": reproduction}
    else:
        transactional_write_files(args.output, deliverables)
        display_report = report
    print(json.dumps(display_report, indent=2))


if __name__ == "__main__":
    main()
