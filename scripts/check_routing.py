import json

from mock_llm.responses import generate_reply

EXPECTED = {
    "knowledge": ["knowledge"],
    "calculator": ["calculator"],
    "both": ["knowledge", "calculator"],
}

with open("data/question_pool.json") as f:
    pool = json.load(f)["questions"]

wrong = 0
for q in pool:
    messages = [
        {"role": "system", "content": "[ROLE:supervisor]"},
        {"role": "user", "content": q["question"]},
    ]
    experts = json.loads(generate_reply(messages))["experts"]
    if experts != EXPECTED[q["type"]]:
        wrong += 1
        print(f"❌ {q['id']} ({q['type']}) → {experts}: {q['question']}")

print(f"\n{len(pool) - wrong}/{len(pool)} routed correctly")
