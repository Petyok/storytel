from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings


_STRING_FIELDS: tuple[str, ...] = (
    "llm_provider",
    "llama_cpp_url",
    "llama_completion_path",
    "llm_api_style",
    "llm_openai_model",
    "llm_api_key",
    "openrouter_api_key",
    "openrouter_base_url",
    "openrouter_model",
    "openrouter_image_model",
    "openrouter_http_referer",
    "openrouter_app_title",
)


def _defaults() -> dict[str, Any]:
    return {
        "llm_provider": (settings.llm_provider or "local").strip().lower() or "local",
        "llama_cpp_url": str(settings.llama_cpp_url).strip(),
        "llama_completion_path": str(settings.llama_completion_path).strip() or "/v1/completions",
        "llm_api_style": str(settings.llm_api_style).strip().lower() or "openai_completions",
        "llm_openai_model": str(settings.llm_openai_model).strip(),
        "llm_api_key": str(settings.llm_api_key).strip(),
        "llm_timeout_sec": float(settings.llm_timeout_sec),
        "openrouter_api_key": str(settings.openrouter_api_key).strip(),
        "openrouter_base_url": str(settings.openrouter_base_url).strip() or "https://openrouter.ai/api/v1",
        "openrouter_model": str(settings.openrouter_model).strip(),
        "openrouter_image_model": str(settings.openrouter_image_model).strip(),
        "openrouter_http_referer": str(settings.openrouter_http_referer).strip(),
        "openrouter_app_title": str(settings.openrouter_app_title).strip() or "Storytel",
        "openrouter_cache_enabled": bool(settings.openrouter_cache_enabled),
        "openrouter_cache_ttl_sec": max(0, int(settings.openrouter_cache_ttl_sec)),
    }


def _path() -> Path:
    return settings.runtime_settings_path


def _read_file() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return raw if isinstance(raw, dict) else {}


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    merged = _defaults()
    for key in _STRING_FIELDS:
        if key in data and data[key] is not None:
            merged[key] = str(data[key]).strip()

    if "llm_provider" in data and data["llm_provider"] is not None:
        prov = str(data["llm_provider"]).strip().lower()
        merged["llm_provider"] = prov if prov in {"local", "openrouter"} else "local"

    if "llm_api_style" in data and data["llm_api_style"] is not None:
        style = str(data["llm_api_style"]).strip().lower()
        merged["llm_api_style"] = style if style in {"native", "openai_completions"} else "openai_completions"

    if "llm_timeout_sec" in data and data["llm_timeout_sec"] is not None:
        try:
            merged["llm_timeout_sec"] = max(1.0, min(600.0, float(data["llm_timeout_sec"])))
        except (TypeError, ValueError):
            pass

    if "openrouter_cache_enabled" in data and data["openrouter_cache_enabled"] is not None:
        merged["openrouter_cache_enabled"] = bool(data["openrouter_cache_enabled"])

    if "openrouter_cache_ttl_sec" in data and data["openrouter_cache_ttl_sec"] is not None:
        try:
            merged["openrouter_cache_ttl_sec"] = max(0, min(86400, int(data["openrouter_cache_ttl_sec"])))
        except (TypeError, ValueError):
            pass

    if not str(merged["llama_completion_path"]).startswith("/"):
        merged["llama_completion_path"] = f"/{merged['llama_completion_path']}"

    return merged


def get_provider_settings() -> dict[str, Any]:
    return _normalize(_read_file())


def save_provider_settings(update: dict[str, Any]) -> dict[str, Any]:
    merged = _normalize({**_read_file(), **update})
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    return merged


def provider_settings_response_dict(include_secrets: bool = True) -> dict[str, Any]:
    current = get_provider_settings()
    openrouter_key = str(current.get("openrouter_api_key", "")).strip()
    llm_key = str(current.get("llm_api_key", "")).strip()
    openrouter_model = str(current.get("openrouter_model", "")).strip()
    image_model = str(current.get("openrouter_image_model", "")).strip()
    provider = str(current.get("llm_provider", "local")).strip().lower() or "local"
    data = {
        **current,
        "llm_provider": provider,
        "openrouter_ready": bool(openrouter_key and openrouter_model),
        "openrouter_image_ready": bool(openrouter_key and image_model),
        "has_openrouter_api_key": bool(openrouter_key),
        "has_llm_bearer": bool(llm_key),
    }
    if not include_secrets:
        data["openrouter_api_key"] = ""
        data["llm_api_key"] = ""
    return data
