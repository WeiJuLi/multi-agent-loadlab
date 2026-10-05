import time

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

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
async def chat_completions(req: ChatCompletionRequest):
    reply = "This is a mock reply."
    return {
        "id": "chatcmpl-mock",
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
        # 第 3 課再算真的 token 數
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.get("/health")
async def health():
    return {"status": "ok"}