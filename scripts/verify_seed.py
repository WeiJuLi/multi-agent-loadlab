"""reset 後依序送一串請求，做兩輪，確認兩輪的 id、狀態碼、延遲完全相同。

Usage:
    python -m scripts.verify_seed
"""

import httpx

BASE_URL = "http://localhost:8001"
# 混合不同內容，不只測 "hi"
PROMPTS = [
    [{"role": "user", "content": "hi"}],
    [{"role": "system", "content": "[ROLE:supervisor]"},
     {"role": "user", "content": "What is the monthly payment on $10,000 over 3 years?"}],
    [{"role": "system", "content": "[ROLE:reviewer]"},
     {"role": "user", "content": "Draft:\nYou need a photo ID."}],
]
ROUNDS_PER_PASS = 3   # 3 種內容 × 3 輪 = 每次 9 個請求


def run_once(client: httpx.Client) -> list[tuple]:
    client.post("/admin/reset")
    results = []
    # 一定要「依序」送：同時送的話，誰先到不固定，結果就不能比
    for _ in range(ROUNDS_PER_PASS):
        for messages in PROMPTS:
            r = client.post("/v1/chat/completions", json={"model": "gpt-4o-mini", "messages": messages})
            body = r.json()
            results.append((
                r.status_code,
                body.get("id", "-"),
                r.headers.get("x-mock-latency-ms", "-"),
                r.headers.get("x-mock-fault", "-"),
            ))
    return results


with httpx.Client(base_url=BASE_URL, timeout=120) as client:
    first = run_once(client)
    second = run_once(client)

for i, (a, b) in enumerate(zip(first, second), start=1):
    print(f"{'✅' if a == b else '❌'} #{i:<2} {a}  |  {b}")
print("\n✅ same seed → same results" if first == second else "\n❌ results differ")
