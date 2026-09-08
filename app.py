import streamlit as st
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

from services.work_order_service import (
    create_work_order,
    release_work_order,
    list_work_orders,
    get_units,
    list_products,
)
from services.production_service import (
    list_active_work_orders,
    list_units_for_order,
    get_unit_progress,
    start_operation,
    complete_operation,
)
from services.quality_service import (
    CHECK_ITEMS,
    submit_inspection,
    list_quality_records,
    list_defects,
    start_rework,
    close_rework,
    list_inspection_work_orders,
)
from services.traceability_service import list_all_units, get_unit_traceability
from services.dashboard_service import (
    get_mes_kpis,
    get_scenario_comparison,
    validate_simulation_data,
)
from services.six_sigma_service import SixSigmaDataError, load_six_sigma_results
from services.anylogic_service import (
    AnyLogicDataError,
    get_process_routing,
    get_resource_capacity,
    SCENARIO_IMAGES,
    SOURCE_ALP,
)

st.set_page_config(
    page_title="Robotic Arm Digital Manufacturing Portfolio",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_DIR = Path(__file__).resolve().parent
SOLIDWORKS_ASSET_DIR = APP_DIR / "assets" / "solidworks"


# ---------------------------------------------------------------------------
# Clean / minimal theme (light, flat, no default Streamlit chrome)
# ---------------------------------------------------------------------------
_CLEAN_THEME_CSS = """
<style>
/* Hide Streamlit's default chrome for a cleaner interface */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
[data-testid="stDecoration"] {display: none;}
[data-testid="stStatusWidget"] {visibility: hidden;}
[data-testid="stHeaderActionElements"] {display: none;}

/* Typography: neutral system stack with CJK fallbacks */
html, body, [class*="css"], .stApp, .stMarkdown, .stText {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI",
                 "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
                 "Noto Sans SC", sans-serif;
}

.stApp {
    background-color: #FAFBFC;
    color: #1F2937;
}

/* Headings: tighter tracking, lighter weight */
h1, h2, h3, h4, h5, h6 {
    color: #111827;
    letter-spacing: -0.015em;
}
h1 { font-size: 1.85rem; font-weight: 650; }
h2 { font-size: 1.35rem; font-weight: 600; }
h3 { font-size: 1.12rem; font-weight: 600; }
h4 { font-size: 1rem; font-weight: 600; }

/* Sidebar: soft, airy, no hard border */
[data-testid="stSidebar"] {
    background-color: #FAFBFC;
    border-right: none;
}

/* Sidebar heading: quiet small-caps label */
[data-testid="stSidebar"] h3 {
    font-size: 0.78rem;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #9CA3AF;
    margin: 0 0 0.75rem 0;
}

/* Nav buttons: strip to bare text, rely on whitespace */
[data-testid="stSidebar"] button {
    background: transparent !important;
    background-image: none !important;
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    text-align: left !important;
    justify-content: flex-start !important;
    width: 100% !important;
    padding: 0.55rem 0.75rem !important;
    margin: 0.15rem 0 !important;
}

/* Unselected: quiet gray text, invisible left rail */
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] * {
    color: #4B5563 !important;
    font-weight: 400 !important;
}
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] {
    border-right: 2px solid transparent !important;
}

/* Selected: thin light-blue rail + light-blue text, no filled block */
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"],
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] * {
    color: #3E6FD6 !important;
    font-weight: 500 !important;
}
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
    border-right: 2px solid #3E6FD6 !important;
}

/* Hover: whisper of tint, never a filled block */
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover {
    background: #F2F4F7 !important;
}
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"]:hover {
    background: rgba(62, 111, 214, 0.06) !important;
}

/* Buttons: flat, rounded, muted primary */
.stButton > button, .stDownloadButton > button {
    border-radius: 8px;
    border: 1px solid #E5E7EB;
    box-shadow: none;
    font-weight: 500;
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
    border: none;
}

/* Metrics: light card, no heavy shadow */
[data-testid="stMetric"] {
    background-color: #FFFFFF;
    border: 1px solid #EFF1F4;
    border-radius: 10px;
    padding: 0.75rem 1rem;
}

/* Expander: soft edges */
[data-testid="stExpander"] {
    border: 1px solid #EFF1F4;
    border-radius: 10px;
}

/* Remove Streamlit's default drop shadows on blocks */
div[data-testid="stVerticalBlock"] > div { box-shadow: none; }

/* Language selector: light-gray label + muted gray selected value */
[data-testid="stWidgetLabel"] {
    color: #9CA3AF;
}
.stSelectbox input {
    color: #6B7280;
}

/* MES tabs: spread evenly to fill the full width of the underline */
[data-testid="stTabs"] [role="tablist"] {
    display: flex;
    width: 100%;
    justify-content: space-evenly;
}

/* Sidebar subtitle: quiet demo note in the lower half */
.sidebar-subtitle {
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid #EEF0F3;
    font-size: 0.78rem;
    line-height: 1.5;
    color: #9CA3AF;
}
</style>
"""

st.markdown(_CLEAN_THEME_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Language / translation
# ---------------------------------------------------------------------------
TRANSLATIONS = {
    "en": {
        "title": "Robotic Arm Digital Manufacturing Portfolio",
        "subtitle": "From mechanical design to manufacturing execution and quality improvement",
        "language_label": "Language",
        # Top-level sidebar
        "sidebar_navigation": "Project Navigation",
        "section_solidworks": "SolidWorks Modeling",
        "section_anylogic": "AnyLogic Simulation",
        "section_mes_system": "MES System",
        "section_six_sigma": "Six Sigma Analysis",
        "mes_heading": "Manufacturing Execution System",
        "mes_caption": "Work-order, production, quality and traceability workflow backed by persistent PostgreSQL storage.",
        "mes_capability_caption": "The system supports work order creation and visualized production progress.",
        # SolidWorks modeling
        "sw_heading": "SolidWorks Modeling",
        "sw_caption": "Parametric design and assembly verification of an agricultural robotic arm.",
        "sw_platform": "CAD Platform",
        "sw_model": "Model",
        "sw_model_value": "Agricultural Robotic Arm",
        "sw_actuation": "Actuation",
        "sw_actuation_value": "3 × MG996R + 1 × SG90",
        "sw_assembly_render": "Assembly Render",
        "sw_motion_demo": "Motion Demonstration",
        "sw_design_scope": "Design Scope",
        "sw_scope_1": "Parametric part and assembly modeling",
        "sw_scope_2": "Multi-joint arm and gripper mechanism",
        "sw_scope_3": "Assembly fit and motion verification",
        "sw_source_files": "SolidWorks Source Package",
        "sw_source_caption": "Download the complete SLDASM/SLDPRT portfolio package.",
        "sw_download_source": "Download SolidWorks Project",
        "sw_asset_missing": "SolidWorks display asset is missing: {name}",
        # Tabs
        "tab_dashboard": "Dashboard",
        "tab_create_work_order": "Create Work Order",
        "tab_work_order_list": "Work Order List",
        "tab_production_execution": "Production Execution",
        "tab_quality_defects": "Quality & Defects",
        "tab_traceability": "Traceability",
        "tab_six_sigma_analytics": "Six Sigma Analysis",
        # Buttons
        "button_create_work_order": "Create Work Order",
        "button_release": "Release",
        "button_start": "Start",
        "button_complete": "Complete",
        "button_submit_inspection": "Submit Inspection",
        "button_start_rework": "Start Rework",
        "button_close_rework": "Close Rework",
        "button_download_csv": "Download Traceability CSV",
        # Form labels
        "label_product": "Product",
        "label_planned_quantity": "Planned Quantity",
        "label_due_date": "Due Date",
        "label_operator": "Operator",
        "label_work_order": "Work Order",
        "label_serial_number": "Serial Number",
        "label_inspector": "Inspector",
        "label_defect_type": "Defect Type",
        "label_severity": "Severity",
        "label_description": "Description",
        "label_rework_notes": "Rework Notes",
        # Flash messages
        "flash_work_order_created": "Work order {code} created successfully.",
        "flash_create_failed": "Failed to create work order: {e}",
        "flash_released": "Work order {code} released. {count} units generated.",
        "flash_release_failed": "Failed to release work order: {e}",
        "flash_operation_started": "Operation {code} {name} started.",
        "flash_operation_completed": "Operation {code} {name} completed.",
        "flash_inspection_passed": "Operation {code} inspection passed (attempt {attempt}).",
        "flash_inspection_failed": "Operation {code} inspection failed. A defect record was created.",
        "flash_rework_started": "Defect #{id} entered rework.",
        "flash_rework_closed": "Rework closed. The unit is ready for reinspection.",
        # Empty / state hints
        "empty_no_products": "No product data found. Check the database configuration and seed data.",
        "empty_no_work_orders": "No work orders found.",
        "empty_no_units": "No units found for this work order.",
        "empty_no_active_orders": "No active work orders found. Release a work order in the Work Order List first.",
        "empty_no_inspection_orders": "No work orders available for inspection (released / in_progress / completed).",
        "empty_no_defects": "No defect records found.",
        "empty_no_quality": "No inspection records found.",
        "empty_no_units_data": "No unit data found.",
        "empty_no_records": "No records found.",
        "empty_no_production_events": "No production events found.",
        "hint_enter_operator": "Enter an operator before starting or completing an operation.",
        "hint_completed_readonly": "This unit has been completed and is read-only.",
        "hint_no_qc_awaiting": "No quality operation currently awaiting inspection.",
        "hint_resolve_defect": "Resolve the open defect before reinspection.",
        "hint_rework_in_progress": "Rework is in progress. Complete the rework and close the defect before reinspection.",
        "hint_completed_readonly_defect": "Completed and read-only.",
        # Work order list fields
        "wo_product": "Product",
        "wo_status": "Status",
        "wo_planned_quantity": "Planned Quantity",
        "wo_due_date": "Due Date",
        "wo_created": "Created",
        "wo_released": "Released",
        "wo_units": "Units",
        "wo_serial_numbers": "Serial Numbers",
        # Production execution
        "pe_current_unit_status": "Current Unit Status",
        "pe_operation_progress": "Operation Progress",
        "pe_goto_quality": "→ Quality & Defects Tab",
        # Quality
        "q_current_qc": "Current Quality Operation",
        "q_inspection_items": "Inspection Items",
        "q_defect_details": "Defect Details (required for a failed inspection)",
        "q_defect_records": "Defect Records",
        "q_inspection_history": "Inspection History",
        "q_inspection_items_attempt": "Inspection items (attempt {attempt})",
        # Traceability
        "tr_summary": "Summary",
        "tr_unit": "Unit",
        "tr_product": "Product",
        "tr_work_order": "Work Order",
        "tr_operations": "Operations",
        "tr_production_events": "Production Events",
        "tr_quality_history": "Quality History",
        "tr_defect_history": "Defect & Rework History",
        "tr_download": "Download",
        "tr_field_serial_number": "Serial Number",
        "tr_field_status": "Status",
        "tr_field_created": "Created",
        "tr_field_planned_start": "Planned Start",
        "tr_field_planned_end": "Planned End",
        "tr_field_released": "Released",
        "tr_field_operation": "Operation",
        "tr_field_operation_name": "Operation Name",
        "tr_field_sequence": "Sequence",
        "tr_field_worker": "Worker",
        "tr_field_station": "Station",
        "tr_field_base_time": "Base Time (min)",
        "tr_field_attempt": "Attempt",
        "tr_field_event": "Event",
        "tr_field_operator": "Operator",
        "tr_field_timestamp": "Timestamp",
        "tr_field_description": "Description",
        "tr_field_severity": "Severity",
        "tr_field_closed": "Closed",
        "tr_field_rework_notes": "Rework Notes",
        # Dashboard
        "db_mes_live": "MES Live Overview",
        "db_caption_demo": "MES values are based on the current demonstration database.",
        "db_work_orders": "Work Orders",
        "db_total_units": "Total Units",
        "db_completed_units": "Completed Units",
        "db_wip": "WIP",
        "db_completion_rate": "Completion Rate",
        "db_inspection_pass_rate": "Inspection Pass Rate",
        "db_defects": "Defects",
        "db_unit_status_dist": "Unit Status Distribution",
        "db_production_events": "Production Events by Operation",
        "db_scenario": "Scenario",
        "db_arrival_interval": "Arrival Interval",
        "db_assembly_capacity": "Assembly Capacity",
        "db_mean_completed": "Mean Completed",
        "db_mean_wip_col": "Mean WIP",
        "db_mean_throughput_col": "Mean Throughput",
        "db_mean_assembly_util_col": "Mean Assembly Utilization",
        "db_dominant_bottleneck": "Dominant Bottleneck",
        "db_mean_bottleneck_util": "Mean Bottleneck Utilization",
        "db_validation_failed": "Simulation data validation failed: {e}",
        "state_completed": "Completed",
        "state_in_progress": "In Progress",
        "state_ready": "Ready",
        "state_locked": "Locked",
        "state_quality_required": "Quality Required",
        "state_defect_open": "Defect Open",
        "state_rework": "Rework",
        "conclusion_bottleneck": "The primary bottleneck shifted from {frm} to {to}.",
        # Six Sigma & Analytics
        "ss_release": "Validated V5 Release",
        "ss_synthetic_notice": "Synthetic Data — portfolio demonstration only. These results are not measured production performance or verified physical causation.",
        "ss_validation_ok": "EOL-EG-V5 source hashes, release metadata, row counts and independently recomputed headline metrics passed validation.",
        "ss_validation_failed": "Six Sigma V5 validation failed: {e}",
        "ss_version": "Version",
        "ss_release_status": "Release Status",
        "ss_ctq": "CTQ",
        "ss_ctq_gripping_force": "Gripping Force",
        "ss_specification": "Specification",
        "ss_target": "Target",
        "ss_process_comparison": "Before / After Capability Comparison",
        "ss_stage": "Stage",
        "ss_before": "Before Improvement",
        "ss_after": "After Improvement",
        "ss_sample_size": "Sample Size",
        "ss_mean_force": "Mean Force (N)",
        "ss_standard_deviation": "Sample SD (N)",
        "ss_defects": "Observed Defects",
        "ss_defect_rate": "Defect Rate",
        "ss_pp": "Pp",
        "ss_ppk": "Ppk",
        "ss_sd_reduction": "SD Reduction",
        "ss_ppk_change": "Ppk Change",
        "ss_centering_gain": "Centering Gain",
        "ss_capability_stability": "Capability & Stability Decision",
        "ss_ppk_reference": "Ppk Reference",
        "ss_ppk_below": "After Ppk {ppk} remains below the {reference} reference.",
        "ss_ppk_meets": "After Ppk {ppk} meets the {reference} reference.",
        "ss_phase_i": "Phase I Status",
        "ss_phase_i_not_control": "Not In Control",
        "ss_phase_ii": "Phase II Limits",
        "ss_phase_ii_not_established": "Not Established",
        "ss_mr_alarms": "After MR Alarms",
        "ss_msa": "Measurement System Analysis",
        "ss_grr_tolerance": "Gage R&R (% Tolerance)",
        "ss_ndc": "Number of Distinct Categories",
        "ss_acceptance": "Acceptance",
        "ss_msa_note": "The measurement system is conditional rather than unconditionally accepted; improvement or documented justification remains required.",
        "ss_root_causes": "Modeled Root-Cause Priorities",
        "ss_rank": "Rank",
        "ss_factor": "Factor",
        "ss_category": "Category",
        "ss_contribution": "Modeled Mean-Shift Contribution (N)",
        "ss_factor_sd_reduction": "Factor SD Reduction",
        "ss_control_action": "Control Action",
        "ss_current_status": "Current Status",
        "ss_root_cause_note": "Relationships are confirmed only inside the declared synthetic model; real causal confirmation requires physical measurements and DOE or controlled trials.",
        "ss_control_readiness": "Control Plan Readiness",
        "ss_control_item": "Control Item",
        "ss_frequency": "Frequency",
        "ss_owner": "Owner",
        "ss_control_items": "Control Items",
        "ss_open_items": "Open Items",
        "ss_control_note": "The Control phase remains OPEN until MR alarms, the Ppk reference gap and the conditional MSA disposition are resolved.",
        "ss_charts": "Validated V5 Charts",
        "ss_chart_note": "Chart annotations remain in the validated V5 source language (English).",
        "ss_data_preview": "V5 Data Preview",
        "ss_downloads": "Source Downloads",
        "ss_download_report": "Download Analysis Report",
        "ss_download_raw": "Download Before/After CSV",
        "ss_download_control": "Download Control Plan",
        "ss_download_validation": "Download Validation Record",
        # AnyLogic simulation
        "al_heading": "AnyLogic Simulation",
        "al_caption": "Discrete-event simulation of the six-stage assembly process to verify the flow, quantify production performance and compare improvement scenarios.",
        "al_objectives": "Simulation Objectives",
        "al_objective_1": "Verify the six-stage assembly process flow",
        "al_objective_1_desc": "Source → 10 → 20 → 30 → 40 → 50 → 60 → Sink.",
        "al_objective_2": "Quantify production performance",
        "al_objective_2_desc": "Observe Completed, WIP, Throughput, resource utilization and the dominant bottleneck.",
        "al_objective_3": "Compare improvement scenarios",
        "al_objective_3_desc": "S0: baseline demand, 2 assemblers · S1: high demand, 2 assemblers · S2: high demand, 3 assemblers.",
        "al_core_question": "Core Question",
        "al_core_question_text": "Does higher demand cause backlog? Can an additional assembler raise throughput? Where does the bottleneck move?",
        "al_model_flow": "Model Flow",
        "al_model_flow_value": "Source → 10 → 20 → 30 → 40 → 50 → 60 → Sink",
        "al_process_routing": "Process Routing",
        "al_resource_capacity": "Resource Capacity",
        "al_op_no": "Operation",
        "al_op_name": "Operation Name",
        "al_time_range": "Time Range (min)",
        "al_base_time": "Base Time (min)",
        "al_distribution": "Distribution",
        "al_worker_pool": "Worker Pool",
        "al_station_pool": "Station Pool",
        "al_resource_pool": "Resource Pool",
        "al_resource_type": "Type",
        "al_capacity": "Capacity",
        "al_used_by": "Used By",
        "al_description": "Description",
        "al_scenario_comparison": "Scenario Comparison",
        "al_scenario_images": "Scenario Views",
        "al_conclusions": "Key Conclusions",
        "al_conclusion_backlog": "S1 vs S0 (high demand, same 2 assemblers): WIP rises from {wip0} to {wip1} while completed output drops from {c0} to {c1} — higher demand causes backlog without output growth.",
        "al_conclusion_throughput": "S2 vs S1 (adding a third assembler): completed output rises from {c0} to {c1} (+{pct}%) and WIP falls from {wip0} to {wip1} — the extra assembler raises throughput.",
        "al_data_status": "Data Status",
        "al_data_status_note": "Cycle times are Engineering Estimate v1, not measured production rhythm. Simulation results feed the MES dashboard analytics and serve as project delivery evidence.",
        "al_estimate_badge": "Engineering Estimate v1",
        "al_source_files": "Simulation Source",
        "al_source_caption": "Download the AnyLogic project file for the assembly process simulation.",
        "al_download_source": "Download AnyLogic Project",
        "al_asset_missing": "AnyLogic source file is missing: {name}",
    },
    "zh": {
        "title": "机械臂数字化制造项目",
        "subtitle": "从机械设计、制造执行到质量改善的完整项目展示",
        "language_label": "语言",
        # 顶层侧边栏
        "sidebar_navigation": "导航",
        "section_solidworks": "SolidWorks 建模",
        "section_anylogic": "AnyLogic 仿真",
        "section_mes_system": "MES 系统",
        "section_six_sigma": "六西格玛分析",
        "mes_heading": "制造执行系统（MES）",
        "mes_caption": "基于持久化 PostgreSQL 数据库的工单、生产、质量和追溯闭环。",
        "mes_capability_caption": "系统可创建工单及可视化生产进度。",
        # SolidWorks 建模
        "sw_heading": "SolidWorks 建模",
        "sw_caption": "农业机械臂的参数化设计与装配验证。",
        "sw_platform": "CAD 平台",
        "sw_model": "模型",
        "sw_model_value": "农业机械臂",
        "sw_actuation": "驱动配置",
        "sw_actuation_value": "3 × MG996R + 1 × SG90",
        "sw_assembly_render": "总装渲染",
        "sw_motion_demo": "运动演示",
        "sw_design_scope": "设计内容",
        "sw_scope_1": "参数化零件与装配体建模",
        "sw_scope_2": "多关节机械臂与夹爪机构",
        "sw_scope_3": "装配配合与运动验证",
        "sw_source_files": "SolidWorks 源文件包",
        "sw_source_caption": "下载完整的 SLDASM/SLDPRT 项目文件。",
        "sw_download_source": "下载 SolidWorks 项目",
        "sw_asset_missing": "缺少 SolidWorks 展示文件：{name}",
        # Tabs
        "tab_dashboard": "仪表盘",
        "tab_create_work_order": "创建工单",
        "tab_work_order_list": "工单列表",
        "tab_production_execution": "生产执行",
        "tab_quality_defects": "质量与缺陷",
        "tab_traceability": "追溯",
        "tab_six_sigma_analytics": "六西格玛分析",
        # Buttons
        "button_create_work_order": "创建工单",
        "button_release": "发布",
        "button_start": "开始",
        "button_complete": "完成",
        "button_submit_inspection": "提交检测",
        "button_start_rework": "开始返工",
        "button_close_rework": "关闭返工",
        "button_download_csv": "下载追溯 CSV",
        # Form labels
        "label_product": "产品",
        "label_planned_quantity": "计划数量",
        "label_due_date": "计划完成日期",
        "label_operator": "操作员",
        "label_work_order": "工单",
        "label_serial_number": "产品序列号",
        "label_inspector": "检验员",
        "label_defect_type": "缺陷类型",
        "label_severity": "严重度",
        "label_description": "描述",
        "label_rework_notes": "返工说明",
        # Flash messages
        "flash_work_order_created": "工单 {code} 创建成功。",
        "flash_create_failed": "创建工单失败：{e}",
        "flash_released": "工单 {code} 已发布，生成 {count} 个 Unit。",
        "flash_release_failed": "发布工单失败：{e}",
        "flash_operation_started": "工序 {code} {name} 已开始。",
        "flash_operation_completed": "工序 {code} {name} 已完成。",
        "flash_inspection_passed": "工序 {code} 检测通过（第 {attempt} 次）。",
        "flash_inspection_failed": "工序 {code} 检测失败，已创建缺陷记录。",
        "flash_rework_started": "缺陷 #{id} 已开始返工。",
        "flash_rework_closed": "返工已关闭，可重新检测。",
        # Empty / state hints
        "empty_no_products": "无产品数据，请检查数据库配置与基础数据。",
        "empty_no_work_orders": "暂无工单。",
        "empty_no_units": "该工单暂无 units。",
        "empty_no_active_orders": "暂无已发布/生产中的工单，请先在工单列表发布工单。",
        "empty_no_inspection_orders": "暂无可检测的工单（released / in_progress / completed）。",
        "empty_no_defects": "暂无缺陷记录。",
        "empty_no_quality": "暂无检测记录。",
        "empty_no_units_data": "暂无 unit 数据。",
        "empty_no_records": "暂无记录。",
        "empty_no_production_events": "暂无生产事件。",
        "hint_enter_operator": "开始或完成工序前请输入操作员。",
        "hint_completed_readonly": "该 Unit 已完成，只读。",
        "hint_no_qc_awaiting": "当前无待检测的质量工序。",
        "hint_resolve_defect": "请先处理未关闭缺陷。",
        "hint_rework_in_progress": "返工进行中，请完成返工并关闭缺陷后重新检测。",
        "hint_completed_readonly_defect": "已完成，只读。",
        # Work order list fields
        "wo_product": "产品",
        "wo_status": "状态",
        "wo_planned_quantity": "计划数量",
        "wo_due_date": "计划完成日期",
        "wo_created": "创建时间",
        "wo_released": "发布时间",
        "wo_units": "Unit 数量",
        "wo_serial_numbers": "序列号",
        # Production execution
        "pe_current_unit_status": "当前 Unit 状态",
        "pe_operation_progress": "工序进度",
        "pe_goto_quality": "→ 质量与缺陷页签",
        # Quality
        "q_current_qc": "当前质量工序",
        "q_inspection_items": "检查项目",
        "q_defect_details": "缺陷信息（检测失败时必填）",
        "q_defect_records": "缺陷列表",
        "q_inspection_history": "历次检测记录",
        "q_inspection_items_attempt": "检查项（第 {attempt} 次）",
        # Traceability
        "tr_summary": "摘要",
        "tr_unit": "Unit",
        "tr_product": "产品",
        "tr_work_order": "工单",
        "tr_operations": "工序",
        "tr_production_events": "生产事件",
        "tr_quality_history": "质量历史",
        "tr_defect_history": "缺陷与返工历史",
        "tr_download": "下载",
        "tr_field_serial_number": "序列号",
        "tr_field_status": "状态",
        "tr_field_created": "创建时间",
        "tr_field_planned_start": "计划开始",
        "tr_field_planned_end": "计划完成",
        "tr_field_released": "发布时间",
        "tr_field_operation": "工序",
        "tr_field_operation_name": "工序名称",
        "tr_field_sequence": "顺序",
        "tr_field_worker": "工人",
        "tr_field_station": "工位",
        "tr_field_base_time": "基准工时(分钟)",
        "tr_field_attempt": "次数",
        "tr_field_event": "事件",
        "tr_field_operator": "操作员",
        "tr_field_timestamp": "时间戳",
        "tr_field_description": "描述",
        "tr_field_severity": "严重度",
        "tr_field_closed": "关闭时间",
        "tr_field_rework_notes": "返工说明",
        # Dashboard
        "db_mes_live": "MES 实时概览",
        "db_caption_demo": "MES 数值基于当前演示数据库。",
        "db_work_orders": "工单数",
        "db_total_units": "Unit 总数",
        "db_completed_units": "已完成 Unit",
        "db_wip": "在制品",
        "db_completion_rate": "完成率",
        "db_inspection_pass_rate": "检测通过率",
        "db_defects": "缺陷数",
        "db_unit_status_dist": "Unit 状态分布",
        "db_production_events": "按工序的生产事件",
        "db_scenario": "场景",
        "db_arrival_interval": "到达间隔",
        "db_assembly_capacity": "装配产能",
        "db_mean_completed": "平均完成数",
        "db_mean_wip_col": "平均 WIP",
        "db_mean_throughput_col": "平均吞吐量",
        "db_mean_assembly_util_col": "平均装配利用率",
        "db_dominant_bottleneck": "主要瓶颈",
        "db_mean_bottleneck_util": "平均瓶颈利用率",
        "db_validation_failed": "仿真数据验证失败：{e}",
        "state_completed": "已完成",
        "state_in_progress": "进行中",
        "state_ready": "就绪",
        "state_locked": "锁定",
        "state_quality_required": "需质量记录",
        "state_defect_open": "缺陷待处理",
        "state_rework": "返工",
        "conclusion_bottleneck": "主要瓶颈由 {frm} 转为 {to}。",
        # Six Sigma & Analytics
        "ss_release": "V5 正式验证版本",
        "ss_synthetic_notice": "合成数据——仅用于项目展示，不代表实测生产性能，也不构成真实物理因果证据。",
        "ss_validation_ok": "EOL-EG-V5 的源文件哈希、版本信息、数据行数及独立重算的核心指标均已通过验证。",
        "ss_validation_failed": "Six Sigma V5 数据验证失败：{e}",
        "ss_version": "版本",
        "ss_release_status": "发布状态",
        "ss_ctq": "关键质量特性（CTQ）",
        "ss_ctq_gripping_force": "夹持力",
        "ss_specification": "规格范围",
        "ss_target": "目标值",
        "ss_process_comparison": "改善前后过程能力对比",
        "ss_stage": "阶段",
        "ss_before": "改善前",
        "ss_after": "改善后",
        "ss_sample_size": "样本量",
        "ss_mean_force": "平均夹持力（N）",
        "ss_standard_deviation": "样本标准差（N）",
        "ss_defects": "观测缺陷数",
        "ss_defect_rate": "缺陷率",
        "ss_pp": "Pp",
        "ss_ppk": "Ppk",
        "ss_sd_reduction": "标准差降低",
        "ss_ppk_change": "Ppk 提升",
        "ss_centering_gain": "中心偏差改善",
        "ss_capability_stability": "过程能力与稳定性判定",
        "ss_ppk_reference": "Ppk 参考值",
        "ss_ppk_below": "改善后 Ppk 为 {ppk}，仍低于 {reference} 参考值。",
        "ss_ppk_meets": "改善后 Ppk 为 {ppk}，达到 {reference} 参考值。",
        "ss_phase_i": "第一阶段状态",
        "ss_phase_i_not_control": "未受控",
        "ss_phase_ii": "第二阶段控制限",
        "ss_phase_ii_not_established": "尚未建立",
        "ss_mr_alarms": "改善后 MR 报警点",
        "ss_msa": "测量系统分析",
        "ss_grr_tolerance": "量具 R&R（占公差百分比）",
        "ss_ndc": "可区分类别数（ndc）",
        "ss_acceptance": "判定",
        "ss_msa_note": "测量系统为有条件接受，并非无条件通过；仍需改进或形成书面合理性说明。",
        "ss_root_causes": "模型内根因优先级",
        "ss_rank": "排名",
        "ss_factor": "因素",
        "ss_category": "类别",
        "ss_contribution": "模型平均值改善贡献（N）",
        "ss_factor_sd_reduction": "因素标准差降低",
        "ss_control_action": "控制措施",
        "ss_current_status": "当前状态",
        "ss_root_cause_note": "这些关系仅在已声明的合成模型内得到确认；真实因果关系仍需实测、DOE 或受控试验验证。",
        "ss_control_readiness": "控制计划就绪度",
        "ss_control_item": "控制项目",
        "ss_frequency": "频次",
        "ss_owner": "负责人",
        "ss_control_items": "控制项目数",
        "ss_open_items": "未关闭项目数",
        "ss_control_note": "在 MR 报警、Ppk 参考值差距及 MSA 有条件判定关闭前，Control 阶段保持 OPEN。",
        "ss_charts": "V5 验证图表",
        "ss_chart_note": "图内标注保留 V5 验证版本的原始英文。",
        "ss_data_preview": "V5 数据预览",
        "ss_downloads": "源文件下载",
        "ss_download_report": "下载分析报告",
        "ss_download_raw": "下载改善前后 CSV",
        "ss_download_control": "下载控制计划",
        "ss_download_validation": "下载验证记录",
        # AnyLogic 仿真
        "al_heading": "AnyLogic 仿真",
        "al_caption": "基于六道装配工序的离散事件仿真，用于验证流程、量化生产表现并比较改善方案。",
        "al_objectives": "仿真目的",
        "al_objective_1": "验证六道装配工序流程是否合理",
        "al_objective_1_desc": "Source → 工序10 → 20 → 30 → 40 → 50 → 60 → Sink。",
        "al_objective_2": "量化生产表现",
        "al_objective_2_desc": "观测 Completed、WIP、Throughput、资源利用率和主要瓶颈。",
        "al_objective_3": "比较改善方案",
        "al_objective_3_desc": "S0：基准需求、2名装配人员 · S1：高需求、2名装配人员 · S2：高需求、3名装配人员。",
        "al_core_question": "核心问题",
        "al_core_question_text": "需求增加后会不会积压？增加一名装配人员能否提高产出？瓶颈会转移到哪里？",
        "al_model_flow": "模型流程",
        "al_model_flow_value": "Source → 工序10 → 20 → 30 → 40 → 50 → 60 → Sink",
        "al_process_routing": "工序路由",
        "al_resource_capacity": "资源与产能",
        "al_op_no": "工序",
        "al_op_name": "工序名称",
        "al_time_range": "工时范围(分钟)",
        "al_base_time": "基准工时(分钟)",
        "al_distribution": "分布",
        "al_worker_pool": "人员",
        "al_station_pool": "工位",
        "al_resource_pool": "资源池",
        "al_resource_type": "类型",
        "al_capacity": "产能",
        "al_used_by": "用于工序",
        "al_description": "说明",
        "al_scenario_comparison": "场景对比",
        "al_scenario_images": "场景视图",
        "al_conclusions": "核心结论",
        "al_conclusion_backlog": "S1 相对 S0（高需求、同样2名装配）：WIP 从 {wip0} 升至 {wip1}，完成数从 {c0} 降至 {c1}——需求增加导致积压、产出未增。",
        "al_conclusion_throughput": "S2 相对 S1（增加第三名装配）：完成数从 {c0} 升至 {c1}（+{pct}%），WIP 从 {wip0} 降至 {wip1}——增加装配人员提高了产出。",
        "al_data_status": "数据状态",
        "al_data_status_note": "当前工时属于 Engineering Estimate v1，并非实测生产节拍。仿真结果用于生成 MES 网页分析数据与项目交付证据。",
        "al_estimate_badge": "Engineering Estimate v1",
        "al_source_files": "仿真源文件",
        "al_source_caption": "下载装配流程仿真的 AnyLogic 项目文件。",
        "al_download_source": "下载 AnyLogic 项目",
        "al_asset_missing": "缺少 AnyLogic 源文件：{name}",
    },
}

# Name maps: English -> Chinese (used only for display)
STATUS_LABELS = {
    "draft": "Draft",
    "released": "Released",
    "in_progress": "In Progress",
    "queued": "Queued",
    "in_production": "In Production",
    "rework": "Rework",
    "completed": "Completed",
    "scrapped": "Scrapped",
    "cancelled": "Cancelled",
}

STATUS_ZH = {
    "draft": "草稿",
    "released": "已发布",
    "in_progress": "进行中",
    "queued": "排队中",
    "in_production": "生产中",
    "rework": "返工",
    "completed": "已完成",
    "scrapped": "报废",
    "cancelled": "已取消",
}

OPERATION_NAME_ZH = {
    "Parts Kitting": "备料齐套",
    "Mechanical Pre-assembly": "机械预装配",
    "Servo & Joint Assembly": "伺服与关节装配",
    "Gripper Assembly & Calibration": "夹爪装配与标定",
    "Functional Testing": "功能测试",
    "Final Inspection": "最终检验",
}

CHECK_ITEM_ZH = {
    "base_rotation_ok": "底座旋转",
    "joint_motion_ok": "关节运动",
    "gripper_motion_ok": "夹爪运动",
    "no_interference": "无机械干涉",
    "appearance_ok": "外观",
    "connections_ok": "电气与机械连接",
    "test_record_complete": "测试记录完整",
}

SIX_SIGMA_FACTOR_ZH = {
    "Jaw alignment error": "夹爪对中误差",
    "Gear backlash": "齿轮回程间隙",
    "Motor current": "电机电流",
    "Fastener torque": "紧固件扭矩",
    "Pad thickness": "夹持垫厚度",
    "People": "人员",
    "Measurement": "测量",
    "Environment": "环境",
}

SIX_SIGMA_CATEGORY_ZH = {
    "Machine": "设备",
    "Method": "方法",
    "Material": "材料",
    "People": "人员",
    "Measurement": "测量",
    "Environment": "环境",
}

SIX_SIGMA_ACCEPTANCE_ZH = {
    "PASS": "通过",
    "CONDITIONAL": "有条件接受",
    "UNACCEPTABLE": "不可接受",
}

SIX_SIGMA_CONTROL_STATUS_ZH = {
    "CURRENT": "当前版本",
    "PASS": "通过",
    "PASS_SAMPLE_ONLY": "仅当前样本通过",
    "PROVISIONAL": "暂定",
    "WATCH": "观察",
    "CONDITIONAL": "有条件接受",
    "UNACCEPTABLE": "不可接受",
    "ACTION_REQUIRED": "需要采取措施",
}

SIX_SIGMA_CHART_TITLE_ZH = {
    "01_force_run_chart.png": "生产顺序中的夹持力",
    "02_force_distribution.png": "改善后夹持力分布向目标值集中",
    "03_force_boxplot.png": "改善前后夹持力箱线图",
    "04_imr_before.png": "改善前 I-MR 控制图",
    "05_imr_after.png": "改善后 I-MR 控制图",
    "06_capability_comparison.png": "过程能力对比",
    "07_process_factor_distributions.png": "过程因素分布",
    "08_msa_variance_components.png": "MSA 方差分量",
    "09_msa_part_appraiser.png": "零件与检验员测量对比",
    "10_improvement_summary.png": "改善效果汇总",
    "11_root_cause_contribution.png": "根因贡献分析",
    "12_control_plan_readiness.png": "控制计划就绪度",
}

PAGE_KEYS = [
    "dashboard",
    "create_work_order",
    "work_order_list",
    "production_execution",
    "quality_defects",
    "traceability",
]

MAIN_SECTION_KEYS = ["solidworks", "anylogic", "mes_system", "six_sigma"]

OPERATION_STATE_KEYS = {
    "Completed": "state_completed",
    "In Progress": "state_in_progress",
    "Ready": "state_ready",
    "Locked": "state_locked",
    "Quality Required": "state_quality_required",
    "Defect Open": "state_defect_open",
    "Rework": "state_rework",
}

LANGUAGE_OPTIONS = ["en", "zh"]
LANGUAGE_LABELS = {"en": "English", "zh": "中文"}


def _lang():
    return st.session_state.get("language", "en")


def t(key, **kwargs):
    template = TRANSLATIONS[_lang()].get(key, TRANSLATIONS["en"][key])
    return template.format(**kwargs) if kwargs else template


def format_status(status):
    if _lang() == "zh":
        return STATUS_ZH.get(status, status)
    return STATUS_LABELS.get(status, status)


def format_operation_name(name):
    if _lang() == "zh":
        return OPERATION_NAME_ZH.get(name, name)
    return name


def format_check_item(item):
    if _lang() == "zh":
        return CHECK_ITEM_ZH.get(item, item)
    return CHECK_ITEM_LABELS_EN.get(item, item)


def format_six_sigma_factor(value):
    if _lang() == "zh":
        return SIX_SIGMA_FACTOR_ZH.get(value, value)
    return value


def format_six_sigma_category(value):
    if _lang() == "zh":
        return SIX_SIGMA_CATEGORY_ZH.get(value, value)
    return value


def format_six_sigma_acceptance(value):
    if _lang() == "zh":
        return SIX_SIGMA_ACCEPTANCE_ZH.get(value, value)
    return value


def format_six_sigma_control_status(value):
    if _lang() == "zh":
        return SIX_SIGMA_CONTROL_STATUS_ZH.get(value, value)
    return value.replace("_", " ").title()


def format_six_sigma_chart_title(chart):
    if _lang() == "zh":
        return SIX_SIGMA_CHART_TITLE_ZH.get(chart["chart_file"], chart["chart_title"])
    return chart["chart_title"]


CHECK_ITEM_LABELS_EN = {
    "base_rotation_ok": "Base Rotation",
    "joint_motion_ok": "Joint Motion",
    "gripper_motion_ok": "Gripper Motion",
    "no_interference": "No Mechanical Interference",
    "appearance_ok": "Appearance",
    "connections_ok": "Electrical and Mechanical Connections",
    "test_record_complete": "Test Record Complete",
}


def set_flash(message, message_type="success"):
    st.session_state["_flash_message"] = {
        "message": message,
        "type": message_type,
    }


# ---------------------------------------------------------------------------
# Handlers (on_click callbacks)
# ---------------------------------------------------------------------------
def handle_create_work_order():
    try:
        products = list_products()
        product_options = {p["product_code"]: p["product_id"] for p in products}
        product_code = st.session_state.get("create_product_code")
        planned_quantity = int(st.session_state.get("create_planned_quantity", 1))
        due_date = st.session_state.get("create_due_date")
        if product_code not in product_options:
            raise ValueError(t("flash_create_failed").format(e="no product selected"))
        due_str = due_date.isoformat() if hasattr(due_date, "isoformat") else str(due_date)
        wid = create_work_order(product_options[product_code], planned_quantity, due_str)
        code = next(
            (o["work_order_code"] for o in list_work_orders() if o["work_order_id"] == wid),
            str(wid),
        )
        set_flash(t("flash_work_order_created", code=code))
    except Exception as e:
        set_flash(t("flash_create_failed", e=e), "error")


def handle_release_work_order(work_order_id):
    try:
        serials = release_work_order(work_order_id)
        code = next(
            (o["work_order_code"] for o in list_work_orders() if o["work_order_id"] == work_order_id),
            str(work_order_id),
        )
        set_flash(t("flash_released", code=code, count=len(serials)))
    except Exception as e:
        set_flash(t("flash_release_failed", e=e), "error")


def handle_start_operation(unit_id, operation_id):
    try:
        operator = st.session_state.get("prod_operator", "").strip()
        op_info = start_operation(unit_id, operation_id, operator)
        set_flash(t("flash_operation_started", code=op_info["operation_code"], name=format_operation_name(op_info["operation_name"])))
    except Exception as e:
        set_flash(str(e), "error")


def handle_complete_operation(unit_id, operation_id):
    try:
        operator = st.session_state.get("prod_operator", "").strip()
        op_info = complete_operation(unit_id, operation_id, operator)
        set_flash(t("flash_operation_completed", code=op_info["operation_code"], name=format_operation_name(op_info["operation_name"])))
    except Exception as e:
        set_flash(str(e), "error")


def handle_submit_inspection(unit_id, operation_id, operation_code):
    try:
        inspector = st.session_state.get("q_inspector", "").strip()
        items = CHECK_ITEMS[operation_code]
        check_results = {}
        for item in items:
            check_results[item] = st.session_state.get(f"q_check_{operation_id}_{item}_{unit_id}", False)
        defect_type = st.session_state.get("q_dtype", "")
        severity = st.session_state.get("q_sev", "minor")
        defect_description = st.session_state.get("q_ddesc", "")
        res = submit_inspection(
            unit_id, operation_id, inspector, check_results,
            defect_type=defect_type, defect_description=defect_description, severity=severity,
        )
        if res["result"] == "pass":
            set_flash(t("flash_inspection_passed", code=operation_code, attempt=res["attempt_no"]))
        else:
            set_flash(t("flash_inspection_failed", code=operation_code), "error")
    except Exception as e:
        set_flash(str(e), "error")


def handle_start_rework(defect_id):
    try:
        start_rework(defect_id)
        set_flash(t("flash_rework_started", id=defect_id))
    except Exception as e:
        set_flash(str(e), "error")


def handle_close_rework(defect_id):
    try:
        rework_notes = st.session_state.get(f"notes_{defect_id}", "").strip()
        close_rework(defect_id, rework_notes)
        set_flash(t("flash_rework_closed"))
    except Exception as e:
        set_flash(str(e), "error")


# ---------------------------------------------------------------------------
# Render functions
# ---------------------------------------------------------------------------
def render_solidworks_modeling():
    st.header(t("sw_heading"))
    st.caption(t("sw_caption"))

    c1, c2, c3 = st.columns(3)
    c1.metric(t("sw_platform"), "SolidWorks")
    c2.metric(t("sw_model"), t("sw_model_value"))
    c3.metric(t("sw_actuation"), t("sw_actuation_value"))

    render_path = SOLIDWORKS_ASSET_DIR / "assembly_isometric.png"
    video_path = APP_DIR / "A_final_Robotic Arm.mp4"
    source_path = SOLIDWORKS_ASSET_DIR / "SW_Agricultural_Manipulator_Portfolio.zip"

    st.subheader(t("sw_assembly_render"))
    if render_path.is_file():
        st.image(str(render_path), use_container_width=True)
    else:
        st.warning(t("sw_asset_missing", name=render_path.name))

    left, right = st.columns([2, 1])
    with left:
        st.subheader(t("sw_motion_demo"))
        if video_path.is_file():
            st.video(str(video_path))
        else:
            st.warning(t("sw_asset_missing", name=video_path.name))
    with right:
        st.subheader(t("sw_design_scope"))
        st.markdown(
            "\n".join(
                [
                    f"- {t('sw_scope_1')}",
                    f"- {t('sw_scope_2')}",
                    f"- {t('sw_scope_3')}",
                ]
            )
        )
        st.subheader(t("sw_source_files"))
        st.caption(t("sw_source_caption"))
        if source_path.is_file():
            st.download_button(
                t("sw_download_source"),
                source_path.read_bytes(),
                file_name=source_path.name,
                mime="application/zip",
                on_click="ignore",
                use_container_width=True,
            )
        else:
            st.warning(t("sw_asset_missing", name=source_path.name))


def render_anylogic_simulation():
    st.header(t("al_heading"))
    st.caption(t("al_caption"))

    st.markdown(f"### {t('al_objectives')}")
    for i in (1, 2, 3):
        st.markdown(f"**{i}. {t(f'al_objective_{i}')}**")
        st.markdown(t(f"al_objective_{i}_desc"))

    st.markdown(f"### {t('al_core_question')}")
    st.markdown(t("al_core_question_text"))

    st.markdown(f"### {t('al_model_flow')}")
    st.code(t("al_model_flow_value"), language=None)

    st.markdown(f"### {t('al_process_routing')}")
    try:
        routing = get_process_routing()
    except AnyLogicDataError as exc:
        st.error(str(exc))
        routing = []
    if routing:
        routing_df = pd.DataFrame([{
            t("al_op_no"): f"OP{r['operation_no']}",
            t("al_op_name"): r["name_zh"] if _lang() == "zh" else r["name_en"],
            t("al_time_range"): f"{r['min_time']:.0f}–{r['max_time']:.0f}",
            t("al_base_time"): r["base_time"],
            t("al_distribution"): r["distribution"],
            t("al_worker_pool"): r["worker_pool"],
            t("al_station_pool"): r["station_pool"],
        } for r in routing])
        st.dataframe(routing_df, use_container_width=True, hide_index=True)

    st.markdown(f"### {t('al_resource_capacity')}")
    try:
        resources = get_resource_capacity()
    except AnyLogicDataError as exc:
        st.error(str(exc))
        resources = []
    if resources:
        res_df = pd.DataFrame([{
            t("al_resource_pool"): r["resource_pool"],
            t("al_resource_type"): r["type"],
            t("al_capacity"): r["capacity"],
            t("al_used_by"): r["used_by"],
            t("al_description"): r["description"],
        } for r in resources])
        st.dataframe(res_df, use_container_width=True, hide_index=True)

    st.markdown(f"### {t('al_scenario_comparison')}")
    try:
        validate_simulation_data()
        comparison = get_scenario_comparison()
    except Exception as exc:
        st.error(t("db_validation_failed", e=exc))
        return

    comp_df = pd.DataFrame(comparison)
    comp_display = pd.DataFrame({
        t("db_scenario"): comp_df["scenario_id"],
        t("db_arrival_interval"): comp_df["arrival_interval"],
        t("db_assembly_capacity"): comp_df["assembly_capacity"],
        t("db_mean_completed"): comp_df["mean_completed"],
        t("db_mean_wip_col"): comp_df["mean_wip"],
        t("db_mean_throughput_col"): comp_df["mean_throughput"],
        t("db_mean_assembly_util_col"): comp_df["mean_assembly_util"].apply(lambda x: f"{x * 100:.1f}%"),
        t("db_dominant_bottleneck"): comp_df["dominant_bottleneck"],
        t("db_mean_bottleneck_util"): comp_df["mean_bottleneck_util"].apply(lambda x: f"{x * 100:.1f}%"),
    })
    st.dataframe(comp_display, use_container_width=True, hide_index=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"**{t('db_mean_completed')}**")
        st.bar_chart(comp_df.set_index("scenario_id")["mean_completed"])
    with c2:
        st.markdown(f"**{t('db_mean_wip_col')}**")
        st.bar_chart(comp_df.set_index("scenario_id")["mean_wip"])
    with c3:
        st.markdown(f"**{t('db_mean_throughput_col')}**")
        st.bar_chart(comp_df.set_index("scenario_id")["mean_throughput"])

    st.markdown(f"### {t('al_conclusions')}")
    s0 = next(c for c in comparison if c["scenario_id"] == "S0")
    s1 = next(c for c in comparison if c["scenario_id"] == "S1")
    s2 = next(c for c in comparison if c["scenario_id"] == "S2")
    throughput_gain = (s2["mean_throughput"] - s1["mean_throughput"]) / s1["mean_throughput"] * 100
    st.markdown("- " + t("al_conclusion_backlog",
        wip0=f"{s0['mean_wip']:.1f}", wip1=f"{s1['mean_wip']:.1f}",
        c0=f"{s0['mean_completed']:.1f}", c1=f"{s1['mean_completed']:.1f}"))
    st.markdown("- " + t("al_conclusion_throughput",
        c0=f"{s1['mean_completed']:.1f}", c1=f"{s2['mean_completed']:.1f}",
        pct=f"{throughput_gain:.1f}",
        wip0=f"{s1['mean_wip']:.1f}", wip1=f"{s2['mean_wip']:.1f}"))
    st.markdown("- " + t("conclusion_bottleneck", frm=s0["dominant_bottleneck"], to=s2["dominant_bottleneck"]))

    st.markdown(f"### {t('al_scenario_images')}")
    scenario_names = {c["scenario_id"]: c["scenario_name"] for c in comparison}
    img_cols = st.columns(2)
    for col, sid in zip(img_cols, ("S1", "S2")):
        with col:
            img_path = SCENARIO_IMAGES[sid]
            if img_path.is_file():
                st.image(str(img_path), use_container_width=True, caption=f"{sid} — {scenario_names.get(sid, '')}")
            else:
                st.caption(f"{sid}: {t('sw_asset_missing', name=img_path.name)}")

    st.markdown(f"### {t('al_data_status')}")
    st.caption(f"**{t('al_estimate_badge')}** — {t('al_data_status_note')}")

    st.markdown(f"### {t('al_source_files')}")
    st.caption(t("al_source_caption"))
    if SOURCE_ALP.is_file():
        st.download_button(
            t("al_download_source"),
            SOURCE_ALP.read_bytes(),
            file_name=SOURCE_ALP.name,
            mime="application/octet-stream",
            on_click="ignore",
            use_container_width=True,
        )
    else:
        st.warning(t("al_asset_missing", name=SOURCE_ALP.name))


def render_create_work_order():
    st.subheader(t("tab_create_work_order"))
    products = list_products()
    if not products:
        st.warning(t("empty_no_products"))
    else:
        product_options = {p["product_code"]: p["product_id"] for p in products}
        c1, c2, c3 = st.columns(3)
        with c1:
            st.selectbox(t("label_product"), list(product_options.keys()), key="create_product_code")
        with c2:
            st.number_input(t("label_planned_quantity"), min_value=1, step=1, value=1, key="create_planned_quantity")
        with c3:
            st.date_input(t("label_due_date"), value=date.today() + timedelta(days=7), key="create_due_date")
        st.button(t("button_create_work_order"), type="primary", on_click=handle_create_work_order)


def render_work_order_list():
    st.subheader(t("tab_work_order_list"))
    orders = list_work_orders()
    if not orders:
        st.info(t("empty_no_work_orders"))
    else:
        st.caption(f"{len(orders)}")
        for o in orders:
            title = f"{o['work_order_code']}  |  {o['product_code']}  |  Qty {o['quantity']}  |  {format_status(o['status'])}"
            with st.expander(title):
                st.write(f"{t('wo_product')}: {o['product_name']}")
                st.write(f"{t('wo_status')}: {format_status(o['status'])}")
                st.write(f"{t('wo_planned_quantity')}: {o['quantity']}")
                st.write(f"{t('wo_due_date')}: {o['planned_end']}")
                st.write(f"{t('wo_created')}: {o['created_at']}")
                st.write(f"{t('wo_released')}: {o['released_at'] or '—'}")
                st.write(f"{t('wo_units')}: {o['unit_count']}")
                if o["status"] == "draft":
                    st.button(t("button_release"), key=f"release_{o['work_order_id']}", on_click=handle_release_work_order, args=(o["work_order_id"],))
                elif o["unit_count"] > 0:
                    units = get_units(o["work_order_id"])
                    st.write(t("wo_serial_numbers") + ":")
                    for u in units:
                        st.write(f"- {u['serial_number']}  ({format_status(u['status'])})")


def render_production_execution():
    st.subheader(t("tab_production_execution"))
    operator = st.text_input(t("label_operator"), key="prod_operator")
    operator_ok = bool(operator.strip())
    if not operator_ok:
        st.caption(t("hint_enter_operator"))

    active_orders = list_active_work_orders()
    if not active_orders:
        st.info(t("empty_no_active_orders"))
    else:
        order_options = {o["work_order_code"]: o["work_order_id"] for o in active_orders}
        c1, c2 = st.columns(2)
        with c1:
            selected_code = st.selectbox(t("label_work_order"), list(order_options.keys()))
        selected_wo_id = order_options[selected_code]

        units = list_units_for_order(selected_wo_id)
        if not units:
            st.warning(t("empty_no_units"))
        else:
            unit_options = {u["serial_number"]: u["unit_id"] for u in units}
            with c2:
                selected_sn = st.selectbox(t("label_serial_number"), list(unit_options.keys()))
            selected_unit_id = unit_options[selected_sn]

            result = get_unit_progress(selected_unit_id)
            st.write(f"{t('pe_current_unit_status')}: **{format_status(result['unit']['status'])}**")

            st.markdown(f"#### {t('pe_operation_progress')}")
            for p in result["progress"]:
                is_quality = p["operation_code"] in ("50", "60")
                cc1, cc2, cc3, cc4 = st.columns([3, 3, 1.6, 1.6])
                with cc1:
                    st.write(f"**{p['operation_code']} {format_operation_name(p['operation_name'])}**")
                with cc2:
                    st.caption(f"{p['worker']} · {p['station']} · base {p['base_time_min']} min")
                with cc3:
                    state_key = OPERATION_STATE_KEYS.get(p["state"])
                    state_label = t(state_key) if state_key else p["state"]
                    if p["state"] == "Completed":
                        st.success(state_label)
                    elif p["state"] == "In Progress":
                        st.info(state_label)
                    elif p["state"] == "Ready":
                        st.warning(state_label)
                    elif p["state"] == "Locked":
                        st.caption(state_label)
                    elif p["state"] == "Quality Required":
                        st.error(state_label)
                    elif p["state"] == "Defect Open":
                        st.error(state_label)
                    elif p["state"] == "Rework":
                        st.error(state_label)
                with cc4:
                    if p["state"] == "Ready":
                        st.button(t("button_start"), key=f"start_{p['operation_id']}_{selected_unit_id}", disabled=not operator_ok, on_click=handle_start_operation, args=(selected_unit_id, p["operation_id"]))
                    elif p["state"] == "In Progress" and not is_quality:
                        st.button(t("button_complete"), key=f"complete_{p['operation_id']}_{selected_unit_id}", disabled=not operator_ok, on_click=handle_complete_operation, args=(selected_unit_id, p["operation_id"]))
                    elif is_quality and p["state"] in ("Quality Required", "Defect Open", "Rework"):
                        st.caption(t("pe_goto_quality"))


def render_quality_defects():
    st.subheader(t("tab_quality_defects"))

    inspection_orders = list_inspection_work_orders()
    if not inspection_orders:
        st.info(t("empty_no_inspection_orders"))
    else:
        order_options = {o["work_order_code"]: o["work_order_id"] for o in inspection_orders}
        c1, c2 = st.columns(2)
        with c1:
            selected_code = st.selectbox(t("label_work_order"), list(order_options.keys()), key="q_wo")
        selected_wo_id = order_options[selected_code]

        units = list_units_for_order(selected_wo_id)
        if not units:
            st.warning(t("empty_no_units"))
        else:
            unit_options = {u["serial_number"]: u["unit_id"] for u in units}
            with c2:
                selected_sn = st.selectbox(t("label_serial_number"), list(unit_options.keys()), key="q_sn")
            selected_unit_id = unit_options[selected_sn]

            result = get_unit_progress(selected_unit_id)
            unit_status = result["unit"]["status"]
            st.write(f"{t('pe_current_unit_status')}: **{format_status(unit_status)}**")

            current_qc = None
            for p in result["progress"]:
                if p["operation_code"] in ("50", "60") and p["state"] in ("Quality Required", "Defect Open", "Rework"):
                    current_qc = p
                    break

            st.markdown("---")

            if current_qc is None:
                if unit_status == "completed":
                    st.success(t("hint_completed_readonly"))
                else:
                    st.info(t("hint_no_qc_awaiting"))
            elif current_qc["state"] == "Quality Required":
                st.markdown(f"#### {t('q_current_qc')}: {current_qc['operation_code']} {format_operation_name(current_qc['operation_name'])}")
                inspector = st.text_input(t("label_inspector"), key="q_inspector")

                items = CHECK_ITEMS[current_qc["operation_code"]]
                st.write(t("q_inspection_items") + ":")
                for item in items:
                    st.checkbox(format_check_item(item), key=f"q_check_{current_qc['operation_id']}_{item}_{selected_unit_id}")

                st.write(t("q_defect_details") + ":")
                dc1, dc2 = st.columns(2)
                dc1.text_input(t("label_defect_type"), key="q_dtype")
                dc2.selectbox(t("label_severity"), ["minor", "major", "critical"], key="q_sev")
                st.text_input(t("label_description"), key="q_ddesc")

                st.button(t("button_submit_inspection"), type="primary", disabled=not bool(inspector.strip()), on_click=handle_submit_inspection, args=(selected_unit_id, current_qc["operation_id"], current_qc["operation_code"]))
            elif current_qc["state"] == "Defect Open":
                st.warning(t("hint_resolve_defect"))
            elif current_qc["state"] == "Rework":
                st.info(t("hint_rework_in_progress"))

            st.markdown("---")
            st.markdown(f"#### {t('q_defect_records')}")
            defects = list_defects(selected_unit_id)
            if not defects:
                st.info(t("empty_no_defects"))
            else:
                for d in defects:
                    with st.expander(f"#{d['defect_id']} {d['defect_type']} [{format_status(d['status'])}] ({d['operation_code']})"):
                        st.write(f"{t('tr_field_description')}: {d['description']}")
                        st.write(f"{t('tr_field_severity')}: {d['severity']}")
                        st.write(f"{t('tr_field_created')}: {d['created_at']}")
                        if unit_status == "completed":
                            st.caption(t("hint_completed_readonly_defect"))
                        elif d["status"] == "open":
                            st.button(t("button_start_rework"), key=f"rework_{d['defect_id']}", on_click=handle_start_rework, args=(d["defect_id"],))
                        elif d["status"] == "in_rework":
                            rework_notes = st.text_input(t("label_rework_notes"), key=f"notes_{d['defect_id']}")
                            st.button(t("button_close_rework"), key=f"close_{d['defect_id']}", disabled=not bool(rework_notes.strip()), on_click=handle_close_rework, args=(d["defect_id"],))
                        else:
                            st.write(f"{t('tr_field_closed')}: {d['closed_at']}")
                            st.write(f"{t('tr_field_rework_notes')}: {d['rework_notes']}")

            st.markdown("---")
            st.markdown(f"#### {t('q_inspection_history')}")
            records = list_quality_records(selected_unit_id)
            if not records:
                st.info(t("empty_no_quality"))
            else:
                for r in records:
                    st.write(f"attempt {r['attempt_no']} · {r['operation_code']} {format_operation_name(r['operation_name'])} · {r['result'].upper()} · {r['inspected_at']} · {r['inspector']}")
                    with st.expander(t("q_inspection_items_attempt", attempt=r["attempt_no"])):
                        st.code(r["measurement"], language="json")


def render_traceability():
    st.subheader(t("tab_traceability"))

    units = list_all_units()
    if not units:
        st.info(t("empty_no_units_data"))
    else:
        serial_options = [u["serial_number"] for u in units]
        selected_sn = st.selectbox(t("label_serial_number"), serial_options, key="trace_sn")

        trace = get_unit_traceability(selected_sn)
        unit = trace["unit"]
        product = trace["product"]
        wo = trace["work_order"]

        st.markdown(f"### {t('tr_summary')}")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"**{t('tr_unit')}**")
            st.write(f"{t('tr_field_serial_number')}: {unit['serial_number']}")
            st.write(f"{t('tr_field_status')}: {format_status(unit['status'])}")
            st.write(f"{t('tr_field_created')}: {unit['created_at']}")
        with c2:
            st.markdown(f"**{t('tr_product')}**")
            st.write(product["product_code"])
            st.write(product["product_name"])
        with c3:
            st.markdown(f"**{t('tr_work_order')}**")
            st.write(wo["work_order_code"])
            st.write(f"{t('tr_field_status')}: {format_status(wo['status'])}")
            st.write(f"{t('wo_planned_quantity')}: {wo['quantity']}")
            st.write(f"{t('tr_field_planned_start')}: {wo['planned_start'] or '—'}")
            st.write(f"{t('tr_field_planned_end')}: {wo['planned_end'] or '—'}")
            st.write(f"{t('tr_field_released')}: {wo['released_at'] or '—'}")

        st.markdown(f"### {t('tr_operations')}")
        ops_df = pd.DataFrame([{
            t("tr_field_operation"): o["operation_code"],
            t("tr_field_operation_name"): format_operation_name(o["operation_name"]),
            t("tr_field_sequence"): o["sequence"],
            t("tr_field_worker"): o["worker"],
            t("tr_field_station"): o["station"],
            t("tr_field_base_time"): o["base_time_min"],
            t("tr_field_status"): o["state"],
        } for o in trace["operations"]])
        st.dataframe(ops_df, use_container_width=True, hide_index=True)

        st.markdown(f"### {t('tr_production_events')}")
        if not trace["production_events"]:
            st.info(t("empty_no_records"))
        else:
            ev_df = pd.DataFrame([{
                t("tr_field_operation"): e["operation_code"],
                t("tr_field_operation_name"): format_operation_name(e["operation_name"]),
                t("tr_field_attempt"): e["attempt_no"],
                t("tr_field_event"): e["event_type"],
                t("tr_field_operator"): e["operator"],
                t("tr_field_timestamp"): e["occurred_at"],
            } for e in trace["production_events"]])
            st.dataframe(ev_df, use_container_width=True, hide_index=True)

        st.markdown(f"### {t('tr_quality_history')}")
        if not trace["quality_records"]:
            st.info(t("empty_no_records"))
        else:
            for q in trace["quality_records"]:
                st.write(f"attempt {q['attempt_no']} · {q['operation_code']} {format_operation_name(q['operation_name'])} · {q['result'].upper()} · {q['inspected_at']} · {q['inspector']}")
                with st.expander(t("q_inspection_items_attempt", attempt=q["attempt_no"])):
                    st.code(q["measurement"], language="json")

        st.markdown(f"### {t('tr_defect_history')}")
        if not trace["defects"]:
            st.info(t("empty_no_records"))
        else:
            for d in trace["defects"]:
                with st.expander(f"#{d['defect_id']} {d['defect_type']} [{format_status(d['status'])}] ({d['operation_code']})"):
                    st.write(f"{t('tr_field_description')}: {d['description']}")
                    st.write(f"{t('tr_field_severity')}: {d['severity']}")
                    st.write(f"{t('tr_field_created')}: {d['created_at']}")
                    st.write(f"{t('tr_field_closed')}: {d['closed_at'] or '—'}")
                    st.write(f"{t('tr_field_rework_notes')}: {d['rework_notes'] or '—'}")

        st.markdown(f"### {t('tr_download')}")
        csv_rows = [{
            "serial_number": unit["serial_number"],
            "work_order_code": wo["work_order_code"],
            "operation_code": e["operation_code"],
            "operation_name": e["operation_name"],
            "attempt_no": e["attempt_no"],
            "event_type": e["event_type"],
            "operator": e["operator"],
            "occurred_at": e["occurred_at"],
        } for e in trace["production_events"]]
        csv_df = pd.DataFrame(csv_rows, columns=["serial_number", "work_order_code", "operation_code", "operation_name", "attempt_no", "event_type", "operator", "occurred_at"])
        csv_bytes = csv_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            t("button_download_csv"),
            csv_bytes,
            file_name=f"{unit['serial_number']}_traceability.csv",
            mime="text/csv",
            on_click="ignore",
        )


