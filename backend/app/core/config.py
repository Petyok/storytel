from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    # backend/app/core/config.py -> repo root is parents[2].parent
    repo_root: Path = Path(__file__).resolve().parents[2].parent
    sessions_dir: Path = repo_root / "sessions"
    runtime_settings_path: Path = repo_root / ".storytel_settings.json"
    openrouter_cache_dir: Path = repo_root / ".cache" / "openrouter"

    # LLM_PROVIDER=local (llama.cpp server) | openrouter
    llm_provider: str = "local"

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
    # Story turns: lower temp + more tokens helps chat-tuned models (Qwen, etc.) emit valid JSON
    llm_game_max_tokens: int = 896
    llm_game_temperature: float = 0.35
    # Comma-separated stop strings for /v1/completions (e.g. </think> when the model adds it after JSON)
    llm_stop_sequences: str = "<|im_end|>"
    max_prompt_chars: int = 12000  # ~3–4k tokens proxy for CPU models
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # OpenRouter (OpenAI-compatible chat): https://openrouter.ai/docs
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # e.g. qwen/qwen-2.5-7b-instruct, anthropic/claude-3.5-sonnet, openai/gpt-4o-mini
    openrouter_model: str = ""
    # Optional dedicated model for scene/context image generation.
    openrouter_image_model: str = ""
    # Optional headers OpenRouter recommends for rankings
    openrouter_http_referer: str = ""
    openrouter_app_title: str = "Storytel"
    openrouter_cache_enabled: bool = True
    openrouter_cache_ttl_sec: int = 1800

    # LLM resilience (llama-server may return 500 under load)
    llm_max_retries: int = 4
    llm_retry_backoff_sec: float = 0.6

    # Story pacing: N "light" turns, then 1 "mad" turn (cycle length N+1)
    madness_light_per_mad: int = 50


settings = Settings()
