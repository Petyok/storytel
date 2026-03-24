from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    # backend/app/core/config.py -> repo root is parents[2].parent
    sessions_dir: Path = Path(__file__).resolve().parents[2].parent / "sessions"
    llama_cpp_url: str = "http://127.0.0.1:8080"
    # Native: POST /completion (n_predict, content). OpenAI-style: POST /v1/completions (recommended for current llama-server).
    llama_completion_path: str = "/v1/completions"
    llm_api_style: str = "openai_completions"  # or "native"
    # Dummy model id for /v1/completions (llama-server ignores or uses for routing)
    llm_openai_model: str = "gpt-3.5-turbo-instruct"
    # Optional Bearer token (some proxies require it; local llama-server often does not)
    llm_api_key: str = ""
    llm_timeout_sec: float = 120.0
    llm_max_tokens: int = 512
    llm_temperature: float = 0.75
    llm_top_p: float = 0.9
    llm_repeat_penalty: float = 1.1
    max_prompt_chars: int = 12000  # ~3–4k tokens proxy for CPU models
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # LLM resilience (llama-server may return 500 under load)
    llm_max_retries: int = 4
    llm_retry_backoff_sec: float = 0.6

    # Story pacing: N "light" turns, then 1 "mad" turn (cycle length N+1)
    madness_light_per_mad: int = 50


settings = Settings()
