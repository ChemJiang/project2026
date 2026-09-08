# 电动夹爪六西格玛合成数据 — EOL-EG-V5

> **版本声明：EOL-EG-V3 已正式退役；EOL-EG-V4 已被取代；EOL-EG-V5 是当前唯一可用于分析和展示的版本。**

**Synthetic Data：全部记录、设备、人员、时间、工艺参数、改进措施及关系均为合成演示，不是实测数据、真实 MES 导出或 SolidWorks / AnyLogic 计算结果。**

本版包含 200 条 Before、200 条 After、400 条正式合并数据，以及 10 件 × 3 名测量者 × 2 次重复的 60 条 MSA 数据。After 的改善是预先写入可观察工艺因素的合成情景，不能作为实际设备改善证据。分析发布同时包含根因证据表、10 项 Control Plan、完整 DMAIC 报告和 12 张图。

## 本次关键决定

采用“未观测残差 SD 保持不变”的方案：

- Before `part_residual_sd_n = 0.28 N`
- After `part_residual_sd_n = 0.28 N`
- 未观测残差不再被列为改善措施，也不用于人为制造 After 方差下降。
- After 的变化只通过 CSV 中可观察、可解释的电流、对中误差、齿轮回程间隙、夹垫厚度和紧固扭矩参数实现。

这样比给隐藏残差直接降幅更容易审计。真实项目若希望残差下降，必须增加可测量的新因素并取得实际数据后再建模。

## CTQ 与规格

- CTQ：Gripping Force（夹爪抓取力）
- Target：12.00 N
- LSL：10.00 N
- USL：14.00 N
- 合格规则：`LSL <= measured_force_n <= USL`
- 力定义：假设测试块上的单个压缩力传感器在保持 1 s 后读取一次；不是左右夹爪力相加，也不是多次平均

规格、测试块尺寸、闭合速度和接触位置都是演示假设，未经过实物验证。

## 能力指数公式修正

能力指数现在固定使用标准 6σ 定义：

```text
Pp  = (USL - LSL) / (6 × overall SD)
Ppk = min(mean - LSL, USL - mean) / (3 × overall SD)

Cp  = (USL - LSL) / (6 × within SD)
Cpk = min(mean - LSL, USL - mean) / (3 × within SD)

within SD = mean moving range / d2
```

`control_sigma_multiplier` 只用于 I 图控制限：`mean ± multiplier × within SD`。它不再参与 Pp/Ppk/Cp/Cpk。配置中的 `capability_sigma_multiplier` 必须等于 3.0；若被改为其他值，配置验证会在生成数据前失败。

## 配置验证

`validate_config()` 在任何随机抽样或文件写入之前执行。本配置通过 147 项条件检查，覆盖：

- `LSL < Target < USL`、规格边界规则和数据标签；
- 测量分辨率与记录小数位兼容；
- 种子完整、整数且互不重复；
- 日期、时区、班次、样本量、人员和 ID 唯一性；
- 5 个工艺因素的 SD、边界和精度；
- MSA 分位点、交叉设计、重复次数，以及 MSA 与生产抽样一致的 UTC 偏移；
- I-MR 常数、能力指数 3σ/6σ 定义、Gage R&R 三档容差阈值（pass/conditional/unacceptable）与 ndc 下限、Ppk 参考值；
- Before 与 After 的未观测残差 SD 必须相同。

`validation_report.json` 还验证 400 条主数据、60 条 MSA、无空白主字段、无边界堆积、ID/时间戳唯一性、MSA 外键、数据字典覆盖和全部 `Synthetic Data` / V5 标签，并记录四份 CSV、配置和生成脚本的 SHA-256。

## After 改进情景 IMP-EG-01

