"""Regenerate the complete V5 Six Sigma chart set from validated synthetic CSV files."""

import argparse
import csv
import hashlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from generate_quality_data import (
    CONTROL_STATUSES,
    OPEN_CONTROL_STATUSES,
    capability,
    gage_rr,
    gage_rr_acceptance,
    validate_config,
)


BEFORE_COLOR = "#2563EB"
AFTER_COLOR = "#16A34A"
SPEC_COLOR = "#DC2626"
TARGET_COLOR = "#F59E0B"
TEXT_COLOR = "#172033"
GRID_COLOR = "#D9E2F0"

FACTOR_SPECS = [
    ("motor_current_a", "Motor current", "A", "Machine", "current_coefficient", "Closed-loop current recipe and deviation alarm"),
    ("jaw_alignment_error_mm", "Jaw alignment error", "mm", "Method", "alignment_coefficient", "Alignment poka-yoke fixture and first-off confirmation"),
    ("gear_backlash_deg", "Gear backlash", "degree", "Machine", "backlash_coefficient", "Incoming backlash screening and lot containment"),
    ("pad_thickness_mm", "Pad thickness", "mm", "Material", "pad_coefficient", "Incoming thickness screening and lot traceability"),
    ("fastener_torque_nm", "Fastener torque", "N*m", "Method", "torque_coefficient", "Program-controlled torque screwdriver with result logging"),
]

STATUS_DISPLAY = {
    "PASS": "PASS",
    "PASS_SAMPLE_ONLY": "PASS (SAMPLE)",
    "PROVISIONAL": "PROVISIONAL",
    "WATCH": "WATCH",
    "CONDITIONAL": "CONDITIONAL",
    "UNACCEPTABLE": "UNACCEPTABLE",
    "ACTION_REQUIRED": "ACTION",
}

STATUS_COLORS = {
    "PASS": "#DCFCE7",
    "PASS_SAMPLE_ONLY": "#DCFCE7",
    "PROVISIONAL": "#E0F2FE",
    "WATCH": "#FEF3C7",
    "CONDITIONAL": "#FFEDD5",
    "UNACCEPTABLE": "#FEE2E2",
    "ACTION_REQUIRED": "#FEE2E2",
}

STATUS_TEXT_COLORS = {
    "PASS": "#166534",
    "PASS_SAMPLE_ONLY": "#166534",
    "PROVISIONAL": "#075985",
    "WATCH": "#92400E",
    "CONDITIONAL": "#9A3412",
    "UNACCEPTABLE": "#991B1B",
    "ACTION_REQUIRED": "#991B1B",
}


def configure_style():
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": GRID_COLOR,
            "axes.labelcolor": TEXT_COLOR,
            "axes.titlecolor": TEXT_COLOR,
            "axes.titleweight": "bold",
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "xtick.color": TEXT_COLOR,
            "ytick.color": TEXT_COLOR,
            "grid.color": GRID_COLOR,
            "grid.alpha": 0.7,
            "legend.frameon": False,
        }
    )


def footer(fig, version, data_label):
    fig.text(
        0.99,
        -0.012,
        f"{data_label} — scenario demonstration only | {version}",
        ha="right",
        va="bottom",
        fontsize=8,
        color="#64748B",
    )


def save_figure(fig, path, version, data_label):
    footer(fig, version, data_label)
    temporary_path = path.with_name(f".{path.stem}.tmp.png")
    try:
        temporary_path.unlink(missing_ok=True)
        buffer = io.BytesIO()
        fig.savefig(buffer, dpi=180, bbox_inches="tight", pad_inches=0.16, facecolor="white", format="png")
        payload = buffer.getvalue()
        if not payload:
            raise RuntimeError(f"Chart render produced an empty file: {path.name}")
        temporary_path.write_bytes(payload)
        temporary_path.replace(path)
    finally:
        plt.close(fig)
        temporary_path.unlink(missing_ok=True)


def add_spec_lines(axis, lsl, target, usl, horizontal=False, labels=True):
    line = axis.axhline if horizontal else axis.axvline
    line(lsl, color=SPEC_COLOR, linestyle="--", linewidth=1.4, label="LSL" if labels else None)
    line(target, color=TARGET_COLOR, linestyle="-", linewidth=1.4, label="Target" if labels else None)
    line(usl, color=SPEC_COLOR, linestyle="--", linewidth=1.4, label="USL" if labels else None)


