from __future__ import annotations

from typing import Any

from app.models.schemas import UnifiedStateView
from app.services.llm_client import LlamaCppClient
from app.services.provider_settings import get_provider_settings
from app.services.state_store import SessionFiles


def _safe_int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _lang(value: str | None) -> str:
    v = str(value or "").strip().lower()
    return "ru" if v.startswith("ru") else "en"


def build_map_image_prompt(scene: str, unified: UnifiedStateView, lang: str) -> str:
    tone = (
        "Create a top-down fantasy local map illustration on aged parchment."
        if lang != "ru"
        else "Создай иллюстрацию локальной фэнтезийной карты сверху на состаренном пергаменте."
    )
    prompt = (
        f"{tone}\n"
        f"Location: {unified.world.location}\n"
        f"Time: {unified.world.time}\n"
        f"Scene cues: {scene[:700]}\n"
        f"ASCII map reference:\n{unified.world.ascii_map[:1200]}\n"
        "Show terrain, paths, landmarks, borders, water, and dangerous zones that match the current location.\n"
        "No UI, no labels, no legend box, no modern cartography, no text overlay."
    )
    return prompt[:3000]


def build_character_image_prompt(unified: UnifiedStateView, lang: str) -> str:
    player = unified.player
    inv = ", ".join(player.inventory[:4]) or ("none" if lang != "ru" else "нет")
    backstory = player.backstory or ("Unknown drifter" if lang != "ru" else "Неизвестный скиталец")
    appearance = player.appearance or ("weathered traveler with practical gear" if lang != "ru" else "потрёпанный путник в практичном снаряжении")
    tone = (
        "Create a character portrait for a dark fantasy RPG. Half-body, cinematic light, realistic medieval clothing."
        if lang != "ru"
        else "Создай портрет персонажа для RPG в тёмном фэнтези. По пояс, кинематографичный свет, реалистичная средневековая одежда."
    )
    prompt = (
        f"{tone}\n"
        f"Name: {player.name}\n"
        f"Backstory: {backstory[:1200]}\n"
        f"Appearance: {appearance[:800]}\n"
        f"Current status: {player.status}\n"
        f"Location context: {unified.world.location}\n"
        f"Inventory cues: {inv}\n"
        "One clear subject only. No text overlay, no watermark, no split panel, no extra characters unless they are vague background silhouettes."
    )
    return prompt[:3000]


def ensure_session_media(
    sf: SessionFiles,
    unified: UnifiedStateView,
    *,
    scene: str,
    session_start: bool = False,
    location_changed: bool = False,
) -> None:
    cfg = get_provider_settings()
    if not (str(cfg.get("openrouter_api_key", "")).strip() and str(cfg.get("openrouter_image_model", "")).strip()):
        return

    player_raw = sf.main_character if isinstance(sf.main_character, dict) else {}
    world_raw = sf.world if isinstance(sf.world, dict) else {}
    lang = _lang(unified.player.flags.get("language"))
    current_turn = max(0, int(unified.world.turn))
    changed = False
    client = LlamaCppClient(provider_settings=cfg)

    portrait_rounds = max(0, int(cfg.get("character_image_rounds", 10)))
    portrait_image = str(player_raw.get("portrait_image", "") or "")
    portrait_turn = _safe_int(player_raw.get("portrait_generated_turn", -1), -1)
    need_portrait = False
    if not portrait_image:
        need_portrait = True
    elif portrait_rounds == 0:
        need_portrait = False
    elif (current_turn - portrait_turn) >= portrait_rounds:
        need_portrait = True

    if need_portrait and (portrait_rounds > 0 or session_start or not portrait_image):
        try:
            image_url, _cached = client.generate_openrouter_image(
                build_character_image_prompt(unified, lang),
                aspect_ratio="3:4",
            )
            player_raw["portrait_image"] = image_url
            player_raw["portrait_prompt"] = build_character_image_prompt(unified, lang)
            player_raw["portrait_generated_turn"] = current_turn
            changed = True
        except Exception:
            pass

    map_rounds = max(0, int(cfg.get("map_image_rounds", 6)))
    map_image = str(world_raw.get("map_image", "") or "")
    map_turn = _safe_int(world_raw.get("map_generated_turn", -1), -1)
    ascii_map = str(unified.world.ascii_map or "").strip()
    need_map = False
    if ascii_map and not map_image:
        need_map = True
    elif ascii_map and location_changed and (map_rounds == 0 or map_turn < 0 or (current_turn - map_turn) >= map_rounds):
        need_map = True

    if need_map:
        try:
            image_url, _cached = client.generate_openrouter_image(
                build_map_image_prompt(scene, unified, lang),
                aspect_ratio="4:3",
            )
            world_raw["map_image"] = image_url
            world_raw["map_image_prompt"] = build_map_image_prompt(scene, unified, lang)
            world_raw["map_generated_turn"] = current_turn
            world_raw["map_generated_location"] = unified.world.location
            changed = True
        except Exception:
            pass

    if changed:
        sf.main_character = player_raw
        sf.world = world_raw
        sf.save()
