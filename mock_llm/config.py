import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)  
    

def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    value_lower = value.strip().lower()
    if value_lower in ("true", "1", "yes"):
        return True
    elif value_lower in ("false", "0", "no"):
        return False
    else:
        raise ValueError(f"Invalid boolean value for {name}: {value}")


@dataclass(frozen=True) #建立後不能修改
class Settings:
    seed: int
    latency_base_ms: float
    latency_per_prompt_token_ms: float
    latency_per_completion_token_ms: float
    latency_jitter: float
    rate_limit_enabled: bool
    rpm: int
    tpm: int
    default_max_tokens: int
    error_rate: float
    hang_rate: float
    hang_seconds: float
    paused: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            seed=_env_int("MOCK_LLM_SEED", 42),
            latency_base_ms=_env_float("MOCK_LLM_LATENCY_BASE_MS", 200),
            latency_per_prompt_token_ms=_env_float("MOCK_LLM_LATENCY_PER_PROMPT_TOKEN_MS", 0.3),
            latency_per_completion_token_ms=_env_float("MOCK_LLM_LATENCY_PER_COMPLETION_TOKEN_MS", 15),
            latency_jitter=_env_float("MOCK_LLM_LATENCY_JITTER", 0.2),
            rate_limit_enabled=_env_bool("MOCK_LLM_RATE_LIMIT_ENABLED", True),
            # 預設值和 .env.example 一致；故障注入一律預設關閉
            rpm=_env_int("MOCK_LLM_RPM", 1000),
            tpm=_env_int("MOCK_LLM_TPM", 1000000),
            default_max_tokens=_env_int("MOCK_LLM_DEFAULT_MAX_TOKENS", 800),
            error_rate=_env_float("MOCK_LLM_ERROR_RATE", 0.0),
            hang_rate=_env_float("MOCK_LLM_HANG_RATE", 0.0),
            hang_seconds=_env_float("MOCK_LLM_HANG_SECONDS", 60),
            paused=_env_bool("MOCK_LLM_PAUSED", False),
        )
