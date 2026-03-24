import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.sessions import router as sessions_router
from app.core.config import settings
from app.models.schemas import ProviderSettingsResponse, ProviderSettingsUpdateRequest
from app.services.game_engine import LLM_PARSE_WAVES
from app.services.llm_client import LlamaCppClient
from app.services.provider_settings import (
    get_provider_settings,
    provider_settings_response_dict,
    save_provider_settings,
)

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
    current = get_provider_settings()
    prov = str(current.get("llm_provider", "local")).strip().lower() or "local"
    or_ok = bool(
        str(current.get("openrouter_api_key", "")).strip()
        and str(current.get("openrouter_model", "")).strip()
    )
    return {
        "status": "ok",
        "llm_max_retries": settings.llm_max_retries,
        "llm_parse_waves": LLM_PARSE_WAVES,
        "llm_provider": prov,
        "openrouter_ready": or_ok if prov == "openrouter" else False,
    }


@app.get("/settings/public", response_model=ProviderSettingsResponse)
def settings_public() -> ProviderSettingsResponse:
    return ProviderSettingsResponse(**provider_settings_response_dict())

@app.get("/settings/provider", response_model=ProviderSettingsResponse)
def settings_provider() -> ProviderSettingsResponse:
    return ProviderSettingsResponse(**provider_settings_response_dict())


@app.put("/settings/provider", response_model=ProviderSettingsResponse)
def settings_provider_update(body: ProviderSettingsUpdateRequest) -> ProviderSettingsResponse:
    save_provider_settings(body.model_dump(exclude_none=True))
    return ProviderSettingsResponse(**provider_settings_response_dict())


@app.post("/settings/test-llm")
def settings_test_llm(body: ProviderSettingsUpdateRequest | None = None) -> dict[str, object]:
    """One minimal completion against the active provider (local llama-server or OpenRouter)."""
    effective = get_provider_settings()
    if body is not None:
        effective = {**effective, **body.model_dump(exclude_none=True)}
    prov = str(effective.get("llm_provider", "local")).strip().lower() or "local"
    t0 = time.perf_counter()
    client = LlamaCppClient(provider_settings=effective)
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
