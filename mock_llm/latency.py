import random

from mock_llm.config import Settings


def compute_latency_seconds(
    settings: Settings,
    prompt_tokens: int,
    completion_tokens: int,
    rng: random.Random,
) -> float:
    base_ms = (
        settings.latency_base_ms
        + prompt_tokens * settings.latency_per_prompt_token_ms
        + completion_tokens * settings.latency_per_completion_token_ms
    )
    # TODO: 抽一個抖動係數，範圍是 (1 - jitter) 到 (1 + jitter)
    #   提示：rng.uniform(a, b) 會回傳 a 到 b 之間的隨機小數
    # TODO: 回傳「秒」（注意上面算的是毫秒）
    jitter_factor = rng.uniform(1 - settings.latency_jitter, 1 + settings.latency_jitter)
    latency_ms = base_ms * jitter_factor
    return latency_ms / 1000.0