def normal_pdf(x, mean, sd):
    return np.exp(-0.5 * ((x - mean) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def equivalent(actual, expected, rel_tol=1e-10, abs_tol=1e-12):
    """Recursively compare recomputed metrics with the signed validation report."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            equivalent(actual[key], expected[key], rel_tol, abs_tol) for key in actual
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            equivalent(left, right, rel_tol, abs_tol) for left, right in zip(actual, expected)
        )
    if isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return math.isclose(float(actual), float(expected), rel_tol=rel_tol, abs_tol=abs_tol)
    return actual == expected


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def ppk_relation_phrase(pk, reference):
    """'below' or 'meets' depending on whether the observed Ppk clears the reference."""
    return "below" if pk < reference else "meets"


def gage_acceptance_note(acceptance):
    """Short prose label for a Gage R&R acceptance classification."""
    return {
        "PASS": "acceptable",
        "CONDITIONAL": "conditional, not unconditional acceptance",
        "UNACCEPTABLE": "unacceptable",
    }[acceptance]


def figure08_interpretation(report):
    m = report["msa"]
    return (
        f"Gage R&R is {m['pct_tolerance']:.2f}% of tolerance with ndc {m['ndc']}; "
        f"classification {m['acceptance']} ({gage_acceptance_note(m['acceptance'])})."
    )


def figure12_interpretation(report, ppk_ref):
    after = report["after"]
    alarms = len(after["control_screen"]["mr_flags"]) + len(after["control_screen"]["i_flags"])
    ppk_relation = ppk_relation_phrase(after["Ppk_descriptive"], ppk_ref)
    msa_acceptance = report["msa"]["acceptance"]
    summary = (
        f"{alarms} After point-rule alarm(s); Ppk {ppk_relation} {ppk_ref:g}; "
        f"Gage R&R {msa_acceptance}."
    )
    blockers = []
    if alarms:
        blockers.append("I-MR stability")
    if ppk_relation == "below":
        blockers.append("Ppk reference")
    if msa_acceptance != "PASS":
        blockers.append(f"Gage R&R {msa_acceptance}")
    if blockers:
        return f"{summary} Open blockers: {', '.join(blockers)}."
    return (
        f"{summary} No listed stability, capability-reference or Gage R&R blocker remains; "
        "verify every Control Plan item before closure."
    )


def interpretation_branch_checks(config, report):
    """Exercise text and acceptance branches with controlled probes, independent of current results."""
    analysis = config["analysis"]
    pass_pct = analysis["gage_rr_tolerance_pass_pct"]
    fail_pct = analysis["gage_rr_tolerance_fail_pct"]
    ndc_min = analysis["gage_rr_ndc_min"]
    conditional_pct = (pass_pct + fail_pct) / 2
    probe_report = json.loads(json.dumps(report))
    probe_report["after"]["control_screen"]["i_flags"] = []
    probe_report["after"]["control_screen"]["mr_flags"] = []
    ppk_ref = analysis["ppk_reference_min"]
    below_pk = ppk_ref - max(abs(ppk_ref) * 0.01, 1e-6)

    figure08_checks = {}
    for acceptance in ("PASS", "CONDITIONAL", "UNACCEPTABLE"):
        candidate = json.loads(json.dumps(probe_report))
        candidate["msa"]["acceptance"] = acceptance
        figure08_checks[f"figure08_{acceptance.lower()}_text"] = (
            f"classification {acceptance} ({gage_acceptance_note(acceptance)})"
            in figure08_interpretation(candidate)
        )

    passing = json.loads(json.dumps(probe_report))
    passing["after"]["Ppk_descriptive"] = ppk_ref
    passing["msa"]["acceptance"] = "PASS"
    passing_text = figure12_interpretation(passing, ppk_ref)
    failing = json.loads(json.dumps(probe_report))
    failing["after"]["Ppk_descriptive"] = below_pk
    failing["after"]["control_screen"]["mr_flags"] = ["PROBE-001"]
    failing["msa"]["acceptance"] = "CONDITIONAL"
    failing_text = figure12_interpretation(failing, ppk_ref)

    return {
        "ppk_below_branch": ppk_relation_phrase(below_pk, ppk_ref) == "below",
        "ppk_meets_branch": ppk_relation_phrase(ppk_ref, ppk_ref) == "meets",
        "gage_pass_branch": gage_rr_acceptance(pass_pct, ndc_min, analysis) == "PASS",
        "gage_conditional_branch": gage_rr_acceptance(conditional_pct, ndc_min, analysis) == "CONDITIONAL",
        "gage_unacceptable_pct_branch": gage_rr_acceptance(fail_pct + 1e-6, ndc_min, analysis) == "UNACCEPTABLE",
        "gage_unacceptable_ndc_branch": gage_rr_acceptance(pass_pct, max(ndc_min - 1, 0), analysis) == "UNACCEPTABLE",
        **figure08_checks,
        "figure12_passing_items_not_blockers": (
            f"Ppk meets {ppk_ref:g}" in passing_text
            and "Gage R&R PASS" in passing_text
            and "Open blockers:" not in passing_text
        ),
        "figure12_failure_items_are_blockers": (
            f"Ppk below {ppk_ref:g}" in failing_text
            and "Open blockers: I-MR stability, Ppk reference, Gage R&R CONDITIONAL." in failing_text
        ),
    }


def manifest_interpretation_checks(chart_rows, report, ppk_ref):
    """Verify the actual rows queued for the manifest use the dynamic interpretation functions."""
    by_file = {row["chart_file"]: row for row in chart_rows}
    return {
        "figure08_manifest_row_matches": (
            by_file.get("08_msa_variance_components.png", {}).get("interpretation")
            == figure08_interpretation(report)
        ),
        "figure12_manifest_row_matches": (
            by_file.get("12_control_plan_readiness.png", {}).get("interpretation")
            == figure12_interpretation(report, ppk_ref)
        ),
    }


def manifest_file_checks(manifest_path, chart_rows, report, ppk_ref):
    """Read the staged CSV back before commit and validate its exact interpretation fields."""
    with manifest_path.open(encoding="utf-8-sig", newline="") as stream:
        written_rows = list(csv.DictReader(stream))
    row_checks = manifest_interpretation_checks(written_rows, report, ppk_ref)
    return {
        "manifest_roundtrip_matches": written_rows == chart_rows,
        "figure08_manifest_file_matches": row_checks["figure08_manifest_row_matches"],
        "figure12_manifest_file_matches": row_checks["figure12_manifest_row_matches"],
    }


def regression_diagnostics(frame):
    fields = [item[0] for item in FACTOR_SPECS]
    x = frame[fields].to_numpy(float)
    y = frame["measured_force_n"].to_numpy(float)
    x_design = np.column_stack([np.ones(len(x)), x])
    coefficients = np.linalg.lstsq(x_design, y, rcond=None)[0]
    predictions = x_design @ coefficients
    ss_total = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1 - float(np.sum((y - predictions) ** 2)) / ss_total
    standardized_x = (x - np.mean(x, axis=0)) / np.std(x, axis=0, ddof=1)
    standardized_y = (y - np.mean(y)) / np.std(y, ddof=1)
    standardized = np.linalg.lstsq(
        np.column_stack([np.ones(len(x)), standardized_x]), standardized_y, rcond=None
    )[0][1:]
    return {
        "r_squared": r_squared,
        "coefficients": dict(zip(fields, coefficients[1:])),
        "standardized_beta": dict(zip(fields, standardized)),
    }


def build_root_cause_rows(before, after, config):
    diagnostics = regression_diagnostics(before)
    rows = []
    for field, label, unit, category, coefficient_key, action in FACTOR_SPECS:
        model_coefficient = float(config["response"][coefficient_key])
        before_mean = round(float(before[field].mean()), 12)
        after_mean = round(float(after[field].mean()), 12)
        before_sd = round(float(before[field].std(ddof=1)), 12)
        after_sd = round(float(after[field].std(ddof=1)), 12)
        sd_reduction_pct = round(100 * (1 - after_sd / before_sd), 12)
        contribution = round(model_coefficient * (after_mean - before_mean), 12)
        rows.append(
            {
                "factor": field,
                "factor_label": label,
                "category": category,
                "unit": unit,
                "model_coefficient_n_per_unit": model_coefficient,
                "before_mean": before_mean,
                "after_mean": after_mean,
                "before_sd": before_sd,
                "after_sd": after_sd,
                "sd_reduction_pct": sd_reduction_pct,
                "modeled_mean_shift_contribution_n": contribution,
                "before_ols_coefficient_n_per_unit": round(diagnostics["coefficients"][field], 12),
                "before_standardized_beta": round(diagnostics["standardized_beta"][field], 12),
                "evidence_status": "SCENARIO_ENCODED_RELATIONSHIP",
                "control_action": action,
                "causal_limit": "Scenario-encoded relationship; requires real DOE/process data before a physical causal claim.",
                "data_label": config["data_label"],
                "generation_model_version": config["version"],
            }
        )
    rows.sort(key=lambda row: abs(row["modeled_mean_shift_contribution_n"]), reverse=True)
    baseline_ranks = {
        row["factor"]: rank
        for rank, row in enumerate(
            sorted(rows, key=lambda item: abs(item["before_standardized_beta"]), reverse=True), 1
        )
    }
    ranked_rows = [
        {
            "centering_priority_rank": rank,
            "baseline_variation_rank": baseline_ranks[row["factor"]],
            **row,
        }
        for rank, row in enumerate(rows, 1)
    ]
    assessed_specs = [
        ("people_operator", "Operator (people)", "People", "operator study / inter-operator comparison"),
        ("measurement_system", "Measurement system", "Measurement", "a full MSA on the real device"),
        ("environment", "Environment", "Environment", "environmental monitoring (temperature, humidity, vibration) during trials"),
    ]
    assessed_rows = [
        {
            "centering_priority_rank": rank,
            "baseline_variation_rank": "",
            "factor": factor,
            "factor_label": label,
            "category": category,
            "unit": "",
            "model_coefficient_n_per_unit": "",
            "before_mean": "",
            "after_mean": "",
            "before_sd": "",
            "after_sd": "",
            "sd_reduction_pct": "",
            "modeled_mean_shift_contribution_n": "",
            "before_ols_coefficient_n_per_unit": "",
            "before_standardized_beta": "",
            "evidence_status": "ASSESSED_NO_SYNTHETIC_EFFECT",
            "control_action": f"Assessed as candidate cause but not encoded in the synthetic scenario; assess via {action} before any causal claim.",
            "causal_limit": "Not represented in the synthetic response model; no synthetic evidence for or against a causal effect.",
            "data_label": config["data_label"],
            "generation_model_version": config["version"],
        }
        for rank, (factor, label, category, action) in enumerate(assessed_specs, start=6)
    ]
    return ranked_rows + assessed_rows, diagnostics


def statistical_window(frame, field, configured_bounds):
    mean = float(frame[field].mean())
    sd = float(frame[field].std(ddof=1))
    return max(configured_bounds[0], mean - 3 * sd), min(configured_bounds[1], mean + 3 * sd)


def build_control_plan_rows(after, config, report):
    version = config["version"]
    label = config["data_label"]
    analysis = config["analysis"]
    specification = config["specification"]
    ppk_ref = analysis["ppk_reference_min"]
    gage_pass = analysis["gage_rr_tolerance_pass_pct"]
    gage_fail = analysis["gage_rr_tolerance_fail_pct"]
    gage_ndc = analysis["gage_rr_ndc_min"]
    phase_i_in_control = report["after"]["control_screen"]["phase_i_in_control"]
    if not phase_i_in_control:
        capability_status = "PROVISIONAL"
    elif report["after"]["Ppk_descriptive"] < ppk_ref:
        capability_status = "WATCH"
    else:
        capability_status = "PASS"
    gage_reaction = {
        "PASS": "No corrective action; maintain scheduled recalibration and re-MSA cadence.",
        "CONDITIONAL": "For conditional result, review appraiser bias, fixture repeatability and calibration; document intended use before acceptance.",
        "UNACCEPTABLE": "Stop using the measurement system for capability decisions; complete root-cause and corrective action; re-run the MSA before any release or capability claim.",
    }[report["msa"]["acceptance"]]
    factor_rows = []
    factor_controls = {
        "motor_current_a": ("PLC/current trace", "Every cycle", "Process Engineer"),
        "jaw_alignment_error_mm": ("Alignment gauge", "First-off and every 20 units", "Production Supervisor"),
        "gear_backlash_deg": ("Backlash fixture", "5 units per incoming lot", "Incoming Quality"),
        "pad_thickness_mm": ("Digital micrometer", "5 units per incoming lot", "Incoming Quality"),
        "fastener_torque_nm": ("Program-controlled torque tool", "Every assembly", "Production Supervisor"),
    }
    for field, label_text, unit, _category, _coefficient_key, action in FACTOR_SPECS:
        lower, upper = statistical_window(after, field, config["stages"]["after"]["variables"][field]["bounds"])
        method, frequency, owner = factor_controls[field]
        factor_rows.append(
            {
                "control_item": label_text,
                "control_type": "Process input",
                "characteristic": field,
                "method": method,
                "sample_size_frequency": frequency,
                "phase_i_descriptive_window": f"{lower:.3f} to {upper:.3f} {unit}",
                "approved_action_limit": "TBD",
                "limit_basis": "Phase I descriptive window (After sample mean +/- 3 sample SD, clipped to synthetic bounds); not an action limit and not an engineering tolerance",
                "current_evidence": "Window and its 0/200 inside-count derive from the same After sample; not independent evidence for a control action limit",
                "owner_role": owner,
                "reaction_plan": f"Hold affected unit/lot; verify measurement; restore standard setting; investigate assignable cause; release only after recheck. Maintain: {action}.",
                "record": "MES quality/process parameter record",
                "current_status": "PROVISIONAL",
                "data_label": label,
                "generation_model_version": version,
            }
        )
    fixed_rows = [
        {
            "control_item": "Gripping force CTQ",
            "control_type": "Product output",
            "characteristic": "measured_force_n",
            "method": f"{config['measurement']['device_id']} under {config['measurement']['protocol_id']}",
            "sample_size_frequency": "Every finished unit",
            "phase_i_descriptive_window": "N/A — specification-governed",
            "approved_action_limit": f"{specification['lsl_n']:.2f} to {specification['usl_n']:.2f} N inclusive; target {specification['target_n']:.2f} N",
            "limit_basis": "Demonstration product specification from generation_config.json",
            "current_evidence": f"{report['after']['defects']} of {report['after']['n']} After units out of specification",
            "owner_role": "Quality Inspector",
            "reaction_plan": "Segregate any nonconforming unit; stop release; confirm test setup; create NCR; investigate process inputs before restart.",
            "record": "MES EOL inspection record",
            "current_status": "PASS_SAMPLE_ONLY" if report["after"]["defects"] == 0 else "ACTION_REQUIRED",
            "data_label": label,
            "generation_model_version": version,
        },
        {
            "control_item": "Sensor zero offset",
            "control_type": "Measurement system",
            "characteristic": "sensor_zero_offset_n",
            "method": "Pre-cycle zero check",
            "sample_size_frequency": "Before each shift and after fixture/sensor disturbance",
            "phase_i_descriptive_window": f"{config['measurement']['zero_offset_bounds_n'][0]:.2f} to {config['measurement']['zero_offset_bounds_n'][1]:.2f} N",
            "approved_action_limit": "TBD",
            "limit_basis": "Synthetic measurement-model bounds; real calibration limit not established",
            "current_evidence": "Recorded for every synthetic observation",
            "owner_role": "Quality Technician",
            "reaction_plan": "Stop measurement; inspect fixture and sensor; zero/calibrate using approved standard; repeat affected measurements.",
            "record": "Calibration/zero-check log",
            "current_status": "PROVISIONAL",
            "data_label": label,
            "generation_model_version": version,
        },
        {
            "control_item": "I-MR stability",
            "control_type": "Statistical process control",
            "characteristic": "measured_force_n in chronological order",
            "method": "Phase I retrospective I-MR; Phase II prospective screen pending a stable Phase I",
            "sample_size_frequency": "Phase I: this 200-unit window; Phase II (once established): review every shift",
            "phase_i_descriptive_window": f"I: {report['after']['control_screen']['i_lcl_n']:.3f} to {report['after']['control_screen']['i_ucl_n']:.3f} N; MR UCL {report['after']['control_screen']['mr_ucl_n']:.3f} N",
            "approved_action_limit": "TBD",
            "limit_basis": f"Phase I trial limits from the After sample; Phase II status {report['after']['control_screen']['phase_ii_status']}",
            "current_evidence": f"MR alarms: {', '.join(report['after']['control_screen']['mr_flags']) or 'none'}; Phase I in control: {report['after']['control_screen']['phase_i_in_control']}",
            "owner_role": "Quality Engineer",
            "reaction_plan": "Contain production since last accepted point; verify measurement; stratify by shift/operator/batch; remove special cause; recalculate only after stability review.",
            "record": "SPC review log and CAPA",
            "current_status": "ACTION_REQUIRED" if not report["after"]["control_screen"]["phase_i_in_control"] else "PASS",
            "data_label": label,
            "generation_model_version": version,
        },
        {
            "control_item": "Process capability",
            "control_type": "Performance review",
            "characteristic": "Ppk",
            "method": "Rolling descriptive Ppk after stability acceptance",
            "sample_size_frequency": "Monthly and after material/tool/process change; minimum 200 units",
            "phase_i_descriptive_window": f"After Ppk = {report['after']['Ppk_descriptive']:.3f}",
            "approved_action_limit": "TBD",
            "limit_basis": f"Project reference criterion Ppk >= {ppk_ref:g}; not a customer-approved requirement",
            "current_evidence": f"After Ppk = {report['after']['Ppk_descriptive']:.3f}; Phase I in control: {phase_i_in_control}",
            "owner_role": "Quality Engineer",
            "reaction_plan": "Do not release a capability claim; address stability alarms; review centering and factor variation; repeat capability study.",
            "record": "Monthly capability review",
            "current_status": capability_status,
            "data_label": label,
            "generation_model_version": version,
        },
        {
            "control_item": "Gage R&R",
            "control_type": "Measurement system review",
            "characteristic": "%Tolerance and ndc",
            "method": "Crossed Gage R&R ANOVA",
            "sample_size_frequency": "Quarterly and after device/fixture/appraiser/protocol change",
            "phase_i_descriptive_window": f"%Tolerance = {report['msa']['pct_tolerance']:.2f}%; ndc = {report['msa']['ndc']}",
            "approved_action_limit": "TBD",
            "limit_basis": f"Common project screening guidance (<= {gage_pass:g}% pass, {gage_pass:g}-{gage_fail:g}% conditional, > {gage_fail:g}% unacceptable, ndc >= {gage_ndc}); customer/industry acceptance must supersede",
            "current_evidence": f"%Tolerance = {report['msa']['pct_tolerance']:.2f}%; ndc = {report['msa']['ndc']}",
            "owner_role": "Measurement System Owner",
            "reaction_plan": gage_reaction,
            "record": "MSA study record",
            "current_status": report["msa"]["acceptance"],
            "data_label": label,
            "generation_model_version": version,
        },
    ]
    return [fixed_rows[0], *factor_rows, *fixed_rows[1:]]


def build_analysis_report(root_causes, control_plan, diagnostics, report, config):
    modeled = [row for row in root_causes if row["evidence_status"] == "SCENARIO_ENCODED_RELATIONSHIP"]
    assessed = [row for row in root_causes if row["evidence_status"] == "ASSESSED_NO_SYNTHETIC_EFFECT"]
    assessed_categories = ", ".join(a["category"] for a in assessed)
    modeled_shift = sum(row["modeled_mean_shift_contribution_n"] for row in modeled)
    observed_shift = report["after"]["mean_n"] - report["before"]["mean_n"]
    target_n = config["specification"]["target_n"]
    lsl_n = config["specification"]["lsl_n"]
    usl_n = config["specification"]["usl_n"]
    ppk_ref = config["analysis"]["ppk_reference_min"]
    residual_sd_n = config["stages"]["before"]["part_residual_sd_n"]
    data_label = config["data_label"]
    msa_acceptance = report["msa"]["acceptance"]
    gage_wording = {
        "PASS": "acceptable",
        "CONDITIONAL": "conditional, not unconditional acceptance",
        "UNACCEPTABLE": "unacceptable",
    }[msa_acceptance]
    after_pk = report["after"]["Ppk_descriptive"]
    after_in_control = report["after"]["control_screen"]["phase_i_in_control"]
    after_mr = report["after"]["control_screen"]["mr_flags"]
    pk_clause = f"Ppk {after_pk:.4f} is below the {ppk_ref:g} reference" if after_pk < ppk_ref else f"Ppk {after_pk:.4f} meets the {ppk_ref:g} reference"
    phase_clause = "Phase I is in control; Phase II limits can be carried forward" if after_in_control else "Phase I is not in control, so Phase II limits are not established"
    top = modeled[:3]
    root_table = "\n".join(
        f"| {row['centering_priority_rank']} | {row['factor_label']} | {row['category']} | {row['modeled_mean_shift_contribution_n']:.4f} | {row['sd_reduction_pct']:.1f}% | {row['before_standardized_beta']:.3f} |"
        for row in modeled
    )
    control_table = "\n".join(
        f"| {row['control_item']} | {row['sample_size_frequency']} | {row['approved_action_limit']} | {row['current_status']} | {row['owner_role']} |"
        for row in control_plan
    )
    return f"""# Six Sigma Analysis Report — {config['version']}

> **{data_label}.** This report describes a reproducible scenario, not measured equipment performance or verified physical causation.

## Executive summary

- CTQ: gripping force; Target {target_n:.2f} N; LSL {lsl_n:.2f} N; USL {usl_n:.2f} N.
- Before: mean {report['before']['mean_n']:.5f} N, SD {report['before']['overall_sd_n']:.5f} N, Ppk {report['before']['Ppk_descriptive']:.4f}, {report['before']['defects']} observed defects in 200 units.
- After: mean {report['after']['mean_n']:.5f} N, SD {report['after']['overall_sd_n']:.5f} N, Ppk {report['after']['Ppk_descriptive']:.4f}, {report['after']['defects']} observed defects in 200 units.
- The After sample is better centered and narrower; {pk_clause}; MR alarms at {', '.join(after_mr) or 'none'}; {phase_clause}.
- Gage R&R is {report['msa']['pct_tolerance']:.2f}% of tolerance with ndc={report['msa']['ndc']}; classification {msa_acceptance} ({gage_wording}).

## DMAIC route

### Define

The project problem is low and variable EOL gripping force in the synthetic Before condition. The customer-facing demonstration requirement is {lsl_n:g}–{usl_n:g} N inclusive around a {target_n:g} N target.

### Measure

The dataset contains independent cohorts of 200 Before and 200 After units plus a balanced 10-part × 3-appraiser × 2-replicate MSA. All identities, timestamps and measurements are synthetic. Capability uses the standard 6-sigma definition; MR-based Cp/Cpk remain provisional until stability is accepted. Control limits shown are Phase I retrospective trial limits; Phase II prospective limits require a demonstrated in-control Phase I.

### Analyze — root-cause evidence

The root-cause route combines: (1) generator response coefficients, (2) observed Before/After factor means and SDs, (3) a five-factor OLS model on the Before sample, and (4) decomposition of the modeled mean shift. The Before regression R² is {diagnostics['r_squared']:.3f}. The five recorded factors explain {modeled_shift:.4f} N of the {observed_shift:.4f} N observed mean shift; the remainder reflects the unchanged random residual and measurement terms in this realization.

| Rank | Factor | Category | Modeled mean-shift contribution (N) | SD reduction | Before standardized beta |
|---:|---|---|---:|---:|---:|
{root_table}

The primary modeled centering drivers are {top[0]['factor_label']}, {top[1]['factor_label']} and {top[2]['factor_label']}. This is not the same as the baseline-variation ranking: motor current has the largest absolute Before standardized beta ({max(modeled, key=lambda row: abs(row['before_standardized_beta']))['before_standardized_beta']:.3f}) and is the dominant recorded driver of Before force variation in the fitted model. Pad thickness contributes little to centering in this realization but its spread is reduced. These relationships hold only inside the declared synthetic model; real root-cause confirmation requires physical measurement, stratification and DOE or controlled trials.

The remaining candidate causes — {assessed_categories} — were assessed but have no encoded effect in the synthetic response model, so no synthetic evidence supports or refutes them; each requires real data before any causal claim.

### Improve

IMP-EG-01 encodes closed-loop motor-current control, alignment poka-yoke, backlash and pad incoming inspection, and program-controlled torque. The hidden part residual remains {residual_sd_n:g} N in both stages, so it is not presented as an improvement lever.

### Control

| Control item | Frequency | Approved action limit | Current status | Owner role |
|---|---|---|---|---|
{control_table}

Detailed methods, limit bases, reaction plans and records are provided in `control_plan.csv`. Statistical windows derived from the After sample are provisional and must not be presented as engineering tolerances.

## Release decision

The synthetic improvement scenario is suitable for portfolio demonstration, but the Control phase remains open. Required next evidence is: resolve the Phase I MR alarms and establish Phase II control limits, establish real engineering input tolerances, improve or justify the {msa_acceptance} MSA result, and then repeat capability analysis on a stable real process.
"""


def make_imr(stage_frame, stage_name, color, metrics, config, output_path, version):
    values = stage_frame["measured_force_n"].to_numpy(float)
    moving_range = np.abs(np.diff(values))
    indices = np.arange(1, len(values) + 1)
    fig, axes = plt.subplots(2, 1, figsize=(12, 7.4), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    fig.suptitle(f"{stage_name} I–MR Stability Screen", fontsize=15, fontweight="bold", color=TEXT_COLOR)

    axes[0].plot(indices, values, color=color, linewidth=1.0, marker="o", markersize=2.8)
    axes[0].axhline(np.mean(values), color=TEXT_COLOR, linewidth=1.2, label="Mean")
    axes[0].axhline(metrics["control_screen"]["i_lcl_n"], color=SPEC_COLOR, linestyle="--", label="I-chart limits")
    axes[0].axhline(metrics["control_screen"]["i_ucl_n"], color=SPEC_COLOR, linestyle="--")
    axes[0].set_ylabel("Gripping force (N)")
    axes[0].grid(axis="y")
    axes[0].legend(loc="upper right", ncol=2, frameon=True, framealpha=0.92, facecolor="white")
    for record_id in metrics["control_screen"]["i_flags"]:
        row = stage_frame.loc[stage_frame["record_id"] == record_id].iloc[0]
        axes[0].scatter(row["sample_index"], row["measured_force_n"], s=50, color=SPEC_COLOR, zorder=4)

    axes[1].plot(indices[1:], moving_range, color=color, linewidth=1.0, marker="o", markersize=2.8)
    axes[1].axhline(np.mean(moving_range), color=TEXT_COLOR, linewidth=1.2, label="Mean MR")
    axes[1].axhline(metrics["control_screen"]["mr_ucl_n"], color=SPEC_COLOR, linestyle="--", label="MR UCL")
    axes[1].set_xlabel("Chronological sample index")
    axes[1].set_ylabel("Moving range (N)")
    axes[1].grid(axis="y")
    axes[1].legend(loc="upper right", ncol=2, frameon=True, framealpha=0.92, facecolor="white")
    flagged = set(metrics["control_screen"]["mr_flags"])
    for index, row in stage_frame.iloc[1:].iterrows():
        if row["record_id"] in flagged:
            sample_index = int(row["sample_index"])
            axes[1].scatter(sample_index, moving_range[sample_index - 2], s=50, color=SPEC_COLOR, zorder=4)
            axes[1].annotate(row["record_id"], (sample_index, moving_range[sample_index - 2]), xytext=(4, 5), textcoords="offset points", fontsize=8)
    fig.text(0.01, 0.012, "Point rule only; capability remains provisional when instability signals are unresolved.", fontsize=8, color="#64748B")
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    save_figure(fig, output_path, version, config["data_label"])


def load_inputs(input_dir):
    combined = pd.read_csv(input_dir / "quality_before_after.csv", encoding="utf-8-sig")
    msa = pd.read_csv(input_dir / "quality_msa.csv", encoding="utf-8-sig")
    config = json.loads((input_dir / "generation_config.json").read_text(encoding="utf-8"))
    report = json.loads((input_dir / "validation_report.json").read_text(encoding="utf-8"))
    config_validation = validate_config(config)
    expected_total = report["expected_counts_from_config"]["before_after_total"]
    expected_msa = report["expected_counts_from_config"]["msa"]
    csv_names = [
        "quality_baseline.csv",
        "quality_before_after.csv",
        "quality_msa.csv",
        "six_sigma_data_dictionary.csv",
    ]
    csv_hashes = {name: sha256_file(input_dir / name) for name in csv_names}
    source_hashes = {
        "generation_config.json": sha256_file(input_dir / "generation_config.json"),
        "generate_quality_data.py": sha256_file(input_dir / "generate_quality_data.py"),
    }
    before = combined.loc[combined["process_stage"] == "Before Improvement"].copy()
    after = combined.loc[combined["process_stage"] == "After Improvement"].copy()
    before_metrics = capability(before.to_dict(orient="records"), config)
    after_metrics = capability(after.to_dict(orient="records"), config)
    msa_metrics = gage_rr(msa.to_dict(orient="records"), config)
    target = config["specification"]["target_n"]
    improvement = {
        "mean_shift_toward_target_n": abs(before_metrics["mean_n"] - target) - abs(after_metrics["mean_n"] - target),
        "overall_sd_reduction_pct": 100 * (1 - after_metrics["overall_sd_n"] / before_metrics["overall_sd_n"]),
        "defect_rate_reduction_percentage_points": 100 * (before_metrics["defect_rate"] - after_metrics["defect_rate"]),
        "Ppk_change": after_metrics["Ppk_descriptive"] - before_metrics["Ppk_descriptive"],
        "interpretation": "Synthetic scenario comparison only; not evidence that real interventions caused these effects.",
    }
    lower = config["specification"]["lsl_n"]
    upper = config["specification"]["usl_n"]
    digits = config["measurement"]["force_record_digits"]
    expected_defect = ~combined["measured_force_n"].between(lower, upper, inclusive="both")
    outcomes_consistent = bool(
        (combined["target_n"] == target).all()
        and (combined["lsl_n"] == lower).all()
        and (combined["usl_n"] == upper).all()
        and (combined["defect_flag"].astype(bool) == expected_defect).all()
        and (combined["spec_status"] == np.where(expected_defect, "Out of Specification", "Within Specification")).all()
        and (combined["defect_type"] == np.where(combined["measured_force_n"] < lower, "Under Force", np.where(combined["measured_force_n"] > upper, "Over Force", "No Defect"))).all()
        and np.isclose(combined["deviation_from_target_n"], (combined["measured_force_n"] - target).round(digits), atol=10 ** (-(digits + 1))).all()
    )
    checks = {
        "validated_release": report["release"]["status"] == "CURRENT" and report["configuration_validation"]["status"] == "PASS" and report["structural_status"] == "PASS",
        "configuration_revalidated": equivalent(config_validation, report["configuration_validation"]),
        "csv_hashes_verified": csv_hashes == report.get("sha256"),
        "source_hashes_verified": source_hashes == report.get("source_sha256"),
        "row_counts": len(combined) == expected_total and len(msa) == expected_msa,
        "synthetic_label": set(combined["data_label"]) == {config["data_label"]} and set(msa["data_label"]) == {config["data_label"]},
        "version_match": set(combined["generation_model_version"]) == {config["version"]} and set(msa["generation_model_version"]) == {config["version"]},
        "stage_counts": combined.groupby("process_stage").size().to_dict() == {"After Improvement": expected_total // 2, "Before Improvement": expected_total // 2},
        "outcomes_recomputed": outcomes_consistent,
        "capability_recomputed": equivalent(before_metrics, report["before"]) and equivalent(after_metrics, report["after"]),
        "msa_recomputed": equivalent(msa_metrics, report["msa"]),
        "improvement_recomputed": equivalent(improvement, report["improvement_comparison"]),
    }
    if not all(checks.values()):
        raise ValueError(f"Chart input validation failed: {checks}")
    verified_report = dict(report)
    verified_report.update(before=before_metrics, after=after_metrics, msa=msa_metrics, improvement_comparison=improvement)
    source_hashes.update({name: csv_hashes[name] for name in csv_names})
    source_hashes["validation_report.json"] = sha256_file(input_dir / "validation_report.json")
    source_hashes["analyze_quality_data.py"] = sha256_file(Path(__file__))
    return combined, msa, config, verified_report, checks, source_hashes


def _build_charts(input_dir, output_dir, artifact_dir):
    combined, msa, config, report, input_checks, source_hashes = load_inputs(input_dir)
    generalization_checks = interpretation_branch_checks(config, report)
    if not all(generalization_checks.values()):
        failed = [name for name, passed in generalization_checks.items() if not passed]
        raise RuntimeError(f"Chart interpretation branch checks failed: {failed}")
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_style()
    version = config["version"]
    data_label = config["data_label"]
    before = combined.loc[combined["process_stage"] == "Before Improvement"].copy()
    after = combined.loc[combined["process_stage"] == "After Improvement"].copy()
    root_causes, diagnostics = build_root_cause_rows(before, after, config)
    control_plan = build_control_plan_rows(after, config, report)
    invalid_statuses = [row["control_item"] for row in control_plan if row["current_status"] not in CONTROL_STATUSES]
    if invalid_statuses:
        raise RuntimeError(f"Control plan produced non-enumerated statuses: {invalid_statuses}")
    lsl = float(combined["lsl_n"].iloc[0])
    target = float(combined["target_n"].iloc[0])
    usl = float(combined["usl_n"].iloc[0])
    ppk_ref = config["analysis"]["ppk_reference_min"]
    residual_sd_n = config["stages"]["before"]["part_residual_sd_n"]
    chart_rows = []

    def record(filename, title, source, interpretation):
        chart_rows.append(
            {
                "chart_file": filename,
                "chart_title": title,
                "source_data": source,
                "interpretation": interpretation,
                "generation_model_version": version,
                "data_label": config["data_label"],
            }
        )

    filename = "01_force_run_chart.png"
    fig, axes = plt.subplots(2, 1, figsize=(12, 7.2), sharex=True, sharey=True)
    fig.suptitle("Gripping Force in Production Sequence", fontsize=15, fontweight="bold", color=TEXT_COLOR)
    for axis, frame, label, color in zip(axes, (before, after), ("Before Improvement", "After Improvement"), (BEFORE_COLOR, AFTER_COLOR)):
        axis.plot(frame["sample_index"], frame["measured_force_n"], color=color, linewidth=1.0, marker="o", markersize=2.5)
        add_spec_lines(axis, lsl, target, usl, horizontal=True, labels=axis is axes[0])
        axis.set_title(label, loc="left", fontsize=11)
        axis.set_ylabel("Force (N)")
        axis.grid(axis="y")
    axes[0].legend(loc="upper right", ncol=3)
    axes[1].set_xlabel("Chronological sample index")
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    save_figure(fig, output_dir / filename, version, data_label)
    record(filename, "Gripping Force in Production Sequence", "quality_before_after.csv", f"After is centered nearer {target:g} N; After MR alarms: {', '.join(report['after']['control_screen']['mr_flags']) or 'none'}.")

    filename = "02_force_distribution.png"
    fig, axis = plt.subplots(figsize=(10.5, 6.2))
    bin_edges = np.linspace(min(before["measured_force_n"].min(), after["measured_force_n"].min()) - 0.15, max(before["measured_force_n"].max(), after["measured_force_n"].max()) + 0.15, 28)
    axis.hist(before["measured_force_n"], bins=bin_edges, density=True, histtype="step", linewidth=2.0, color=BEFORE_COLOR, label="Before")
    axis.hist(after["measured_force_n"], bins=bin_edges, density=True, histtype="step", linewidth=2.0, color=AFTER_COLOR, label="After")
    add_spec_lines(axis, lsl, target, usl, labels=True)
    axis.set_title("After Distribution Narrows Around the Target")
    axis.set_xlabel("Measured gripping force (N)")
    axis.set_ylabel("Density")
    axis.grid(axis="y")
    axis.legend(ncol=5, loc="upper right")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    save_figure(fig, output_dir / filename, version, data_label)
    record(filename, "After Distribution Narrows Around the Target", "quality_before_after.csv", f"Observed SD falls from {report['before']['overall_sd_n']:.3f} N to {report['after']['overall_sd_n']:.3f} N with unchanged hidden residual SD.")

    filename = "03_force_boxplot.png"
    fig, axis = plt.subplots(figsize=(10.5, 4.8))
    box = axis.boxplot([before["measured_force_n"], after["measured_force_n"]], vert=False, tick_labels=["Before", "After"], patch_artist=True, widths=0.55, medianprops={"color": "#111827", "linewidth": 1.5})
    for patch, color in zip(box["boxes"], (BEFORE_COLOR, AFTER_COLOR)):
        patch.set_facecolor(color)
        patch.set_alpha(0.65)
    add_spec_lines(axis, lsl, target, usl, labels=True)
    axis.set_title("Force Spread and Outliers by Improvement Stage")
    axis.set_xlabel("Measured gripping force (N)")
    axis.grid(axis="x")
    axis.legend(ncol=3, loc="upper right")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    save_figure(fig, output_dir / filename, version, data_label)
    record(filename, "Force Spread and Outliers by Improvement Stage", "quality_before_after.csv", f"Before has {report['before']['defects']} out-of-spec observation(s); After has {report['after']['defects']} in this 200-piece sample.")

    make_imr(before, "Before Improvement", BEFORE_COLOR, report["before"], config, output_dir / "04_imr_before.png", version)
    record("04_imr_before.png", "Before Improvement I–MR Stability Screen", "quality_before_after.csv + validation_report.json", f"MR point-rule alarms: {', '.join(report['before']['control_screen']['mr_flags']) or 'none'}.")
    make_imr(after, "After Improvement", AFTER_COLOR, report["after"], config, output_dir / "05_imr_after.png", version)
    record("05_imr_after.png", "After Improvement I–MR Stability Screen", "quality_before_after.csv + validation_report.json", f"MR point-rule alarms: {', '.join(report['after']['control_screen']['mr_flags']) or 'none'}; do not claim a stable process yet.")

    filename = "06_capability_comparison.png"
    fig, axis = plt.subplots(figsize=(10.5, 6.0))
    metrics = ["Pp_descriptive", "Ppk_descriptive", "Cp_MR_provisional", "Cpk_MR_provisional"]
    labels = ["Pp", "Ppk", "Cp (MR)", "Cpk (MR)"]
    x = np.arange(len(metrics))
    width = 0.34
    before_values = [report["before"][metric] for metric in metrics]
    after_values = [report["after"][metric] for metric in metrics]
    bars_before = axis.bar(x - width / 2, before_values, width, color=BEFORE_COLOR, label="Before")
    bars_after = axis.bar(x + width / 2, after_values, width, color=AFTER_COLOR, label="After")
    axis.axhline(1.0, color="#64748B", linestyle=":", linewidth=1.2, label="Index = 1.00")
    axis.axhline(ppk_ref, color=TARGET_COLOR, linestyle="--", linewidth=1.2, label=f"Reference = {ppk_ref:g}")
    axis.set_xticks(x, labels)
    axis.set_ylim(0, max(1.55, max(after_values) + 0.2))
    axis.set_ylabel("Capability index")
    axis.set_title("Capability Improves, but MR-Based Cp/Cpk Remain Provisional")
    axis.grid(axis="y")
    axis.legend(ncol=4, loc="upper left")
    axis.bar_label(bars_before, fmt="%.2f", padding=3, fontsize=9)
    axis.bar_label(bars_after, fmt="%.2f", padding=3, fontsize=9)
    fig.text(0.01, 0.035, "Standard formula: Pp/Cp use 6σ; Ppk/Cpk use one-sided 3σ. Control-limit settings do not enter these formulas.", fontsize=8, color="#64748B")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    save_figure(fig, output_dir / filename, version, data_label)
    record(filename, "Capability Improves, but MR-Based Cp/Cpk Remain Provisional", "validation_report.json", f"Ppk changes from {report['before']['Ppk_descriptive']:.3f} to {report['after']['Ppk_descriptive']:.3f} under the standard 6-sigma definition.")

    filename = "07_process_factor_distributions.png"
    factors = [
        ("motor_current_a", "Motor current (A)"),
        ("jaw_alignment_error_mm", "Alignment error (mm)"),
        ("gear_backlash_deg", "Gear backlash (degree)"),
        ("pad_thickness_mm", "Pad thickness (mm)"),
        ("fastener_torque_nm", "Fastener torque (N·m)"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(13, 7.2))
    axes = axes.flatten()
    for axis, (field, label) in zip(axes, factors):
        low = min(before[field].min(), after[field].min())
        high = max(before[field].max(), after[field].max())
        bins = np.linspace(low, high, 20)
        axis.hist(before[field], bins=bins, density=True, histtype="step", linewidth=1.7, color=BEFORE_COLOR, label="Before")
        axis.hist(after[field], bins=bins, density=True, histtype="step", linewidth=1.7, color=AFTER_COLOR, label="After")
        axis.set_title(label, fontsize=10)
        axis.set_ylabel("Density")
        axis.grid(axis="y")
    axes[0].legend(loc="upper right")
    axes[-1].axis("off")
    fig.suptitle("Observable Process Factors Encode the After Improvement", fontsize=15, fontweight="bold", color=TEXT_COLOR)
    fig.text(0.01, 0.035, f"The latent part-residual SD is held at {residual_sd_n:g} N in both stages; it is not presented as an improvement lever.", fontsize=8, color="#64748B")
    fig.tight_layout(rect=(0, 0.06, 1, 0.95))
    save_figure(fig, output_dir / filename, version, data_label)
    record(filename, "Observable Process Factors Encode the After Improvement", "quality_before_after.csv + generation_config.json", "Reduced variation is tied to recorded current, alignment, backlash, pad thickness and torque factors; hidden residual SD is unchanged.")

    filename = "08_msa_variance_components.png"
    components = report["msa"]["variance_components_n2"]
    component_labels = ["Part-to-part", "Appraiser", "Part × appraiser", "Repeatability"]
    component_values = [components["part"], components["appraiser"], components["part_appraiser_interaction"], components["repeatability"]]
    total = sum(component_values)
    contributions = [100 * value / total for value in component_values]
    fig, axis = plt.subplots(figsize=(10.5, 5.8))
    colors = ["#475569", "#7C3AED", "#A855F7", "#DB2777"]
    bars = axis.barh(component_labels[::-1], contributions[::-1], color=colors[::-1])
    axis.set_xlabel("Contribution to total observed variance (%)")
    axis.set_title("MSA Variance Is Dominated by Part-to-Part Differences")
    axis.grid(axis="x")
    axis.bar_label(bars, fmt="%.2f%%", padding=4, fontsize=9)
    fig.text(0.01, 0.04, f"Gage R&R: {report['msa']['pct_tolerance']:.2f}% of tolerance; {report['msa']['pct_study_variation']:.2f}% of study variation; ndc = {report['msa']['ndc']}.", fontsize=8, color="#64748B")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    save_figure(fig, output_dir / filename, version, data_label)
    record(filename, "MSA Variance Is Dominated by Part-to-Part Differences", "quality_msa.csv + validation_report.json", figure08_interpretation(report))

    filename = "09_msa_part_appraiser.png"
    reference_by_part = msa.groupby("part_id")["reference_force_n"].first().sort_values()
    part_order = list(reference_by_part.index)
    short_labels = [f"P{index + 1}" for index in range(len(part_order))]
    means = msa.groupby(["part_id", "appraiser_id"])["measured_force_n"].mean()
    fig, axis = plt.subplots(figsize=(11.5, 6.2))
    palette = ["#2563EB", "#16A34A", "#7C3AED", "#DB2777"]
    for color, appraiser in zip(palette, sorted(msa["appraiser_id"].unique())):
        axis.plot(short_labels, [means.loc[part, appraiser] for part in part_order], marker="o", linewidth=1.5, color=color, label=appraiser)
    axis.plot(short_labels, reference_by_part.values, color=TEXT_COLOR, linestyle="--", linewidth=1.3, label="Synthetic latent reference")
    axis.set_xlabel("MSA part ordered by latent reference")
    axis.set_ylabel("Mean measured force (N)")
    axis.set_title("Appraiser Profiles Across the Crossed MSA Parts")
    axis.grid(axis="y")
    axis.legend(ncol=4, loc="upper left")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    save_figure(fig, output_dir / filename, version, data_label)
    record(filename, "Appraiser Profiles Across the Crossed MSA Parts", "quality_msa.csv", "Parallel appraiser profiles indicate small synthetic appraiser effects relative to part-to-part spread; the latent reference is not a real calibration standard.")

    filename = "10_improvement_summary.png"
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.8))
    fig.suptitle("V5 Improvement Summary", fontsize=15, fontweight="bold", color=TEXT_COLOR)
    summary_specs = [
        ("Distance from target", [abs(report["before"]["mean_n"] - target), abs(report["after"]["mean_n"] - target)], "N", "Lower is better"),
        ("Overall sample SD", [report["before"]["overall_sd_n"], report["after"]["overall_sd_n"]], "N", "Lower is better"),
        ("Observed defect rate", [100 * report["before"]["defect_rate"], 100 * report["after"]["defect_rate"]], "%", "Sample result only"),
    ]
    for axis, (title, values, unit, note) in zip(axes, summary_specs):
        bars = axis.bar(["Before", "After"], values, color=[BEFORE_COLOR, AFTER_COLOR], width=0.58)
        axis.set_title(title, fontsize=11)
        axis.set_ylabel(unit)
        axis.grid(axis="y")
        axis.bar_label(bars, labels=[f"{value:.3f}" if unit == "N" else f"{value:.1f}%" for value in values], padding=4, fontsize=9)
        axis.text(0.5, -0.16, note, transform=axis.transAxes, ha="center", fontsize=8, color="#64748B")
        axis.set_ylim(0, max(values) * 1.28 if max(values) > 0 else 1)
    fig.text(0.01, 0.035, f"Causal claim boundary: improvements are encoded in observable synthetic factors; hidden residual SD is unchanged at {residual_sd_n:g} N.", fontsize=8, color="#64748B")
    fig.tight_layout(rect=(0, 0.08, 1, 0.93))
    save_figure(fig, output_dir / filename, version, data_label)
    record(filename, "V5 Improvement Summary", "validation_report.json", f"Mean moves {report['improvement_comparison']['mean_shift_toward_target_n']:.3f} N toward target and observed SD falls {report['improvement_comparison']['overall_sd_reduction_pct']:.1f}% in the synthetic scenario.")

    filename = "11_root_cause_contribution.png"
    modeled_causes = [row for row in root_causes if row["evidence_status"] == "SCENARIO_ENCODED_RELATIONSHIP"]
    ordered_causes = sorted(modeled_causes, key=lambda row: row["modeled_mean_shift_contribution_n"])
    fig, axis = plt.subplots(figsize=(10.8, 6.1))
    values = [row["modeled_mean_shift_contribution_n"] for row in ordered_causes]
    labels = [row["factor_label"] for row in ordered_causes]
    colors = [AFTER_COLOR if value >= 0 else SPEC_COLOR for value in values]
    bars = axis.barh(labels, values, color=colors)
    axis.axvline(0, color=TEXT_COLOR, linewidth=1.0)
    axis.set_xlabel("Modeled contribution to After − Before mean force (N)")
    axis.set_title("Alignment and Backlash Explain Most of the Modeled Mean Shift")
    axis.grid(axis="x")
    axis.bar_label(bars, labels=[f"{value:+.4f} N" for value in values], padding=4, fontsize=9)
    fig.text(0.01, 0.035, f"Five-factor modeled shift = {sum(values):.4f} N; observed shift = {report['after']['mean_n'] - report['before']['mean_n']:.4f} N. Synthetic model evidence only.", fontsize=8, color="#64748B")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    save_figure(fig, output_dir / filename, version, data_label)
    record(filename, "Alignment and Backlash Explain Most of the Modeled Mean Shift", "root_cause_analysis.csv + generation_config.json", "Signed contributions decompose the response-model shift; they do not establish real-world physical causation.")

    filename = "12_control_plan_readiness.png"
    status_by_item = {row["control_item"]: row["current_status"] for row in control_plan}
    readiness = [
        ("After sample conformity", status_by_item["Gripping force CTQ"], f"{report['after']['defects']} / {report['after']['n']} OOS"),
        ("I-MR stability", status_by_item["I-MR stability"], f"{len(report['after']['control_screen']['mr_flags']) + len(report['after']['control_screen']['i_flags'])} point-rule alarms"),
        ("Ppk reference", status_by_item["Process capability"], f"{report['after']['Ppk_descriptive']:.3f} vs {ppk_ref:g}"),
        ("Gage R&R", status_by_item["Gage R&R"], f"{report['msa']['pct_tolerance']:.2f}% tolerance; ndc {report['msa']['ndc']}"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 6.2))
    fig.suptitle("Control Phase Is Not Yet Closed", fontsize=15, fontweight="bold", color=TEXT_COLOR)
    for axis, (title, status, detail) in zip(axes.flatten(), readiness):
        axis.set_facecolor(STATUS_COLORS[status])
        axis.text(0.5, 0.68, title, ha="center", va="center", fontsize=12, fontweight="bold", color=TEXT_COLOR)
        axis.text(0.5, 0.43, STATUS_DISPLAY[status], ha="center", va="center", fontsize=18, fontweight="bold", color=STATUS_TEXT_COLORS[status])
        axis.text(0.5, 0.20, detail, ha="center", va="center", fontsize=10, color=TEXT_COLOR)
        axis.set_xticks([])
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_color("#CBD5E1")
    fig.text(0.01, 0.025, "Sample conformity alone does not close Control: stability, capability and measurement-system gates remain open.", fontsize=8, color="#64748B")
    fig.tight_layout(rect=(0, 0.06, 1, 0.93), h_pad=1.4, w_pad=1.4)
    save_figure(fig, output_dir / filename, version, data_label)
    record(filename, "Control Phase Is Not Yet Closed", "control_plan.csv + validation_report.json", figure12_interpretation(report, ppk_ref))

    generalization_checks.update(manifest_interpretation_checks(chart_rows, report, ppk_ref))
    if not all(generalization_checks.values()):
        failed = [name for name, passed in generalization_checks.items() if not passed]
        raise RuntimeError(f"Chart manifest row checks failed: {failed}")

    root_cause_path = artifact_dir / "root_cause_analysis.csv"
    control_plan_path = artifact_dir / "control_plan.csv"
    report_path = artifact_dir / "six_sigma_analysis_report.md"
    write_csv(root_cause_path, root_causes)
    write_csv(control_plan_path, control_plan)
    report_path.write_text(
        build_analysis_report(root_causes, control_plan, diagnostics, report, config),
        encoding="utf-8",
        newline="\n",
    )

    manifest_path = artifact_dir / "chart_manifest.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(chart_rows[0]))
        writer.writeheader()
        writer.writerows(chart_rows)
    generalization_checks.update(manifest_file_checks(manifest_path, chart_rows, report, ppk_ref))
    if not all(generalization_checks.values()):
        failed = [name for name, passed in generalization_checks.items() if not passed]
        raise RuntimeError(f"Staged chart manifest checks failed: {failed}")

    generated = [output_dir / row["chart_file"] for row in chart_rows]
    generated_artifacts = [root_cause_path, control_plan_path, report_path, manifest_path]
    analysis_validation = {
        "release": {"version": version, "status": "CURRENT", "v3_status": "RETIRED", "v4_status": "SUPERSEDED", "data_label": config["data_label"]},
        "input_checks": input_checks,
        "chart_count": len(generated),
        "all_chart_files_exist": all(path.is_file() and path.stat().st_size > 0 for path in generated),
        "chart_manifest": manifest_path.name,
        "root_cause_analysis": {
            "row_count": len(root_causes),
            "before_ols_r_squared": diagnostics["r_squared"],
            "modeled_mean_shift_n": sum(row["modeled_mean_shift_contribution_n"] for row in root_causes if row["evidence_status"] == "SCENARIO_ENCODED_RELATIONSHIP"),
            "observed_mean_shift_n": report["after"]["mean_n"] - report["before"]["mean_n"],
            "causal_claim_scope": "SCENARIO_ENCODED_RELATIONSHIP",
        },
        "control_plan": {
            "row_count": len(control_plan),
            "all_rows_have_reaction_plan": all(row["reaction_plan"] for row in control_plan),
            "all_rows_have_owner_and_record": all(row["owner_role"] and row["record"] for row in control_plan),
            "all_statuses_in_enum": all(row["current_status"] in CONTROL_STATUSES for row in control_plan),
            "open_statuses": [row["control_item"] for row in control_plan if row["current_status"] in OPEN_CONTROL_STATUSES],
        },
        "generalization_checks": generalization_checks,
        "artifact_sha256": {path.name: sha256_file(path) for path in generated_artifacts},
        "source_sha256": source_hashes,
        "metrics_source": "Independently recomputed from verified CSV inputs; validation_report.json used only as a comparison contract.",
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "matplotlib": matplotlib.__version__,
        },
        "chart_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in generated},
        "chart_hash_scope": "Environment-specific; PNG bytes are not guaranteed reproducible across Python/NumPy/Matplotlib versions. Semantic verification is via chart_manifest.csv.",
    }
    (artifact_dir / "analysis_validation.json").write_text(json.dumps(analysis_validation, indent=2) + "\n", encoding="utf-8", newline="\n")
    return analysis_validation


def remove_path(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def commit_analysis_transaction(stage_root, input_dir, output_dir):
    """Commit charts, analysis tables, report and audit JSON together with rollback."""
    targets = {
        stage_root / "charts": output_dir,
        stage_root / "chart_manifest.csv": input_dir / "chart_manifest.csv",
        stage_root / "root_cause_analysis.csv": input_dir / "root_cause_analysis.csv",
        stage_root / "control_plan.csv": input_dir / "control_plan.csv",
        stage_root / "six_sigma_analysis_report.md": input_dir / "six_sigma_analysis_report.md",
        stage_root / "analysis_validation.json": input_dir / "analysis_validation.json",
    }
    backup_root = Path(tempfile.mkdtemp(prefix=".analysis-backup-", dir=input_dir))
    backups = {}
    committed = []
    try:
        for index, target in enumerate(targets.values()):
            if target.exists():
                backup = backup_root / f"{index}-{target.name}"
                os.replace(target, backup)
                backups[target] = backup
        for staged, target in targets.items():
            os.replace(staged, target)
            committed.append(target)
    except Exception:
        for target in reversed(committed):
            remove_path(target)
        for target, backup in backups.items():
            if backup.exists():
                os.replace(backup, target)
        raise
    finally:
        shutil.rmtree(backup_root, ignore_errors=True)


def build_charts(input_dir, output_dir):
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    if output_dir.parent != input_dir:
        raise ValueError("Transactional chart output must be a direct child of the input directory")
    stage_root = Path(tempfile.mkdtemp(prefix=".analysis-stage-", dir=input_dir))
    try:
        staged_charts = stage_root / "charts"
        staged_charts.mkdir()
        result = _build_charts(input_dir, staged_charts, stage_root)
        if not result["all_chart_files_exist"] or result["chart_count"] != 12:
            raise RuntimeError("Analysis validation failed before commit")
        commit_analysis_transaction(stage_root, input_dir, output_dir)
        return result
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or args.input / "charts"
    result = build_charts(args.input, output)
    print(json.dumps(result, indent=2))
    if not result["all_chart_files_exist"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