def render_dashboard():
    st.subheader(t("tab_dashboard"))

    st.markdown(f"### {t('db_mes_live')}")
    st.caption(t("db_caption_demo"))

    kpis = get_mes_kpis()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(t("db_work_orders"), kpis["work_order_total"])
    c2.metric(t("db_total_units"), kpis["unit_total"])
    c3.metric(t("db_completed_units"), kpis["completed_units"])
    c4.metric(t("db_wip"), kpis["wip_units"])

    c1, c2, c3 = st.columns(3)
    c1.metric(t("db_completion_rate"), f"{kpis['completion_rate'] * 100:.1f}%")
    c2.metric(t("db_inspection_pass_rate"), f"{kpis['inspection_pass_rate'] * 100:.1f}%")
    c3.metric(t("db_defects"), kpis["defect_count"])

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.markdown(f"#### {t('db_unit_status_dist')}")
        if kpis["unit_status_counts"]:
            status_df = pd.DataFrame(list(kpis["unit_status_counts"].items()), columns=["status", "count"]).set_index("status")
            st.bar_chart(status_df)
        else:
            st.info(t("empty_no_units_data"))
    with chart_col2:
        st.markdown(f"#### {t('db_production_events')}")
        if kpis["production_events_by_operation"]:
            pe_df = pd.DataFrame(kpis["production_events_by_operation"])
            pe_df = pe_df.set_index("operation_code")[["start_count", "complete_count"]]
            st.bar_chart(pe_df)
        else:
            st.info(t("empty_no_production_events"))


