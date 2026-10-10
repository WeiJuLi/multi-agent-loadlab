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

# 暫停開關：set = 正常（綠燈）；clear = 暫停（紅燈，請求卡在 wait）
running = asyncio.Event()
if not settings.paused:
    running.set()

# 背景任務要存參考，否則可能被垃圾回收而沒執行完
background_tasks: set[asyncio.Task] = set()


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
    # ⓪ 暫停中就卡在這裡，模擬下游完全沒回應
    await running.wait()

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

    # 每個請求固定抽 4 次：① id → ② 是否 500 → ③ 是否卡住 → ④ 抖動
    # 就算故障關閉也照抽，不同故障設定的實驗之間，同一位置的請求才拿到同樣的抖動
    completion_id = f"chatcmpl-{rng.getrandbits(48):012x}"
    error_roll = rng.random()
    hang_roll = rng.random()

    reply = generate_reply(messages)
    completion_tokens = estimate_tokens(reply)
    # ④ 抖動也要在決定回 500「之前」抽完，否則回 500 的請求少抽一次，後面全部錯開
    latency = compute_latency_seconds(settings, prompt_tokens, completion_tokens, rng)

    if error_roll < settings.error_rate:
        return error_response(
            500,
            "The server had an error while processing your request.",
            "server_error",
            headers={"x-mock-fault": "error"},
        )

    if hang_roll < settings.hang_rate:
        # 在正常延遲之外多卡一段時間，模擬「這次呼叫莫名其妙特別慢」
        await asyncio.sleep(settings.hang_seconds)
        response.headers["x-mock-fault"] = "hang"

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


def error_response(
    status_code: int,
    message: str,
    error_type: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    # OpenAI 的錯誤格式；SDK 會依 status code 拋出對應的例外（429 → RateLimitError、500 → InternalServerError）
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={"error": {"message": message, "type": error_type, "code": str(status_code)}},
    )


def rate_limited_response(wait_seconds: float) -> JSONResponse:
    # Retry-After 依 HTTP 標準必須是整數秒，無條件進位才不會叫客戶端太早回來
    retry_after = math.ceil(wait_seconds)
    return error_response(
        429,
        f"Rate limit exceeded. Retry after {retry_after} seconds.",
        "rate_limit_error",
        headers={
            "Retry-After": str(retry_after),
            # Azure 額外提供的毫秒版本，比較精確
            "retry-after-ms": str(math.ceil(wait_seconds * 1000)),
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


async def _resume_after(seconds: float) -> None:
    await asyncio.sleep(seconds)
    running.set()


# 模擬下游中斷：POST /admin/pause?seconds=30 → 30 秒後自動恢復；不帶 seconds 就一直暫停
@app.post("/admin/pause")
async def pause(seconds: float | None = None):
    running.clear()
    if seconds is not None:
        # 交給 event loop 在背景倒數，這個 API 本身馬上回應
        task = asyncio.create_task(_resume_after(seconds))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
    return {"status": "paused", "auto_resume_seconds": seconds}


@app.post("/admin/resume")
async def resume():
    running.set()
    return {"status": "running"}
