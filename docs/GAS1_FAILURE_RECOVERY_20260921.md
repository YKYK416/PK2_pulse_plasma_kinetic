# Gas1 CSTR 失败工况恢复记录

## 目的

对 1000 ms 工况扫描中出现 DVODE corrector 失败的 7 个点进行恢复计算。原始失败日志不是 `T + H = T` roundoff 告警，而是：

```text
corrector convergence failed repeatedly
ZDPlasKin ERROR: DVODE solver issued an error
```

## 数值修复

新增 `positive_radical_floor_unbounded` 模式，组合了两项局部数值处理：

1. 试探态和接受态保持非负投影，避免低密度物种的负值进入反应速率计算；
2. 对激发态、自由基、离子和表面状态使用分物种绝对容差 `100 × ATOL`，而 N2、H2、NH3、电子和气体温度继续使用标量 `ATOL`。

恢复计算同时将脉冲相位子步数由基线 `48/32` 提高为：

```text
n_sub_on  = 240
n_sub_off = 160
```

这没有修改反应机理、壁面驰豫、CSTR 流项、表面反应开关或电子密度模型。

## 恢复结果

输出目录：

`run_data/diagnostics/gas1_failure_recovery_20260921T_parallel8/`

外层并行度为 8，7 个失败工况全部通过 1000 ms 验证：

| 工况 | NH3(1000 ms), cm^-3 | `T + H` 告警 | DVODE 错误 | species | rates | 状态 |
|---|---:|---:|---:|---|---|---|
| E/N = 25 Td | 7.7441 | 0 | 0 | PASS | PASS | PASS |
| E/N = 75 Td | 1.0950e11 | 0 | 0 | PASS | PASS | PASS |
| f = 1 kHz | 1.7803e8 | 0 | 0 | PASS | PASS | PASS |
| ne = 1e9 cm^-3 | 6.7341e9 | 0 | 0 | PASS | PASS | PASS |
| P = 0.5 atm | 1.5906e7 | 0 | 0 | PASS | PASS | PASS |
| T = 300 K | 4.5402e8 | 0 | 0 | PASS | PASS | PASS |
| tau = 0.1 ms | 1.3485e5 | 0 | 0 | PASS | PASS | PASS |

所有恢复结果的 `species_endpoints.csv` 均无负采样值；最小值为 0，负值计数为 0。

## 复现

```powershell
$env:PYTHONPATH='src'
python scripts/run_gas1_condition_scan.py `
  --max-workers 8 `
  --species-tolerance-mode positive_radical_floor_unbounded `
  --n-sub-on 240 `
  --n-sub-off 160 `
  --case-suffix='-recovery' `
  --only en25td en75td f1khz ne1-000e-09 p0-5atm t300k tau0-1ms `
  --output-root run_data/diagnostics/gas1_failure_recovery_20260921T_parallel8
```

汇总文件：

- `run_data/diagnostics/gas1_failure_recovery_20260921T_parallel8/summary.json`
- `run_data/diagnostics/gas1_failure_recovery_20260921T_parallel8/summary.csv`
- `run_data/diagnostics/gas1_failure_recovery_20260921T_parallel8/scan_plan.json`

## 使用边界

该模式解决的是积分器在低密度正值边界附近的数值失败，不等于已经完成物理模型的最终收敛认证。当前运行仍使用 `positive_radical_floor_unbounded` 诊断模式，并保留 `--append-detailed-balance-inverses` 的 BOLSIG 截面审计设置；在发布生产数据前，仍需用批准的截面数据库、bounded DVODE 对照和容差/子步数收敛测试复核 NH3 绝对浓度。