def render_six_sigma_analytics():
    st.subheader(t("tab_six_sigma_analytics"))

    try:
        results = load_six_sigma_results()
    except (SixSigmaDataError, OSError, ValueError) as exc:
        st.error(t("ss_validation_failed", e=exc))
        return

    st.markdown(f"**{t('ss_synthetic_notice')}**")
    st.markdown(f"**{t('ss_validation_ok')}**")

    release = results["release"]
    spec = results["specification"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(t("ss_version"), release["version"])
    c2.metric(t("ss_release_status"), format_six_sigma_control_status(release["status"]))
    c3.metric(t("ss_ctq"), t("ss_ctq_gripping_force"))
    c4.metric(
        t("ss_specification"),
        f"{spec['lsl_n']:.0f}–{spec['usl_n']:.0f} N",
        f"{t('ss_target')} {spec['target_n']:.0f} N",
    )

    st.markdown(f"### {t('ss_process_comparison')}")
    before = results["before"]
    after = results["after"]
    comparison = pd.DataFrame(
        [
            {
                t("ss_stage"): t("ss_before"),
                t("ss_sample_size"): before["n"],
                t("ss_mean_force"): before["mean_n"],
                t("ss_standard_deviation"): before["overall_sd_n"],
                t("ss_defects"): before["defects"],
                t("ss_defect_rate"): before["defect_rate"],
                t("ss_pp"): before["pp"],
                t("ss_ppk"): before["ppk"],
            },
            {
                t("ss_stage"): t("ss_after"),
                t("ss_sample_size"): after["n"],
                t("ss_mean_force"): after["mean_n"],
                t("ss_standard_deviation"): after["overall_sd_n"],
                t("ss_defects"): after["defects"],
                t("ss_defect_rate"): after["defect_rate"],
                t("ss_pp"): after["pp"],
                t("ss_ppk"): after["ppk"],
            },
        ]
    )
    st.dataframe(
        comparison.style.format(
            {
                t("ss_mean_force"): "{:.5f}",
                t("ss_standard_deviation"): "{:.5f}",
                t("ss_defect_rate"): "{:.1%}",
                t("ss_pp"): "{:.4f}",
                t("ss_ppk"): "{:.4f}",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    improvement = results["improvement"]
    c1, c2, c3 = st.columns(3)
    c1.metric(t("ss_sd_reduction"), f"{improvement['sd_reduction_pct']:.1f}%")
    c2.metric(t("ss_ppk_change"), f"+{improvement['ppk_change']:.4f}")
    c3.metric(t("ss_centering_gain"), f"{improvement['mean_shift_toward_target_n']:.4f} N")

    st.markdown(f"### {t('ss_capability_stability')}")
    ppk_reference = results["ppk_reference_min"]
    if after["ppk"] < ppk_reference:
        st.warning(t("ss_ppk_below", ppk=f"{after['ppk']:.4f}", reference=f"{ppk_reference:.2f}"))
    else:
        st.success(t("ss_ppk_meets", ppk=f"{after['ppk']:.4f}", reference=f"{ppk_reference:.2f}"))
    control = results["after_control"]
    c1, c2, c3 = st.columns(3)
    c1.metric(t("ss_phase_i"), t("ss_phase_i_not_control"))
    c2.metric(t("ss_phase_ii"), t("ss_phase_ii_not_established"))
    c3.metric(t("ss_mr_alarms"), ", ".join(control["mr_flags"]) or "—")

    st.markdown(f"### {t('ss_msa')}")
    msa = results["msa"]
    c1, c2, c3 = st.columns(3)
    c1.metric(t("ss_grr_tolerance"), f"{msa['pct_tolerance']:.2f}%")
    c2.metric(t("ss_ndc"), msa["ndc"])
    c3.metric(t("ss_acceptance"), format_six_sigma_acceptance(msa["acceptance"]))
    if msa["acceptance"] == "CONDITIONAL":
        st.warning(t("ss_msa_note"))

    st.markdown(f"### {t('ss_root_causes')}")
    root_rows = []
    for row in results["root_causes"][:5]:
        root_rows.append(
            {
                t("ss_rank"): int(row["centering_priority_rank"]),
                t("ss_factor"): format_six_sigma_factor(row["factor_label"]),
                t("ss_category"): format_six_sigma_category(row["category"]),
                t("ss_contribution"): row["modeled_mean_shift_contribution_n"],
                t("ss_factor_sd_reduction"): row["sd_reduction_pct"] / 100.0,
                t("ss_control_action"): row["control_action"],
            }
        )
    root_df = pd.DataFrame(root_rows)
    st.dataframe(
        root_df.style.format(
            {
                t("ss_contribution"): "{:.4f}",
                t("ss_factor_sd_reduction"): "{:.1%}",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(t("ss_root_cause_note"))

    st.markdown(f"### {t('ss_control_readiness')}")
    c1, c2 = st.columns(2)
    c1.metric(t("ss_control_items"), len(results["control_plan"]))
    c2.metric(t("ss_open_items"), len(results["open_control_items"]))
    control_rows = [
        {
            t("ss_control_item"): row["control_item"],
            t("ss_frequency"): row["sample_size_frequency"],
            t("ss_owner"): row["owner_role"],
            t("ss_current_status"): format_six_sigma_control_status(row["current_status"]),
        }
        for row in results["control_plan"]
    ]
    st.dataframe(pd.DataFrame(control_rows), use_container_width=True, hide_index=True)
    st.warning(t("ss_control_note"))

    st.markdown(f"### {t('ss_charts')}")
    st.caption(t("ss_chart_note"))
    chart_paths = {path.name: path for path in results["chart_paths"]}
    charts = results["chart_manifest"]
    for start in range(0, len(charts), 2):
        columns = st.columns(2)
        for column, chart in zip(columns, charts[start:start + 2]):
            with column:
                st.markdown(f"#### {format_six_sigma_chart_title(chart)}")
                st.image(str(chart_paths[chart["chart_file"]]), use_container_width=True)

    with st.expander(t("ss_data_preview")):
        preview_columns = [
            "record_id",
            "process_stage",
            "measurement_timestamp_sgt",
            "assembly_operator_id",
            "measured_force_n",
            "target_n",
            "lsl_n",
            "usl_n",
            "spec_status",
            "data_label",
            "generation_model_version",
        ]
        st.dataframe(
            results["quality_preview"][preview_columns].head(20),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown(f"### {t('ss_downloads')}")
    c1, c2, c3, c4 = st.columns(4)
    c1.download_button(
        t("ss_download_report"),
        results["report_path"].read_bytes(),
        file_name="six_sigma_analysis_report.md",
        mime="text/markdown",
        on_click="ignore",
    )
    c2.download_button(
        t("ss_download_raw"),
        results["raw_data_path"].read_bytes(),
        file_name="quality_before_after.csv",
        mime="text/csv",
        on_click="ignore",
    )
    c3.download_button(
        t("ss_download_control"),
        results["control_plan_path"].read_bytes(),
        file_name="control_plan.csv",
        mime="text/csv",
        on_click="ignore",
    )
    c4.download_button(
        t("ss_download_validation"),
        results["validation_path"].read_bytes(),
        file_name="analysis_validation.json",
        mime="application/json",
        on_click="ignore",
    )


# ---------------------------------------------------------------------------
# Main rendering
# ---------------------------------------------------------------------------
assert set(TRANSLATIONS["en"].keys()) == set(TRANSLATIONS["zh"].keys()), "Translation key mismatch between en and zh"

if "language" not in st.session_state:
    st.session_state["language"] = "en"
if "main_section" not in st.session_state:
    st.session_state["main_section"] = "solidworks"
elif st.session_state["main_section"] not in MAIN_SECTION_KEYS:
    st.session_state["main_section"] = "solidworks"


def set_main_section(section_key):
    st.session_state["main_section"] = section_key


SECTION_LABEL_KEYS = {
    "solidworks": "section_solidworks",
    "anylogic": "section_anylogic",
    "mes_system": "section_mes_system",
    "six_sigma": "section_six_sigma",
}
with st.sidebar:
    st.markdown(f"### {t('sidebar_navigation')}")
    for section_key in MAIN_SECTION_KEYS:
        st.button(
            t(SECTION_LABEL_KEYS[section_key]),
            key=f"nav_{section_key}",
            type="primary" if st.session_state["main_section"] == section_key else "secondary",
            use_container_width=True,
            on_click=set_main_section,
            args=(section_key,),
        )
    st.markdown(
        f'<div class="sidebar-subtitle">{t("subtitle")}</div>',
        unsafe_allow_html=True,
    )

_, lang_col = st.columns([4, 1])
with lang_col:
    st.selectbox(
        t("language_label"),
        LANGUAGE_OPTIONS,
        format_func=lambda x: LANGUAGE_LABELS[x],
        key="language",
    )

flash = st.session_state.pop("_flash_message", None)
if flash:
    if flash["type"] == "success":
        st.success(flash["message"])
    elif flash["type"] == "error":
        st.error(flash["message"])
    elif flash["type"] == "warning":
        st.warning(flash["message"])
    else:
        st.info(flash["message"])

active_section = st.session_state["main_section"]

if active_section == "solidworks":
    render_solidworks_modeling()
elif active_section == "anylogic":
    render_anylogic_simulation()
elif active_section == "mes_system":
    st.header(t("mes_heading"))
    st.caption(t("mes_caption"))
    st.caption(t("mes_capability_caption"))
    tab_labels = [t(f"tab_{key}") for key in PAGE_KEYS]
    tab_dashboard, tab_create, tab_list, tab_exec, tab_quality, tab_trace = st.tabs(
        tab_labels,
        key="active_tab",
        on_change="rerun",
    )
    with tab_dashboard:
        render_dashboard()
    with tab_create:
        render_create_work_order()
    with tab_list:
        render_work_order_list()
    with tab_exec:
        render_production_execution()
    with tab_quality:
        render_quality_defects()
    with tab_trace:
        render_traceability()
elif active_section == "six_sigma":
    render_six_sigma_analytics()
