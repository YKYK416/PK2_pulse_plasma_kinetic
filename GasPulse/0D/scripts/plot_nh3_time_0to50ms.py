"""Plot accepted NH3 endpoint trajectories through 50 ms for the square-wave case."""
from __future__ import annotations

import csv
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


CASE_DIR = Path(
    r"F:\Codex\PK2_pulse\GasPulse\0D"
    r"\squarewave_T300K_N2-0p1_H2-0p9_EN140Td_f10kHz_d50"
)
BASELINE_1MS = CASE_DIR / "build" / "results" / "pulse_series_baseline.csv"
RESCUE_10MS = CASE_DIR / "time_scan_rescue_20260912" / "10ms" / "attempt_02" / "results" / "pulse_series_rescue_t10ms.csv"
RESCUE_50MS = CASE_DIR / "time_scan_rescue_20260912" / "50ms" / "attempt_02" / "results" / "pulse_series_rescue_t50ms.csv"
OUTPUT_PATH = CASE_DIR / "analysis" / "nh3_concentration_vs_time_0to50ms.png"


def parse_float(value: str) -> float:
    normalized = re.sub(
        r"^([+-]?(?:\d+\.?\d*|\.\d+))([+-]\d{2,3})$", r"\1E\2", value.strip()
    )
    return float(normalized)


def load_endpoints(path: Path) -> tuple[list[float], list[float], list[int]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return (
        [parse_float(row["time_s"]) * 1.0e3 for row in rows],
        [parse_float(row["NH3"]) for row in rows],
        [int(row["phase"]) for row in rows],
    )


def select_phase(time_ms: list[float], nh3: list[float], phase: list[int], wanted: int) -> tuple[list[float], list[float]]:
    selected = [(time, value) for time, value, item_phase in zip(time_ms, nh3, phase) if item_phase == wanted]
    return [item[0] for item in selected], [item[1] for item in selected]


def main() -> None:
    required = (BASELINE_1MS, RESCUE_10MS, RESCUE_50MS)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing accepted input data: " + "; ".join(missing))

    t50, nh3_50, phase50 = load_endpoints(RESCUE_50MS)
    t10, nh3_10, phase10 = load_endpoints(RESCUE_10MS)
    t1, nh3_1, phase1 = load_endpoints(BASELINE_1MS)
    t50_off, nh3_50_off = select_phase(t50, nh3_50, phase50, 2)
    t10_off, nh3_10_off = select_phase(t10, nh3_10, phase10, 2)
    t1_off, nh3_1_off = select_phase(t1, nh3_1, phase1, 2)

    if abs(t50_off[-1] - 50.0) > 1.0e-9:
        raise RuntimeError("The 50 ms input does not reach its requested horizon")
    if abs(nh3_50_off[-1] - 1.02479e15) / 1.02479e15 > 1.0e-6:
        raise RuntimeError("Unexpected 50 ms NH3 endpoint")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(8.5, 7.3), sharex=True, constrained_layout=True)
    for axis in axes:
        axis.plot(t50_off, nh3_50_off, color="#1f4e79", linewidth=1.8,
                  label="50 ms rescue trajectory (off-phase endpoints)")
        axis.scatter(t10_off, nh3_10_off, marker="o", s=11, color="#1b7837", alpha=0.8,
                     label="10 ms rescue endpoints")
        axis.scatter(t1_off, nh3_1_off, marker="s", s=28, color="#d95f02", zorder=3,
                     label="1 ms baseline endpoints")
        axis.grid(True, which="both", alpha=0.3)

    axes[0].set_title("Closed 0D Hong gas-phase square-wave: NH$_3$ accumulation")
    axes[0].set_ylabel(r"[NH$_3$] (cm$^{-3}$)")
    axes[0].legend(loc="upper left", frameon=True)
    axes[0].annotate(r"50 ms: $1.025\times10^{15}$ cm$^{-3}$", xy=(t50_off[-1], nh3_50_off[-1]),
                     xytext=(34, 8.4e14), arrowprops={"arrowstyle": "->", "color": "#1f4e79"},
                     color="#1f4e79")

    positive = [(time, value) for time, value in zip(t50_off, nh3_50_off) if value > 0.0]
    axes[1].cla()
    axes[1].semilogy([item[0] for item in positive], [item[1] for item in positive], color="#1f4e79", linewidth=1.8)
    axes[1].semilogy(t10_off, nh3_10_off, "o", markersize=3.2, color="#1b7837", alpha=0.8)
    axes[1].semilogy(t1_off, nh3_1_off, "s", markersize=5.5, color="#d95f02")
    axes[1].set_xlabel("Reaction time (ms)")
    axes[1].set_ylabel(r"[NH$_3$] (cm$^{-3}$, log scale)")
    axes[1].set_xlim(0.0, 50.0)
    axes[1].grid(True, which="both", alpha=0.3)

    fig.savefig(OUTPUT_PATH, dpi=240, bbox_inches="tight", facecolor="white")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
