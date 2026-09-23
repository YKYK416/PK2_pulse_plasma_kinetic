# Gas1 CSTR 第一阶段自适应单因素扫描（1000 ms）

## 执行结论

第一阶段共执行 60 个自适应单因素工况。初始并行度为 8；其中 51 个工况在首轮并行运行中完整结束，9 个工况在同一时间点留下了只覆盖约 0.1–0.8 ms 的部分输出，退出码属于 Windows 进程提前终止，而不是 DVODE 数值错误。对这 9 个工况使用相同数值模型串行补跑后，60/60 个工况均通过。

最终通过标准为：

- 1000 ms 结果 manifest 存在且 `return_code=0`；
- 物种、表面端点和平均反应速率验证均为真；
- `T + H = T` 告警数为 0；
- DVODE solver error 数为 0。

合并结果中 60 个工况满足上述标准，告警总数为 0，DVODE 错误总数为 0。

## 模型与数值设置

- Gas1 CSTR 0D，1 atm、400 K、N2:H2 = 1:1 为基准工况。
- 停留时间基准 1 ms；气体重组分启用 CSTR 流入/流出，电子和表面状态不进入流项。
- E/N 基准 50 Td，10 kHz，duty 20%；电子密度基准 `1.17e8 cm^-3`。
- 每个工况计算到 1000 ms。
- `solver_time_mode=phase_local`。
- 数值模式为 `positive_radical_floor_unbounded`，`n_sub_on=240`、`n_sub_off=160`。该模式用于诊断和工况筛选，不替代有界 DVODE 与截面数据库完成后的生产收敛认证。
- 表面反应关闭、壁面驰豫开启、气体加热关闭；BOLSIG 运行仍带详细平衡逆反应审计选项，因此结果应作为诊断扫描使用。

## 自适应扫描矩阵

这是围绕确认工况的单因素扫描，不是全因子组合：

| 参数 | 扫描值 |
|---|---|
| E/N on | 25、30、35、40、45、50、60、70、75、80、85、100 Td |
| 停留时间 | 0.1、0.15、0.2、0.3、0.5、0.75、1.0、1.5、2、3、5、10 ms |
| 压力 | 0.5、0.75、1.0、1.25、1.5、2 atm |
| 气体温度 | 300、325、350、375、400、425、450、500 K |
| H2 摩尔分数 | 0.25、0.35、0.40、0.45、0.50、0.55、0.65、0.75 |
| 电子密度 | `1e7`、`3e7`、`1e8`、`2e8`、`3e8`、`5e8`、`1e9 cm^-3`（另含基准 `1.17e8`） |
| 频率 | 1、2、5、10、50、100 kHz |
| duty fraction | 0.1、0.15、0.2、0.25、0.3、0.4、0.5 |

去重后的总工况数为 60（每一行包含基准点或基准轴上的一个点）。

## 重试工况与最终值

以下 9 个点在首轮并行运行中被进程级中断，随后串行补跑成功。NH3 数值为 1000 ms 末端浓度，单位 `cm^-3`。

| 工况 | NH3(1000 ms) | 告警 | DVODE 错误 | 状态 |
|---|---:|---:|---:|---|
| duty = 10% | `4.35384e7` | 0 | 0 | PASS |
| duty = 15% | `9.10527e7` | 0 | 0 | PASS |
| duty = 25% | `2.32869e8` | 0 | 0 | PASS |
| duty = 30% | `3.25459e8` | 0 | 0 | PASS |
| duty = 40% | `5.50321e8` | 0 | 0 | PASS |
| duty = 50% | `8.23649e8` | 0 | 0 | PASS |
| f = 50 kHz | `1.53988e8` | 0 | 0 | PASS |
| f = 100 kHz | `1.53966e8` | 0 | 0 | PASS |
| `ne = 1e9 cm^-3` | `6.73411e9` | 0 | 0 | PASS |

首轮已完整通过的 51 个工况中，NH3 末值范围为 `7.74` 到 `1.03331e12 cm^-3`；基准点为 `1.54444e8 cm^-3`。这些数值是筛选输出，不应直接解释为已完成的物理参数不确定度分析。

## 输出与复现

- 首轮并行输出：[gas1_adaptive_condition_scan_20260921T_parallel8](../run_data/diagnostics/gas1_adaptive_condition_scan_20260921T_parallel8/)
- 首轮计划：[scan_plan.json](../run_data/diagnostics/gas1_adaptive_condition_scan_20260921T_parallel8/scan_plan.json)
- 首轮汇总：[summary.json](../run_data/diagnostics/gas1_adaptive_condition_scan_20260921T_parallel8/summary.json)
- 9 点补跑输出：[gas1_adaptive_condition_scan_20260921T_retry_serial](../run_data/diagnostics/gas1_adaptive_condition_scan_20260921T_retry_serial/)
- 补跑汇总：[summary.json](../run_data/diagnostics/gas1_adaptive_condition_scan_20260921T_retry_serial/summary.json)
- 调度器：[run_gas1_condition_scan.py](../scripts/run_gas1_condition_scan.py)

调度器现支持 `--retry-failed`：首轮结果会保存为 `summary_initial.*`，失败点使用较稳健的诊断设置自动重跑，重试结果保存为 `summary_retry.*`，最终 `summary.*` 是按原始 case ID 合并后的状态。这样进程级中断和 DVODE 数值失败都不会再被留在最终汇总中。

首轮执行命令：

```powershell
$env:PYTHONPATH='src'
python scripts/run_gas1_condition_scan.py `
  --profile adaptive `
  --max-workers 8 `
  --retry-failed `
  --retry-max-workers 1 `
  --species-tolerance-mode positive_radical_floor_unbounded `
  --n-sub-on 240 `
  --n-sub-off 160 `
  --case-suffix='-adaptive' `
  --output-root run_data/diagnostics/gas1_adaptive_condition_scan_20260921T_parallel8
```

9 点串行补跑命令：

```powershell
$env:PYTHONPATH='src'
python scripts/run_gas1_condition_scan.py `
  --profile adaptive `
  --only duty0.1pct duty0.15pct duty0.25pct duty0.3pct duty0.4pct duty0.5pct `
           f50khz f100khz ne1.000e-09 `
  --max-workers 1 `
  --species-tolerance-mode positive_radical_floor_unbounded `
  --n-sub-on 240 `
  --n-sub-off 160 `
  --case-suffix='-adaptive-retry' `
  --output-root run_data/diagnostics/gas1_adaptive_condition_scan_20260921T_retry_serial
```

## 解释边界与下一步

本批次证明的是：在当前 CSTR、脉冲和诊断数值模式下，第一阶段 60 个单因素点均能完成 1000 ms 积分，并且没有 `T + H = T` 或 DVODE 错误。它没有证明 `positive_radical_floor_unbounded` 与有界模型的绝对浓度完全一致，也没有替代 BOLSIG 截面数据库的最终审计。

下一步应优先把 NH3 响应变化最大的区域（E/N 25–60 Td、停留时间 0.1–3 ms、电子密度 `1e7–1e9 cm^-3`）转换为局部二维或小型全因子扫描，并对候选点加入 bounded/positive 两种数值模式的相对差异检查。
