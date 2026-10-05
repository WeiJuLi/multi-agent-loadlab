"""Send N concurrent requests to the mock LLM and record how long the whole batch takes.

Usage (from the project root, with the mock LLM already running):
    python -m scripts.sleep_experiment --label asyncio_sleep
    python -m scripts.sleep_experiment --label time_sleep
"""

import argparse
import asyncio
import csv
import statistics
import time
from pathlib import Path

import httpx

URL = "http://localhost:8001/v1/chat/completions"
PAYLOAD = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}
RESULTS_DIR = Path("experiments/results")


async def send_batch(client: httpx.AsyncClient, concurrency: int) -> tuple[float, list[float]]:
    # 同時送出 concurrency 個請求，回傳「整批花多久」和「伺服器回報的每個延遲」
    start = time.perf_counter()
    responses = await asyncio.gather(*(client.post(URL, json=PAYLOAD) for _ in range(concurrency)))
    wall_seconds = time.perf_counter() - start
    for r in responses:
        r.raise_for_status()
    server_ms = [float(r.headers["x-mock-latency-ms"]) for r in responses]
    return wall_seconds, server_ms


async def main(label: str, levels: list[int], runs: int) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"sleep_{label}.csv"
    rows = []
    # time.sleep 版本會排隊，20 個請求可能要 40 秒以上，timeout 要給夠
    async with httpx.AsyncClient(timeout=300) as client:
        for concurrency in levels:
            for run in range(1, runs + 1):
                wall_seconds, server_ms = await send_batch(client, concurrency)
                mean_ms = statistics.mean(server_ms)
                rows.append({
                    "label": label,
                    "concurrency": concurrency,
                    "run": run,
                    "wall_seconds": round(wall_seconds, 3),
                    "mean_server_latency_ms": round(mean_ms, 1),
                })
                print(f"{label:>14}  concurrency={concurrency:>3}  run={run}  "
                      f"wall={wall_seconds:6.2f}s  mean server latency={mean_ms:7.1f}ms")

    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="e.g. asyncio_sleep or time_sleep")
    parser.add_argument("--levels", type=int, nargs="+", default=[1, 5, 10, 20])
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(main(args.label, args.levels, args.runs))
