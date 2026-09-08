# Six Sigma Analysis Report — EOL-EG-V5

> **Synthetic Data.** This report describes a reproducible scenario, not measured equipment performance or verified physical causation.

## Executive summary

- CTQ: gripping force; Target 12.00 N; LSL 10.00 N; USL 14.00 N.
- Before: mean 11.66295 N, SD 0.76935 N, Ppk 0.7205, 3 observed defects in 200 units.
- After: mean 12.00560 N, SD 0.51403 N, Ppk 1.2933, 0 observed defects in 200 units.
- The After sample is better centered and narrower; Ppk 1.2933 is below the 1.33 reference; MR alarms at AF-118, AF-158; Phase I is not in control, so Phase II limits are not established.
- Gage R&R is 11.56% of tolerance with ndc=14; classification CONDITIONAL (conditional, not unconditional acceptance).

## DMAIC route

### Define

The project problem is low and variable EOL gripping force in the synthetic Before condition. The customer-facing demonstration requirement is 10–14 N inclusive around a 12 N target.

### Measure

The dataset contains independent cohorts of 200 Before and 200 After units plus a balanced 10-part × 3-appraiser × 2-replicate MSA. All identities, timestamps and measurements are synthetic. Capability uses the standard 6-sigma definition; MR-based Cp/Cpk remain provisional until stability is accepted. Control limits shown are Phase I retrospective trial limits; Phase II prospective limits require a demonstrated in-control Phase I.

### Analyze — root-cause evidence

The root-cause route combines: (1) generator response coefficients, (2) observed Before/After factor means and SDs, (3) a five-factor OLS model on the Before sample, and (4) decomposition of the modeled mean shift. The Before regression R² is 0.880. The five recorded factors explain 0.3308 N of the 0.3426 N observed mean shift; the remainder reflects the unchanged random residual and measurement terms in this realization.

| Rank | Factor | Category | Modeled mean-shift contribution (N) | SD reduction | Before standardized beta |
|---:|---|---|---:|---:|---:|
| 1 | Jaw alignment error | Method | 0.1581 | 47.1% | -0.200 |
| 2 | Gear backlash | Machine | 0.1036 | 52.1% | -0.134 |
| 3 | Motor current | Machine | 0.0440 | 43.1% | 0.866 |
| 4 | Fastener torque | Method | 0.0230 | 64.3% | 0.058 |
| 5 | Pad thickness | Material | 0.0021 | 47.0% | 0.119 |

The primary modeled centering drivers are Jaw alignment error, Gear backlash and Motor current. This is not the same as the baseline-variation ranking: motor current has the largest absolute Before standardized beta (0.866) and is the dominant recorded driver of Before force variation in the fitted model. Pad thickness contributes little to centering in this realization but its spread is reduced. These relationships hold only inside the declared synthetic model; real root-cause confirmation requires physical measurement, stratification and DOE or controlled trials.

The remaining candidate causes — People, Measurement, Environment — were assessed but have no encoded effect in the synthetic response model, so no synthetic evidence supports or refutes them; each requires real data before any causal claim.

### Improve

IMP-EG-01 encodes closed-loop motor-current control, alignment poka-yoke, backlash and pad incoming inspection, and program-controlled torque. The hidden part residual remains 0.28 N in both stages, so it is not presented as an improvement lever.

### Control

| Control item | Frequency | Approved action limit | Current status | Owner role |
|---|---|---|---|---|
| Gripping force CTQ | Every finished unit | 10.00 to 14.00 N inclusive; target 12.00 N | PASS_SAMPLE_ONLY | Quality Inspector |
| Motor current | Every cycle | TBD | PROVISIONAL | Process Engineer |
| Jaw alignment error | First-off and every 20 units | TBD | PROVISIONAL | Production Supervisor |
| Gear backlash | 5 units per incoming lot | TBD | PROVISIONAL | Incoming Quality |
| Pad thickness | 5 units per incoming lot | TBD | PROVISIONAL | Incoming Quality |
| Fastener torque | Every assembly | TBD | PROVISIONAL | Production Supervisor |
| Sensor zero offset | Before each shift and after fixture/sensor disturbance | TBD | PROVISIONAL | Quality Technician |
| I-MR stability | Phase I: this 200-unit window; Phase II (once established): review every shift | TBD | ACTION_REQUIRED | Quality Engineer |
| Process capability | Monthly and after material/tool/process change; minimum 200 units | TBD | PROVISIONAL | Quality Engineer |
| Gage R&R | Quarterly and after device/fixture/appraiser/protocol change | TBD | CONDITIONAL | Measurement System Owner |

Detailed methods, limit bases, reaction plans and records are provided in `control_plan.csv`. Statistical windows derived from the After sample are provisional and must not be presented as engineering tolerances.

## Release decision

The synthetic improvement scenario is suitable for portfolio demonstration, but the Control phase remains open. Required next evidence is: resolve the Phase I MR alarms and establish Phase II control limits, establish real engineering input tolerances, improve or justify the CONDITIONAL MSA result, and then repeat capability analysis on a stable real process.
