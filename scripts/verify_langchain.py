"""用 LangChain 的 ChatOpenAI 打模擬 LLM，確認 5 種角色都回對的內容。

Usage（先啟動模擬 LLM）:
    python -m scripts.verify_langchain
"""

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

# 和階段 2 的 agent 用同一種寫法；換成真的 LLM 只要改 base_url、api_key、model
llm = ChatOpenAI(
    base_url="http://localhost:8001/v1",
    api_key="mock-key",
    model="gpt-4o-mini",
    temperature=0,
    max_tokens=512,
    max_retries=0,   # 關掉 SDK 自動重試，錯誤才會原樣呈現
    timeout=30,
)

TOOL_RESULT = json.dumps({
    "principal": 20000, "annual_rate_pct": 8.5, "months": 60,
    "monthly_payment": 410.33, "total_interest": 4619.8, "total_paid": 24619.8,
})

# (名稱, system prompt, user 訊息, 回答裡應該出現的文字)
CASES = [
    ("supervisor", "[ROLE:supervisor] Route the question.",
     "What is the monthly payment on a $20,000 loan over 5 years, and what documents do I need?",
     '"experts": ["knowledge", "calculator"]'),
    ("knowledge", "[ROLE:knowledge] Answer using the references.",
     "Question: What documents do I need?\nReferences:\n"
     "[FAQ-01] Q: What documents do I need? A: A photo ID and three pay stubs.",
     "Based on our FAQ"),
    ("calculator", "[ROLE:calculator] Explain the result.",
     f"Question: Monthly payment on $20,000 over 5 years?\nTOOL_RESULT: {TOOL_RESULT}",
     "monthly payment is $410.33"),
    ("reviewer", "[ROLE:reviewer] Review the draft.",
     "Draft:\nYou need a photo ID.",
     "for reference only"),
    ("no role", None, "hi", "This is a mock reply."),
]

failed = 0
for name, system, user, expected in CASES:
    messages = ([SystemMessage(system)] if system else []) + [HumanMessage(user)]
    reply = llm.invoke(messages)
    ok = expected in reply.content
    failed += not ok
    print(f"{'✅' if ok else '❌'} {name:<11} tokens={reply.usage_metadata['total_tokens']:<4} "
          f"{reply.content[:70]}")

print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
