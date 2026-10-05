import math


def estimate_tokens(text: str) -> int:
    # 英文平均約 4 個字元 = 1 token；至少算 1
    return max(1, math.ceil(len(text) / 4))



def estimate_prompt_tokens(messages: list[dict]) -> int:
    # 每則訊息：內容的 token + 4 個格式 token；整個請求最後再 +3
    return sum(estimate_tokens(msg["content"]) + 4 for msg in messages) + 3
