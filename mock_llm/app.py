import asyncio
import math
import random
import time
from dataclasses import asdict

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from mock_llm.config import Settings
from mock_llm.latency import compute_latency_seconds
from mock_llm.rate_limiter import RateLimiter
from mock_llm.responses import generate_reply
from mock_llm.tokens import estimate_prompt_tokens, estimate_tokens

settings = Settings.from_env()
rng = random.Random(settings.seed)
# 限流關閉時設成 None，endpoint 就直接跳過檢查
limiter = RateLimiter(settings.rpm, settings.tpm) if settings.rate_limit_enabled else None


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
    # Pydantic 物件轉成普通 dict，responses.py 就不用依賴 app.py
    messages = [m.model_dump() for m in req.messages]
    prompt_tokens = estimate_prompt_tokens(messages)

    # 限流放在最前面：被拒絕的請求不抽隨機數，seed 序列才不會因為 429 而錯開
    if limiter is not None:
        # 和 Azure 一樣：產生回答前不知道會多長，所以 TPM 用 max_tokens 先扣
        # 新名字 max_completion_tokens 優先，沒有就用舊名字，都沒有用預設值
        max_tokens = req.max_completion_tokens or req.max_tokens or settings.default_max_tokens
        wait_seconds = limiter.try_acquire(prompt_tokens + max_tokens)
        if wait_seconds > 0:
            return rate_limited_response(wait_seconds)

    # 每個請求固定的抽取順序：① id → ② 抖動
    completion_id = f"chatcmpl-{rng.getrandbits(48):012x}"

    reply = generate_reply(messages)
    completion_tokens = estimate_tokens(reply)

    latency = compute_latency_seconds(settings, prompt_tokens, completion_tokens, rng)
    # 一定要用 asyncio.sleep：等待時 event loop 可以去處理別的請求
    await asyncio.sleep(latency)

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


def rate_limited_response(wait_seconds: float) -> JSONResponse:
    # Retry-After 依 HTTP 標準必須是整數秒，無條件進位才不會叫客戶端太早回來
    retry_after = math.ceil(wait_seconds)
    return JSONResponse(
        status_code=429,
        headers={
            "Retry-After": str(retry_after),
            # Azure 額外提供的毫秒版本，比較精確
            "retry-after-ms": str(math.ceil(wait_seconds * 1000)),
        },
        # OpenAI 的錯誤格式；SDK 會依 status code 拋出 RateLimitError
        content={
            "error": {
                "message": f"Rate limit exceeded. Retry after {retry_after} seconds.",
                "type": "rate_limit_error",
                "code": "429",
            }
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


# 壓測前打一次，把結果貼進實驗紀錄表的 mock_llm_params 欄，
# 保證記錄的是真正生效的值，而不是你以為的值。
@app.get("/admin/config")
async def get_config():
    return asdict(settings)


# 每次實驗前打一次：隨機數序列回到起點、限流桶補滿，不用重啟服務
@app.post("/admin/reset")
async def reset():
    # rng.seed 修改的是同一個物件；寫 rng = random.Random(...) 只會建立區域變數
    rng.seed(settings.seed)
    if limiter is not None:
        limiter.reset()
    return {"status": "reset", "seed": settings.seed}
