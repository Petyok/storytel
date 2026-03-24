"""LLM HTTP client: native llama.cpp /completion or OpenAI-compatible /v1/completions."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.core.config import settings


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
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


class LlamaCppClient:
    def __init__(
        self,
        base_url: str | None = None,
        completion_path: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.llama_cpp_url).rstrip("/")
        self.completion_path = completion_path or settings.llama_completion_path
        self.timeout = timeout if timeout is not None else settings.llm_timeout_sec
        self._api_style = (settings.llm_api_style or "openai_completions").strip().lower()

    def _build_payload(self, prompt: str, max_tokens: int) -> dict[str, Any]:
        if self._api_style == "native":
            return {
                "prompt": prompt,
                "n_predict": max_tokens,
                "temperature": settings.llm_temperature,
                "top_p": settings.llm_top_p,
                "repeat_penalty": settings.llm_repeat_penalty,
            }
        return {
            "model": settings.llm_openai_model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": settings.llm_temperature,
            "top_p": settings.llm_top_p,
            "repeat_penalty": settings.llm_repeat_penalty,
        }

    def _request_headers(self) -> dict[str, str]:
        key = (settings.llm_api_key or "").strip()
        if key:
            return {"Authorization": f"Bearer {key}"}
        return {}

    def complete(self, prompt: str, max_tokens: int | None = None) -> str:
        url = f"{self.base_url}{self.completion_path}"
        mt = max_tokens or settings.llm_max_tokens
        payload = self._build_payload(prompt, mt)
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
                return self.complete(prompt, max_tokens=max_tokens), attempts, None
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


def parse_llm_game_response(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (parsed_dict, error_reason)."""
    obj = _extract_json_object(raw)
    if not obj:
        return None, "not_json"
    if "scene" not in obj or "choices" not in obj:
        return None, "missing_keys"
    scene = obj.get("scene")
    choices = obj.get("choices")
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
