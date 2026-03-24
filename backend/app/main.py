import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.sessions import router as sessions_router
from app.core.config import settings
from app.services.game_engine import LLM_PARSE_WAVES
from app.services.llm_client import LlamaCppClient

app = FastAPI(title="Dark Fantasy Story", version="1.0.0")

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)


@app.get("/health")
def health() -> dict[str, object]:
    prov = (settings.llm_provider or "local").strip().lower()
    or_ok = bool((settings.openrouter_api_key or "").strip() and (settings.openrouter_model or "").strip())
    return {
        "status": "ok",
        "llm_max_retries": settings.llm_max_retries,
        "llm_parse_waves": LLM_PARSE_WAVES,
        "llm_provider": prov,
        "openrouter_ready": or_ok if prov == "openrouter" else False,
    }


@app.get("/settings/public")
def settings_public() -> dict[str, object]:
    """Non-secret LLM / provider configuration for the UI (env-driven)."""
    prov = (settings.llm_provider or "local").strip().lower()
    or_key = bool((settings.openrouter_api_key or "").strip())
    or_model = bool((settings.openrouter_model or "").strip())
    return {
        "llm_provider": prov,
        "llama_cpp_url": settings.llama_cpp_url,
        "llama_completion_path": settings.llama_completion_path,
        "llm_api_style": settings.llm_api_style,
        "llm_openai_model": settings.llm_openai_model,
        "openrouter_base_url": settings.openrouter_base_url,
        "openrouter_model": (settings.openrouter_model or "").strip(),
        "openrouter_ready": or_key and or_model if prov == "openrouter" else False,
        "has_openrouter_api_key": or_key,
        "has_llm_bearer": bool((settings.llm_api_key or "").strip()),
        "llm_timeout_sec": settings.llm_timeout_sec,
    }


@app.post("/settings/test-llm")
def settings_test_llm() -> dict[str, object]:
    """One minimal completion against the active provider (local llama-server or OpenRouter)."""
    prov = (settings.llm_provider or "local").strip().lower()
    t0 = time.perf_counter()
    client = LlamaCppClient()
    try:
        text = client.complete(
            "Reply with only the letter A.",
            max_tokens=8,
            temperature=0,
            stop=[],
        )
        ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": True,
            "latency_ms": ms,
            "llm_provider": prov,
            "response_preview": (text or "").strip()[:120],
        }
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        detail = str(e)
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                body = (resp.text or "")[:300]
                if body:
                    detail = f"{detail} — {body}"
            except Exception:
                pass
        return {
            "ok": False,
            "latency_ms": ms,
            "llm_provider": prov,
            "error": type(e).__name__,
            "detail": detail[:500],
        }
