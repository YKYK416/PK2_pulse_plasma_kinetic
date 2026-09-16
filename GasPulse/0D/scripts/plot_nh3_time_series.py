"""Plot NH3 concentration from the baseline closed-0D square-wave calculation."""
from __future__ import annotations

import csv
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


CASE_DIR = Path(
    r"F:\Codex\PK2_pulse\GasPulse\0D"
    r"\squarewave_T300K_N2-0p1_H2-0p9_EN140Td_f10kHz_d50"
)
SERIES_PATH = CASE_DIR / "build" / "results" / "pulse_series_baseline.csv"
OUTPUT_PATH = CASE_DIR / "analysis" / "nh3_concentration_vs_time.png"


def parse_float(value: str) -> float:
    """Accept legacy ZDPlasKin exponents that omit the E character."""
    normalized = re.sub(
        r"^([+-]?(?:\d+\.?\d*|\.\d+))([+-]\d{2,3})$", r"\1E\2", value.strip()
    )
    return float(normalized)


def load_data(path: Path) -> tuple[list[float], list[int], list[float]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return (
        [parse_float(row["time_s"]) * 1.0e3 for row in rows],
        [int(row["phase"]) for row in rows],
        [parse_float(row["NH3"]) for row in rows],
    )


def shade_phases(axes: list[plt.Axes], time_ms: list[float], phase: list[int]) -> None:
    for index in range(1, len(time_ms)):
        color = "#d9f0d3" if phase[index] == 1 else "#f0f0f0"
        for axis in axes:
            axis.axvspan(time_ms[index - 1], time_ms[index], color=color, alpha=0.65, linewidth=0)


def main() -> None:
    if not SERIES_PATH.is_file():
        raise FileNotFoundError(f"Missing time-series result: {SERIES_PATH}")
    time_ms, phase, nh3 = load_data(SERIES_PATH)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 1, figsize=(8.3, 7.1), sharex=True, constrained_layout=True)
    shade_phases(list(axes), time_ms, phase)
    on = [idx for idx, value in enumerate(phase) if value == 1]
    off = [idx for idx, value in enumerate(phase) if value == 2]

    axes[0].plot(time_ms, nh3, color="#1f4e79", linewidth=1.8, zorder=2)
    axes[0].scatter([time_ms[i] for i in on], [nh3[i] for i in on], marker="o", s=28,
                    color="#1b7837", label="on endpoint", zorder=3)
    axes[0].scatter([time_ms[i] for i in off], [nh3[i] for i in off], marker="s", s=24,
                    color="#d95f02", label="off endpoint", zorder=3)
    axes[0].set_ylabel(r"[NH$_3$] (cm$^{-3}$)")
    axes[0].set_title("Closed 0D Hong gas-phase square-wave test: NH$_3$ time series")
    axes[0].grid(True, alpha=0.3)
    handles, labels = axes[0].get_legend_handles_labels()
    handles.extend([
        Patch(facecolor="#d9f0d3", alpha=0.65, label="on phase: E/N = 140 Td"),
        Patch(facecolor="#f0f0f0", alpha=0.65, label="off phase: E/N = 0 Td"),
    ])
    axes[0].legend(handles=handles, loc="upper left", frameon=True)

    positive = [(time, value) for time, value in zip(time_ms, nh3) if value > 0.0]
    axes[1].semilogy([item[0] for item in positive], [item[1] for item in positive],
                     color="#1f4e79", linewidth=1.8, zorder=2)
    axes[1].scatter([time_ms[i] for i in on], [nh3[i] for i in on], marker="o", s=28,
                    color="#1b7837", zorder=3)
    axes[1].scatter([time_ms[i] for i in off], [nh3[i] for i in off], marker="s", s=24,
                    color="#d95f02", zorder=3)
    axes[1].set_xlabel("Time (ms)")
    axes[1].set_ylabel(r"[NH$_3$] (cm$^{-3}$, log scale)")
    axes[1].grid(True, which="both", alpha=0.3)
    axes[1].set_xlim(time_ms[0], time_ms[-1])

    fig.savefig(OUTPUT_PATH, dpi=240, bbox_inches="tight", facecolor="white")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