| 改进方向 | Before 参数 | After 参数 | 合成情景中的可解释措施 |
|---|---|---|---|
| 电机电流 | 件间 SD 0.22 A；批次漂移 SD 0.025 A；夜班 -0.025 A；人员偏差跨度 0.080 A | 件间 SD 0.12 A；批次漂移 SD 0.012 A；无夜班偏移；人员偏差跨度 0.020 A | 闭环电流设定值、偏差报警和班次标准化 |
| 夹爪对中 | 人员均值 0.19/0.27/0.35 mm；SD 0.125 mm；夜班 +0.035 mm | 人员均值 0.15/0.16/0.17 mm；SD 0.060 mm；夜班 +0.005 mm | 定位防错夹具和对中确认 |
| 齿轮回程间隙 | 批次均值 0.76°；批次间 SD 0.10°；件间 SD 0.26° | 批次均值 0.45°；批次间 SD 0.04°；件间 SD 0.12° | 来料筛检和间隙控制 |
| 夹垫厚度 | 批次间 SD 0.045 mm；件间 SD 0.095 mm | 批次间 SD 0.020 mm；件间 SD 0.050 mm | 来料厚度分选和批次控制 |
| 紧固扭矩 | 人员均值 2.32–2.48 N·m；SD 0.22 N·m | 人员均值 2.49–2.50 N·m；SD 0.080 N·m | 程序控制电动扭矩工具 |
| 未观测件间差异 | SD 0.28 N | SD 0.28 N | **不作为改善因素；保持不变** |

Before 与 After 使用同一设备、协议、0.01 N 分辨率、测量重复性 SD 0.042 N 和零点残差 SD 0.040 N，因此 After 的改善没有通过更换测量精度制造出来。

## V5 结果

| 指标 | Before | After | 变化 |
|---|---:|---:|---:|
| 样本数 | 200 | 200 | — |
| 平均值 | 11.66295 N | 12.00560 N | 距目标缩短 0.33145 N |
| 总体样本 SD | 0.76935 N | 0.51403 N | 下降 33.19% |
| 超规格数 | 3 | 0 | 样本不良率下降 1.5 个百分点 |
| Pp | 0.8665 | 1.2969 | +0.4304 |
| Ppk | 0.7205 | 1.2933 | +0.5728 |
| MR 法暂算 Cp | 0.8601 | 1.2252 | +0.3651 |
| MR 法暂算 Cpk | 0.7151 | 1.2218 | +0.5066 |

After 的 Ppk 为 1.2933，仍低于常见的 1.33 参考线；不能写成“能力已达 1.33”。Before 的 MR 图在 `BL-049` 报警，After 的 MR 图在 `AF-118` 和 `AF-158` 报警。因此目前不能宣称过程已经稳定，MR 法 Cp/Cpk 只能作为暂算值。

MSA 结果：Gage R&R SD 约 0.07704 N，%Tolerance 约 11.56%，%Study Variation 约 9.87%，`ndc=14`。按三档判定（≤10% PASS、10–30% CONDITIONAL、>30% 或 ndc<5 UNACCEPTABLE），当前判定为 CONDITIONAL，不得简单描述为”测量系统完全合格”。

## 根因分析结论

根因分析同时使用生成模型系数、Before/After 因素均值与 SD、Before 五因素 OLS 和均值变化分解。Before 回归 `R²=0.880`；五个可观察因素解释 0.3308 N 的模型均值变化，而实际样本均值变化为 0.3426 N。

按模型均值变化贡献排序：夹爪对中误差 0.1581 N、齿轮回程间隙 0.1036 N、电机电流 0.0439 N、紧固扭矩 0.0230 N、夹垫厚度 0.0021 N。这个排序只回答“什么推动均值回到目标附近”；Before 波动的多元回归则显示电机电流是最大的已记录变化驱动（标准化 beta 约 0.866）。夹垫厚度对本次居中变化贡献很小，但其离散程度下降。以上只是在合成模型内确认的驱动关系，不是实际设备根因确认。

## Control 阶段状态

`control_plan.csv` 覆盖 CTQ 全检、五个工艺输入、传感器零点、I-MR、过程能力和 Gage R&R。每项都包含方法、频次、行动界限依据、当前证据、责任角色、反应计划和记录位置。

Control 阶段尚未关闭：After 样本 0/200 超规格仅代表当前样本结果；`AF-118`、`AF-158` 仍触发 MR 报警，因此 Phase I 未受控、Phase II 前瞻监控限不可建立（NOT_ESTABLISHED）；Ppk 1.293 低于 1.33 参考线且因 Phase I 未受控而标记为 PROVISIONAL；Gage R&R 11.56% tolerance 属于有条件使用（CONDITIONAL）。五个工艺因素的统计窗口只是 Phase I 描述性窗口（均值 ±3 SD 并受合成边界约束），不是控制计划的行动限、也不能冒充工程公差。

