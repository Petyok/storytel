"""LLM HTTP client: local llama.cpp (/completion or /v1/completions) or OpenRouter (/chat/completions)."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.services.provider_settings import get_provider_settings


def _stop_list_from_settings() -> list[str]:
    raw = (settings.llm_stop_sequences or "").strip()
    return [s.strip() for s in raw.split(",") if s.strip()]


def _normalize_llm_text(text: str) -> str:
    """Strip ChatML/Qwen junk so JSON extraction works (chat-tuned models)."""
    t = text.strip()
    # Qwen3 / DeepSeek-style thinking blocks (remove before JSON)
    t = re.sub(r"`</think>`[\s\S]*?`</think>`", "", t)
    t = re.sub(r"</think>[\s\S]*?</think>", "", t)
    t = re.sub(r"<think>[\s\S]*?</think>", "", t, flags=re.IGNORECASE)
    # Leading ChatML role lines (repeat — models may emit several)
    for _ in range(24):
        orig = t
        t = re.sub(r"^<\|im_start\|>[^\n]*\n?", "", t)
        t = re.sub(r"^<\|im_end\|>\s*", "", t)
        t = re.sub(r"^<\|assistant\|>\s*", "", t, flags=re.IGNORECASE)
        if t == orig:
            break
        t = t.lstrip()
    # Keep only text before trailing EOS markers (JSON should come first)
    for marker in ("<|im_end|>", "<|endoftext|>"):
        if marker in t:
            t = t.split(marker, 1)[0]
    return t.strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = _normalize_llm_text(text)
    # Strip markdown fences
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if m:
            text = m.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # Find outermost { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _text_from_llm_response(data: dict[str, Any], api_style: str) -> str:
    """Parse body from native /completion or OpenAI /v1/completions."""
    style = (api_style or "openai_completions").strip().lower()
    if style == "native":
        content = data.get("content", "")
        if content:
            return str(content).strip()
        ch0 = (data.get("choices") or [{}])[0]
        return (ch0.get("text") or ch0.get("message", {}).get("content") or "").strip()

    # openai_completions (and fallback)
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        c0 = choices[0]
        if isinstance(c0, dict):
            t = c0.get("text")
            if t is not None and str(t).strip():
                return str(t).strip()
            msg = c0.get("message")
            if isinstance(msg, dict) and msg.get("content"):
                return str(msg["content"]).strip()
    content = data.get("content", "")
    if content:
        return str(content).strip()
    return ""


def _provider(provider_settings: dict[str, Any] | None = None) -> str:
    cfg = provider_settings or get_provider_settings()
    return str(cfg.get("llm_provider", "local")).strip().lower() or "local"


class LlamaCppClient:
    """Talks to local llama-server or, when LLM_PROVIDER=openrouter, to OpenRouter chat API."""

    def __init__(
        self,
        base_url: str | None = None,
        completion_path: str | None = None,
        timeout: float | None = None,
        provider_settings: dict[str, Any] | None = None,
    ) -> None:
        self.provider_settings = dict(provider_settings or get_provider_settings())
        self.base_url = (base_url or str(self.provider_settings.get("llama_cpp_url", settings.llama_cpp_url))).rstrip("/")
        self.completion_path = completion_path or str(
            self.provider_settings.get("llama_completion_path", settings.llama_completion_path)
        )
        self.timeout = timeout if timeout is not None else float(
            self.provider_settings.get("llm_timeout_sec", settings.llm_timeout_sec)
        )
        self._api_style = str(
            self.provider_settings.get("llm_api_style", settings.llm_api_style or "openai_completions")
        ).strip().lower()

    def _cfg(self) -> dict[str, Any]:
        return self.provider_settings

    def _build_payload(
        self,
        prompt: str,
        max_tokens: int,
        *,
        temperature: float | None = None,
        stop: list[str] | None = None,
    ) -> dict[str, Any]:
        temp = float(settings.llm_temperature if temperature is None else temperature)
        stops = stop if stop is not None else _stop_list_from_settings()
        if self._api_style == "native":
            payload: dict[str, Any] = {
                "prompt": prompt,
                "n_predict": max_tokens,
                "temperature": temp,
                "top_p": settings.llm_top_p,
                "repeat_penalty": settings.llm_repeat_penalty,
            }
            if stops:
                payload["stop"] = stops
            return payload
        payload = {
            "model": str(self._cfg().get("llm_openai_model", settings.llm_openai_model)).strip(),
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temp,
            "top_p": settings.llm_top_p,
            "repeat_penalty": settings.llm_repeat_penalty,
        }
        if stops:
            payload["stop"] = stops
        return payload

    def _request_headers(self) -> dict[str, str]:
        key = str(self._cfg().get("llm_api_key", settings.llm_api_key or "")).strip()
        if key:
            return {"Authorization": f"Bearer {key}"}
        return {}

    def _openrouter_cache_dir(self) -> Path:
        return settings.openrouter_cache_dir

    def _openrouter_cache_key(self, payload: dict[str, Any], base: str) -> str:
        blob = json.dumps(
            {
                "base": base,
                "payload": payload,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _openrouter_cache_get(self, key: str, ttl_sec: int) -> str | None:
        if ttl_sec <= 0:
            return None
        path = self._openrouter_cache_dir() / f"{key}.json"
        if not path.exists():
            return None
        try:
            if (time.time() - path.stat().st_mtime) > ttl_sec:
                return None
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                text = raw.get("text")
                if isinstance(text, str):
                    return text
        except Exception:
            return None
        return None

    def _openrouter_cache_put(self, key: str, text: str) -> None:
        path = self._openrouter_cache_dir() / f"{key}.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"text": text, "cached_at": time.time()}, f, ensure_ascii=False)
        except Exception:
            pass

    def _openrouter_chat_complete(
        self,
        prompt: str,
        max_tokens: int,
        *,
        temperature: float | None = None,
        stop: list[str] | None = None,
    ) -> str:
        cfg = self._cfg()
        key = str(cfg.get("openrouter_api_key", settings.openrouter_api_key or "")).strip()
        if not key:
            raise ValueError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter")
        model = str(cfg.get("openrouter_model", settings.openrouter_model or "")).strip()
        if not model:
            raise ValueError("OPENROUTER_MODEL is required when LLM_PROVIDER=openrouter (see openrouter.ai/models)")

        base = str(cfg.get("openrouter_base_url", settings.openrouter_base_url or "https://openrouter.ai/api/v1")).rstrip("/")
        url = f"{base}/chat/completions"
        temp = float(settings.llm_temperature if temperature is None else temperature)
        stops = stop if stop is not None else _stop_list_from_settings()

        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temp,
            "top_p": float(settings.llm_top_p),
        }
        if stops:
            payload["stop"] = stops

        cache_enabled = bool(cfg.get("openrouter_cache_enabled", settings.openrouter_cache_enabled))
        ttl_sec = int(cfg.get("openrouter_cache_ttl_sec", settings.openrouter_cache_ttl_sec))
        cache_key = self._openrouter_cache_key(payload, base)
        if cache_enabled:
            cached = self._openrouter_cache_get(cache_key, ttl_sec)
            if cached is not None:
                return cached

        headers: dict[str, str] = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        ref = str(cfg.get("openrouter_http_referer", settings.openrouter_http_referer or "")).strip()
        if ref:
            headers["HTTP-Referer"] = ref
        title = str(cfg.get("openrouter_app_title", settings.openrouter_app_title or "")).strip()
        if title:
            headers["X-Title"] = title

        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        if not isinstance(data, dict):
            return ""
        text = _text_from_llm_response(data, "openai_completions")
        if cache_enabled and text:
            self._openrouter_cache_put(cache_key, text)
        return text

    def complete(
        self,
        prompt: str,
        max_tokens: int | None = None,
        *,
        temperature: float | None = None,
        stop: list[str] | None = None,
    ) -> str:
        mt = max_tokens or settings.llm_max_tokens
        if _provider(self._cfg()) == "openrouter":
            return self._openrouter_chat_complete(
                prompt, mt, temperature=temperature, stop=stop
            )

        url = f"{self.base_url}{self.completion_path}"
        payload = self._build_payload(prompt, mt, temperature=temperature, stop=stop)
        headers = self._request_headers()
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        if not isinstance(data, dict):
            return ""
        return _text_from_llm_response(data, self._api_style)

    def complete_with_retries(
        self,
        prompt: str,
        max_tokens: int | None = None,
        on_attempt: Callable[[int, int], None] | None = None,
        *,
        temperature: float | None = None,
        stop: list[str] | None = None,
    ) -> tuple[str, int, str | None]:
        """
        Returns (raw_text, attempts_used, last_error).
        Retries on 5xx, timeouts, and connection errors until max retries.
        on_attempt(current_1based, max_tries) is invoked before each HTTP call.
        """
        attempts = 0
        last_err: str | None = None
        max_tries = max(1, int(settings.llm_max_retries))
        backoff = float(settings.llm_retry_backoff_sec)

        for attempt in range(max_tries):
            attempts = attempt + 1
            if on_attempt is not None:
                on_attempt(attempts, max_tries)
            try:
                return (
                    self.complete(
                        prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        stop=stop,
                    ),
                    attempts,
                    None,
                )
            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response is not None else 0
                last_err = f"http_{code}"
                # Retry transient server / overload responses
                if code in (429, 500, 502, 503, 504) and attempt < max_tries - 1:
                    time.sleep(backoff * (2**attempt))
                    continue
                return "", attempts, last_err
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
                last_err = type(e).__name__
                if attempt < max_tries - 1:
                    time.sleep(backoff * (2**attempt))
                    continue
                return "", attempts, last_err
            except Exception as e:
                last_err = type(e).__name__
                return "", attempts, last_err

        return "", attempts, last_err or "unknown"


def parse_llm_json_object(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    obj = _extract_json_object(raw)
    if not obj:
        return None, "not_json"
    return obj, None


def parse_llm_game_response(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (parsed_dict, error_reason)."""
    obj, err = parse_llm_json_object(raw)
    if not obj:
        return None, err
    if "scene" not in obj or "choices" not in obj:
        return None, "missing_keys"
    scene = obj.get("scene")
    choices = obj.get("choices")
    if isinstance(choices, str):
        try:
            parsed_ch = json.loads(choices.strip())
            if isinstance(parsed_ch, list):
                choices = parsed_ch
                obj["choices"] = parsed_ch
        except json.JSONDecodeError:
            pass
    if not isinstance(scene, str) or not scene.strip():
        return None, "empty_scene"
    if not isinstance(choices, list) or len(choices) < 2 or len(choices) > 4:
        return None, "bad_choices_count"
    ch = [str(c).strip() for c in choices if str(c).strip()]
    if len(ch) < 2:
        return None, "choices_empty"
    obj["scene"] = scene.strip()[:2000]
    obj["choices"] = ch[:4]
    if "effects_hint" not in obj:
        obj["effects_hint"] = ""
    elif not isinstance(obj["effects_hint"], str):
        obj["effects_hint"] = str(obj["effects_hint"])[:500]
    return obj, None
