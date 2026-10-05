"""Plot asyncio.sleep vs time.sleep from the CSVs written by sleep_experiment.py.

Usage (from the project root):
    python -m scripts.plot_sleep_experiment
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

RESULTS_DIR = Path("experiments/results")
CHART_PATH = Path("experiments/charts/asyncio_vs_time_sleep.png")

SERIES = [
    # (label in CSV, legend name, color)
    ("asyncio_sleep", "await asyncio.sleep", "#2a78d6"),
    ("time_sleep", "time.sleep", "#eb6834"),
]
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"


def load_medians() -> pd.DataFrame:
    frames = [pd.read_csv(RESULTS_DIR / f"sleep_{label}.csv") for label, _, _ in SERIES]
    df = pd.concat(frames)
    # 守則 4：同一設定跑 3 次，取中位數
    return df.groupby(["label", "concurrency"], as_index=False)[
        ["wall_seconds", "mean_server_latency_ms"]
    ].median()


def plot(medians: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for label, name, color in SERIES:
        s = medians[medians["label"] == label].sort_values("concurrency")
        ax.plot(s["concurrency"], s["wall_seconds"], color=color, linewidth=2,
                marker="o", markersize=7, markeredgecolor=SURFACE, markeredgewidth=2, label=name)
        # 只在最後一點標數字，避免每個點都有數字
        last = s.iloc[-1]
        ax.annotate(f"{name}: {last['wall_seconds']:.1f}s",
                    (last["concurrency"], last["wall_seconds"]),
                    xytext=(8, 0), textcoords="offset points", va="center",
                    color=TEXT_PRIMARY, fontsize=9)

    ax.set_title("Total time for N concurrent requests to the mock LLM",
                 loc="left", color=TEXT_PRIMARY, fontsize=12, pad=12)
    ax.set_xlabel("Concurrent requests", color=TEXT_SECONDARY)
    ax.set_ylabel("Total wall time (s), median of 3 runs", color=TEXT_SECONDARY)
    ax.set_xticks(sorted(medians["concurrency"].unique()))
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(colors=TEXT_SECONDARY)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.legend(frameon=False, labelcolor=TEXT_PRIMARY, loc="upper left")
    ax.margins(x=0.15)

    CHART_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(CHART_PATH, facecolor=SURFACE)
    print(f"Saved {CHART_PATH}")


def print_table(medians: pd.DataFrame) -> None:
    table = medians.pivot(index="concurrency", columns="label", values="wall_seconds")
    table["slowdown_x"] = (table["time_sleep"] / table["asyncio_sleep"]).round(1)
    print("\nMedian total wall time (s):")
    print(table.to_string())


if __name__ == "__main__":
    medians = load_medians()
    print_table(medians)
    plot(medians)
