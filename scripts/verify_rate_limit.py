"""RPM=10 時同時送 30 個請求，確認約 20 個 429，而且每個 429 都有 Retry-After。

Usage:
    MOCK_LLM_RPM=10 uvicorn mock_llm.app:app --port 8001 --workers 1   # 終端機 1
    python -m scripts.verify_rate_limit                                # 終端機 2
"""

import asyncio
from collections import Counter

import httpx

BASE_URL = "http://localhost:8001"
PAYLOAD = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}
TOTAL = 30


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        # 先讀「真正生效」的設定，避免用錯 RPM 啟動還以為測試通過
        config = (await client.get("/admin/config")).json()
        rpm = config["rpm"]
        if not config["rate_limit_enabled"] or not 0 < rpm < TOTAL:
            print(f"❌ 目前 rate_limit_enabled={config['rate_limit_enabled']}, rpm={rpm}；"
                  f"請用 MOCK_LLM_RPM=10 重新啟動")
            return

        await client.post("/admin/reset")   # 桶子補滿，從頭開始
        responses = await asyncio.gather(
            *(client.post("/v1/chat/completions", json=PAYLOAD) for _ in range(TOTAL))
        )

    counts = Counter(r.status_code for r in responses)
    limited = [r for r in responses if r.status_code == 429]
    missing_header = [r for r in limited if "retry-after" not in r.headers]
    retry_afters = sorted({int(r.headers["retry-after"]) for r in limited if "retry-after" in r.headers})

    print(f"RPM={rpm}, sent {TOTAL} at once → {dict(counts)}")
    print(f"Retry-After values: {retry_afters}")
    ok = counts[200] == rpm and counts[429] == TOTAL - rpm and not missing_header
    print("✅ passed" if ok else f"❌ failed（{len(missing_header)} 個 429 沒有 Retry-After）")


if __name__ == "__main__":
    asyncio.run(main())
