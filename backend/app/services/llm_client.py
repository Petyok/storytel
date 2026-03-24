"""llama.cpp HTTP completion client (server default: /completion)."""

from __future__ import annotations

import json
import re
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

    def complete(self, prompt: str, max_tokens: int | None = None) -> str:
        url = f"{self.base_url}{self.completion_path}"
        payload: dict[str, Any] = {
            "prompt": prompt,
            "n_predict": max_tokens or settings.llm_max_tokens,
            "temperature": settings.llm_temperature,
            "top_p": settings.llm_top_p,
            "repeat_penalty": settings.llm_repeat_penalty,
        }
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
        # llama.cpp server returns { "content": "..." } for /completion
        content = data.get("content", "")
        if not content and "choices" in data:
            # OpenAI-compatible fallback
            ch0 = (data.get("choices") or [{}])[0]
            content = (ch0.get("text") or ch0.get("message", {}).get("content") or "").strip()
        return str(content).strip()


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
