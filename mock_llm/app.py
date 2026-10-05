import asyncio
import random
import time
from dataclasses import asdict

from fastapi import FastAPI, Response
from pydantic import BaseModel, ConfigDict

from mock_llm.config import Settings
from mock_llm.latency import compute_latency_seconds
from mock_llm.responses import generate_reply
from mock_llm.tokens import estimate_prompt_tokens, estimate_tokens

settings = Settings.from_env()
rng = random.Random(settings.seed)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    # LangChain 會多送一些我們用不到的欄位（例如 stream、n），
    # extra="allow" 讓 FastAPI 收下它們而不是回 422 錯誤
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage]
    temperature: float = 1.0
    max_tokens: int | None = None
    max_completion_tokens: int | None = None


app = FastAPI(title="Mock LLM")


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, response: Response):
    # 每個請求固定的抽取順序：① id → ② 抖動
    completion_id = f"chatcmpl-{rng.getrandbits(48):012x}"

    # Pydantic 物件轉成普通 dict，responses.py 就不用依賴 app.py
    messages = [m.model_dump() for m in req.messages]
    reply = generate_reply(messages)
    prompt_tokens = estimate_prompt_tokens(messages)
    completion_tokens = estimate_tokens(reply)

    latency = compute_latency_seconds(settings, prompt_tokens, completion_tokens, rng)
    # 一定要用 asyncio.sleep：等待時 event loop 可以去處理別的請求
    #await asyncio.sleep(latency)
    time.sleep(latency)

    # 把實際延遲放進 header，方便驗證公式和 seed
    response.headers["x-mock-latency-ms"] = f"{latency * 1000:.0f}"

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


# 壓測前打一次，把結果貼進實驗紀錄表的 mock_llm_params 欄，
# 保證記錄的是真正生效的值，而不是你以為的值。
@app.get("/admin/config")
async def get_config():
    return asdict(settings)
