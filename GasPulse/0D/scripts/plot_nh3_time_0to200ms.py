"""Plot the validated 200 ms NH3 endpoint trajectory for the square-wave case."""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


CASE_DIR = Path(
    r"F:\Codex\PK2_pulse\GasPulse\0D"
    r"\squarewave_T300K_N2-0p1_H2-0p9_EN140Td_f10kHz_d50"
)
SERIES_PATH = (
    CASE_DIR / "time_scan_rescue_20260912" / "200ms" / "attempt_02" / "results"
    / "pulse_series_rescue_t200ms.csv"
)
OUTPUT_PATH = CASE_DIR / "analysis" / "nh3_concentration_vs_time_0to200ms.png"
EXPECTED_FINAL_NH3 = 2.77599e15


def parse_float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def load_off_phase_endpoints(path: Path) -> tuple[list[float], list[float]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = [row for row in rows if int(row["phase"]) in (0, 2)]
    return (
        [parse_float(row["time_s"]) * 1.0e3 for row in selected],
        [parse_float(row["NH3"]) for row in selected],
    )


def main() -> None:
    if not SERIES_PATH.is_file():
        raise FileNotFoundError(f"Missing 200 ms trajectory: {SERIES_PATH}")

    time_ms, nh3_cm3 = load_off_phase_endpoints(SERIES_PATH)
    if abs(time_ms[-1] - 200.0) > 1.0e-9:
        raise RuntimeError("The input trajectory does not reach 200 ms")
    if abs(nh3_cm3[-1] - EXPECTED_FINAL_NH3) / EXPECTED_FINAL_NH3 > 1.0e-6:
        raise RuntimeError("Unexpected 200 ms NH3 endpoint")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(8.5, 7.3), sharex=True, constrained_layout=True)
    for axis in axes:
        axis.grid(True, which="both", alpha=0.3)

    axes[0].plot(time_ms, nh3_cm3, color="#1f4e79", linewidth=1.8)
    axes[0].scatter([time_ms[-1]], [nh3_cm3[-1]], color="#d95f02", s=32, zorder=3)
    axes[0].set_title("Closed 0D Hong gas-phase square-wave: NH$_3$ accumulation")
    axes[0].set_ylabel(r"[NH$_3$] (cm$^{-3}$)")
    axes[0].annotate(
        r"200 ms: $2.776\times10^{15}$ cm$^{-3}$",
        xy=(time_ms[-1], nh3_cm3[-1]), xytext=(112, 2.06e15),
        arrowprops={"arrowstyle": "->", "color": "#1f4e79"}, color="#1f4e79",
    )

    positive = [(time, value) for time, value in zip(time_ms, nh3_cm3) if value > 0.0]
    axes[1].semilogy(
        [item[0] for item in positive], [item[1] for item in positive],
        color="#1f4e79", linewidth=1.8,
    )
    axes[1].set_xlabel("Reaction time (ms)")
    axes[1].set_ylabel(r"[NH$_3$] (cm$^{-3}$, log scale)")
    axes[1].set_xlim(0.0, 200.0)

    fig.savefig(OUTPUT_PATH, dpi=240, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
