# Gas1 下一阶段执行记录（2026-09-22）

## 执行范围

本阶段按“数值认证 → 三因素响应面 → 截面审计 → 表面化学筛选 → 生产时间扫描”的顺序执行。所有 Gas1 结果均为 CSTR 0D、1 atm、400 K、N2:H2=1:1、τ=1 ms 基准附近的诊断结果；表面化学单独使用 Surf1 机制。并行扫描使用 8 个 worker，单个 native case 内部使用 1 个 worker，避免共享 build 目录。

## 1. 六锚点数值认证

输出：`run_data/diagnostics/gas1_numerical_certification_20260922T_parallel8_shortpath`

- 6 个锚点：`(45 Td, 0.3 ms)`、基准 `(50 Td, 1 ms)`、`49 Td`、`53 Td`、`60 Td`、`(65 Td, 2 ms)`。
- 数值模式：`scalar`（有界对照）、`positive_unbounded`、`positive_radical_floor_unbounded`。
- 脉冲子步：`120/80`、`240/160`、`480/320`。
- 共 54 个 case；35 个通过全部质量门，19 个未通过均来自有界 `scalar` 的 DVODE 告警或粗子步高 E/N 对照。
- PRF 模式的 240/160 与 480/320 最大相对差为 `5.93e-4`，通过 5% 子步收敛阈值。
- 有界 `scalar` 与 PRF 240/160 最大相对差为 `11.14%`，未通过 5% 模式一致性阈值。因此当前不能把有界浓度直接当作生产基准。
- 通过的生产候选数值设置：`phase_local + positive_radical_floor_unbounded + n_sub_on=240 + n_sub_off=160`；高 E/N 点至少保留 480/320 做抽查。

比较明细见 `certification.json` 和 `comparisons.json`。

## 2. E/N–τ–ne 响应面

输出：`run_data/diagnostics/gas1_surface3d_scan_20260922T_parallel8`

27 个点（E/N=`49/53/57 Td`，τ=`0.5/1/1.5 ms`，ne=`1e8/1.17e8/2e8 cm^-3`）全部通过，DVODE warning/error 均为 0。趋势仍由 E/N 与 residence time 主导，ne 提升提供第二层增益；例如基准 ne 下，E/N=49 Td 的 τ=0.5/1/1.5 ms 约为 `1.49e7/9.99e7/2.74e8 cm^-3`。

## 3. BOLSIG 截面审计

输出：`run_data/diagnostics/gas1_bolsig_audit_20260922T`

- 原始 `SigloDataBase-LXCat-04Jun2013.txt` 审计不接受：缺少 16 个逆过程块，但存在对应正向记录；另有 N2 `a\`1` 与 H2 `v1–v3` 的大小写/撇号别名。
- 生成的 case-local `bolsigdb.dat` 通过审计，追加 16 个详细平衡逆过程；`forward_records_modified=false`，正向激发记录保持原样。
- 该独立诊断脚本使用 closed-0D driver，链接 CSTR case 时缺少 `zdplaskin_set_cstr_flow_`，所以 linker smoke test 不适用于 CSTR。真正的 CSTR 编译和求解已由 27 点响应面与认证矩阵逐 case 验证通过。

## 4. Surf1 表面化学筛选

输出：`run_data/diagnostics/gas1_surface_chemistry_scan_20260922T_parallel8`

- 25 个一因素点中 24 个通过；Surf1 基准 NH3=`1.55668e8 cm^-3`，Surf/HSurf 末态覆盖度约为 `3.43e-6/0.999755`。
- 失败点为 ne=`1e9 cm^-3`：约 `4.4 µs` 处 DVODE corrector failure，随后 native solver 等待 stdin，导致 EOF；不是表面守恒错误。
- 已用 PRF、`n_sub_on/off=240/160`、`MXSTEP=2,000,000` 单点恢复：输出 `run_data/diagnostics/gas1_surface_chemistry_recovery_ne1e9_20260922T`，1000 ms 通过全部质量门，NH3=`6.76782e9 cm^-3`。

## 5. 基准生产时间扫描

配置：`configs/gas_phase/cstr/gas1-cstr0d-production-prf.yaml`；输出：`run_data/diagnostics/gas1_production_prf_baseline_20260922T`。

1/2/5/10 s 四个 horizon 均通过，DVODE warning/error 全部为 0。NH3 末态分别为 `1.54443786e8`、`1.54445796e8`、`1.54446827e8`、`1.54445262e8 cm^-3`。10 s 最后 100 个输出周期的 NH3 均值为 `1.54434859e8 cm^-3`，峰峰值 `2.07678e4 cm^-3`，相对峰峰值 `1.34e-4`，已进入稳定平台。

## 6. 失败案例恢复

输出：`run_data/diagnostics/gas1_failure_recovery_20260923T`

- 认证批次的 19 个失败记录全部恢复：18 个 bounded `scalar` case 改用同锚点、同子步的 PRF case，另 1 个高 E/N `positive_unbounded` 粗步 case 改用 PRF 120/80。
- Surf1 的 ne=`1e9 cm^-3` 失败点由独立高刚性恢复 case 解决，使用 PRF 240/160 和 `MXSTEP=2,000,000`。
- 恢复记录总数 20，已恢复 20，未解决 0；明细见 `recovery.json`、`recovery.csv` 和 `recovery.md`。
- `bounded_mode_fixed_count=0`：bounded scalar 本身仍会产生 DVODE 告警，恢复含义是找到稳定的诊断数值路径，不是证明 bounded 与 PRF 的绝对浓度一致。

## 结论与限制

当前可以把 PRF 240/160 作为工况筛选和长时间积分的稳定诊断设置；但由于 bounded 与 PRF 的绝对浓度仍有约 11% 差异，结果还不能称为最终物理收敛。下一步应固定接受的截面数据库版本、解决原始数据库逆过程缺口，并对高 E/N/Surf1 恢复点提取末 100 周期的均值、峰谷和相位占比，再决定生产数据发布标准。