## 文件

- `quality_before_after.csv`：正式主数据，400 条；Before/After 各 200 条。
- `quality_baseline.csv`：主表前 200 条的精确 Before 子集。
- `quality_msa.csv`：60 条完整交叉 MSA 数据。
- `six_sigma_data_dictionary.csv`：三份 CSV 的全部字段定义。
- `generation_config.json`：V5 参数及版本状态。
- `generate_quality_data.py`：生成、能力计算、MSA 和验证逻辑。
- `validation_report.json`：配置验证、结构校验、指标和数据 SHA-256。
- `analyze_quality_data.py`：完整 V5 图表再生脚本。
- `build_package.py`：按明确白名单重建 ZIP，排除旧版和临时文件。
- `charts/`：12 张重新制作的分析图表。
- `chart_manifest.csv`：图表、来源和解释边界清单。
- `analysis_validation.json`：图表输入检查、文件数和 SHA-256。
- `root_cause_analysis.csv`：五个可观察因素的模型系数、Before/After 分布、OLS 结果、均值变化贡献和控制措施。
- `control_plan.csv`：10 项控制特性、频次、行动界限、责任角色、反应计划和当前状态。
- `six_sigma_analysis_report.md`：Define、Measure、Analyze、Improve、Control 的完整再生报告。
- `VERSION_STATUS.md`：V3 退役、V4 被取代、V5 当前的正式声明。

## 图表重制范围

所有旧版分析图表均应从最终页面移除，改用以下 V5 图表：

1. 抓取力生产顺序图；
2. Before/After 分布图；
3. 箱线图；
4. Before I-MR；
5. After I-MR；
6. Pp/Ppk/Cp/Cpk 对比；
7. 五个可观察工艺因素分布；
8. MSA 方差分量；
9. MSA 零件 × 测量者剖面；
10. 改进摘要；
11. 根因均值变化贡献图；
12. Control 阶段就绪状态图。

每张图均显示 `Synthetic Data` 和 `EOL-EG-V5`。图表脚本会先核对四份 CSV、配置和生成脚本的 SHA-256，再从 CSV 独立重算能力指数、改善指标和 Gage R&R，并与 `validation_report.json` 比对。图 08/12 的解释文字还会执行独立分支测试、内存清单行核对及暂存 CSV 回读核对；结果记录在 `analysis_validation.json` 的 `generalization_checks`。12 张图、根因表、Control Plan、DMAIC 报告、图表清单和分析验证文件全部通过后才作为一个事务提交；失败时保留上一套正式产物。

数据生成同样采用五文件事务：四份 CSV 与 `validation_report.json` 先写入同盘暂存区，结构审计全部通过后才整体替换；任一替换失败都会回滚旧文件。打包脚本会再次验证生成源、CSV、重算指标、分析源、全部图表哈希及完整的 `generalization_checks`，旧版根目录文件存在时拒绝打包。

## 复现

需要 Python 3.9+；数据生成仅依赖标准库。图表生成需要 pandas、numpy 和 matplotlib。

```bash
python generate_quality_data.py --output .
python generate_quality_data.py --check --output .
python analyze_quality_data.py --input .
python build_package.py --input .
```

`structural_status = PASS` 和 `all_chart_files_exist = true` 只证明程序定义的结构、算术和文件完整性通过，不代表真实过程稳定、真实 MSA 通过或措施已验证。

跨环境复现：CSV 浮点统一舍入到 12 位小数、Markdown 固定 `newline="\n"`，因此 `root_cause_analysis.csv`、`control_plan.csv`、`chart_manifest.csv` 与报告可字节复现。图表 PNG 的字节在不同 Python/NumPy/Matplotlib 版本下不保证一致，跨环境以 `chart_manifest.csv` 做语义验证，运行环境版本记录在 `analysis_validation.json` 的 `environment` 字段。
