# Gas1 CSTR 1000 ms 工况扫描（并行度 8）

## 执行概况

- 模型：Gas1、CSTR 0D、1 atm 基准、400 K、N2:H2 = 1:1。
- 反应器：停留时间基准为 1 ms；扫描时同时改变停留时间。
- 脉冲：E/N 基准 50 Td，10 kHz，duty fraction 0.2（20%）。
- 电子密度：基准 `1.17e8 cm^-3`。
- 时间：每个工况固定计算到 1000 ms。
- 数值模式：`phase_local` + `positive_unbounded`，用于消除已知的 DVODE `T + H = T` 边界回退告警；这是诊断模式，不替代有界基线结果的物理收敛认证。
- 表面反应：禁用；壁面驰豫：启用；CSTR 流入/流出项：启用。
- BOLSIG：运行命令带 `--append-detailed-balance-inverses`，因此本批次仍属于截面/详细平衡诊断运行，不应作为最终生产数据发布。

扫描由 `scripts/run_gas1_condition_scan.py` 调度，外层 `ThreadPoolExecutor` 并行度为 8；每个子任务内部 `run_pulse_case.py --max-workers 1`，避免嵌套并行争抢资源。

## 扫描矩阵

这是以确认工况为中心的单因素扫描，不是全因子组合扫描：

| 参数 | 扫描值 |
|---|---|
| E/N on | 25、50、75、100 Td |
| 停留时间 | 0.1、0.3、1、3、10 ms |
| 压力 | 0.5、1、2 atm |
| 气体温度 | 300、400、500 K |
| H2 摩尔分数 | 0.25、0.5、0.75 |
| 电子密度 | `1e7`、`1.17e8`、`1e9 cm^-3` |
| 频率 | 1、10、100 kHz |
| duty fraction | 0.1、0.2、0.5（10%、20%、50%） |

共 20 个工况（含基准点）。

## 结果

输出目录：

`run_data/diagnostics/gas1_condition_scan_20260921T_parallel8/`

结果状态定义：`PASS` 表示 1000 ms manifest 存在、NH3 终值存在、DVODE 错误数为 0、`T + H = T` 告警数为 0，并且内部验证标志均为真；`FAIL` 表示至少一个条件不满足。

| 工况 | NH3(1000 ms), cm^-3 | 告警 | DVODE 错误 | 状态 |
|---|---:|---:|---:|---|
| baseline: 50 Td, 1 ms, 1 atm, 400 K, xH2=0.50, `1.17e8`, 10 kHz, 20% | 1.5448e8 | 0 | 0 | PASS |
| E/N = 25 Td | — | 0 | 1 | FAIL |
| E/N = 75 Td | — | 0 | 1 | FAIL |
| E/N = 100 Td | 1.0337e12 | 0 | 0 | PASS |
| tau = 0.1 ms | — | 0 | 1 | FAIL |
| tau = 0.3 ms | 5.0077e6 | 0 | 0 | PASS |
| tau = 3 ms | 1.9478e9 | 0 | 0 | PASS |
| tau = 10 ms | 1.8036e10 | 0 | 0 | PASS |
| P = 0.5 atm | — | 0 | 1 | FAIL |
| P = 2 atm | 9.6804e8 | 0 | 0 | PASS |
| T = 300 K | — | 0 | 1 | FAIL |
| T = 500 K | 1.2680e8 | 0 | 0 | PASS |
| xH2 = 0.25 | 2.5685e7 | 0 | 0 | PASS |
| xH2 = 0.75 | 5.0151e8 | 0 | 0 | PASS |
| `ne = 1e7 cm^-3` | 2.3155e6 | 0 | 0 | PASS |
| `ne = 1e9 cm^-3` | — | 0 | 1 | FAIL |
| f = 1 kHz | — | 0 | 1 | FAIL |
| f = 100 kHz | 1.5399e8 | 0 | 0 | PASS |
| duty = 10% | 4.3545e7 | 0 | 0 | PASS |
| duty = 50% | 8.2374e8 | 0 | 0 | PASS |

汇总：20 个工况中 13 个 PASS、7 个 FAIL。所有 PASS 工况均为 0 次 `T + H = T` 告警；FAIL 工况均在 DVODE corrector 阶段报错，典型日志为 `corrector convergence failed repeatedly`，随后 `ZDPlasKin ERROR: DVODE solver issued an error`。因此这些工况不能用空值或“0 告警”解释为已收敛。

随后对这 7 个 FAIL 点使用 `positive_radical_floor_unbounded`、`n_sub_on=240`、`n_sub_off=160` 进行了恢复计算，7/7 全部通过；详见 [失败工况恢复记录](GAS1_FAILURE_RECOVERY_20260921.md)。

## 文件与复现

- 调度器：[scripts/run_gas1_condition_scan.py](../scripts/run_gas1_condition_scan.py)
- 扫描计划：[scan_plan.json](../run_data/diagnostics/gas1_condition_scan_20260921T_parallel8/scan_plan.json)
- 汇总 JSON：[summary.json](../run_data/diagnostics/gas1_condition_scan_20260921T_parallel8/summary.json)
- 汇总 CSV：[summary.csv](../run_data/diagnostics/gas1_condition_scan_20260921T_parallel8/summary.csv)
- 每个工况的输入 YAML 位于 `configs/gas_phase/cstr/`，输出位于 `run_data/.../cases/<case_id>/`。

复现命令（项目根目录）：

```powershell
$env:PYTHONPATH='src'
python scripts/run_gas1_condition_scan.py --max-workers 8 --output-root run_data/diagnostics/gas1_condition_scan_20260921T_parallel8
```

由于输出目录采用防覆盖创建，复现时请换用新的 `--output-root`。

## 下一步建议

1. 对 7 个 FAIL 点先做局部数值稳健性扫描（更小的初始步长/最大步长、分段 ramp、降低输出跨度），区分“物理刚性”与“初始化/脉冲切换造成的求解器失败”。
2. 在每个通过点保留 bounded DVODE 与 `positive_unbounded` 的对照，报告 NH3 相对差异；当前 positive 模式只证明告警路径被绕开，不能单独证明绝对浓度已经物理收敛。
3. 完成 BOLSIG 截面数据库和详细平衡审计后，再将通过点升级为生产数据。
