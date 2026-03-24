"""
Turn loop: compact prompt -> LLM JSON -> validate -> deterministic state updates.
"""

from __future__ import annotations

import json
import re
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

from app.core.config import settings
from app.models.schemas import NPCState, UnifiedStateView
from app.services.llm_client import LlamaCppClient, parse_llm_game_response, parse_llm_json_object
from app.services.provider_settings import get_provider_settings
from app.services.state_store import BASE_SKILLS, SessionFiles, apply_unified_to_files, merge_to_unified

TIME_ORDER = ["dawn", "morning", "noon", "dusk", "night", "witching_hour"]

# Default map for new sessions (compact but readable).
DEFAULT_BOOTSTRAP_ASCII_MAP = """    N
+---+---+---+---+---+---+
| # | # | # | ~ | ~ | # |
+---+---+---+---+---+---+
| # | . | . | . | T | # |   T  toll / threshold
+---+---+---+---+---+---+
| # | . | @ | . | . | # |   @  you
+---+---+---+---+---+---+
| # | > | . | . | P | # |   >  descent   P  patrol
+---+---+---+---+---+---+
| # | # | # | # | # | # |
+---+---+---+---+---+---+
  # wall   . floor   ~ water"""

DEFAULT_BOOTSTRAP_ASCII_MAP_RU = """    С
+---+---+---+---+---+---+
| # | # | # | ~ | ~ | # |
+---+---+---+---+---+---+
| # | . | . | . | T | # |   T  пошлина / порог
+---+---+---+---+---+---+
| # | . | @ | . | . | # |   @  вы
+---+---+---+---+---+---+
| # | > | . | . | P | # |   >  спуск   P  патруль
+---+---+---+---+---+---+
| # | # | # | # | # | # |
+---+---+---+---+---+---+
  # стена   . пол   ~ вода"""


def _normalize_lang(value: str | None) -> str:
    v = str(value or "").strip().lower()
    return "ru" if v.startswith("ru") else "en"


def _lang_instruction(lang: str) -> str:
    if lang == "ru":
        return "Write scene and choices in Russian. Keep JSON keys in English."
    return "Write scene and choices in English."


def _model_failed_notice(lang: str) -> str:
    if lang == "ru":
        return "Модель не вернула корректный JSON. Ход не применён — попробуйте снова."
    return "The model did not return valid play JSON. This turn was not applied—try again."


LLM_PARSE_WAVES = 3


def _opening_setting(location: str, premise: str) -> str:
    """Coarse place type from free text (location + premise) for bootstrap prose."""
    blob = f"{location} {premise}".lower()
    forest_kw = (
        "forest",
        "wood",
        "grove",
        "jungle",
        "wildwood",
        "лес",
        "чащ",
        "рощ",
        "дубрав",
        "elven",
        "elf",
        "эльф",
        "fey",
        "фейр",
        "sylvan",
        "бора",
        "тайг",
    )
    water_kw = (
        "sea",
        "ocean",
        "lake",
        "river",
        "coast",
        "harbor",
        "harbour",
        "port",
        "bay",
        "dock",
        "море",
        "озер",
        "рек",
        "бухт",
        "причал",
        "берег",
        "залив",
    )
    urban_kw = (
        "city",
        "town",
        "gate",
        "market",
        "street",
        "inn",
        "tavern",
        "district",
        "citadel",
        "borough",
        "slum",
        "город",
        "площад",
        "рынок",
        "трактир",
        "постоял",
        "крепост",
        "стен",
        "ворот",
        "ул.",
        "улиц",
        "квартал",
    )
    for k in forest_kw:
        if k in blob:
            return "forest"
    for k in water_kw:
        if k in blob:
            return "water"
    for k in urban_kw:
        if k in blob:
            return "urban"
    return "wild"


def _opening_seed_payload(
    lang: str,
    player_name: str,
    world_location: str,
    world_premise: str = "",
) -> tuple[str, list[str]]:
    """First scene + choices: tone matches location (forest / water / town / open country)."""
    setting = _opening_setting(world_location, world_premise)

    if setting == "forest":
        if lang == "ru":
            scene = (
                f"{player_name} переступает кромку «{world_location}». Смола и мокрый мох; свет здесь редкий — "
                "но впереди, между стволами, тянет теплом, будто чей-то костёр или факел. "
                "Сзади сухие ветки отвечают на шаг слишком ровно, чтобы это был только ветер."
            )
            choices = [
                "Подойти к тусклому свету между деревьями",
                "Замереть и вслушаться в лес",
                "Свернуть с тропы и стереть след",
            ]
        else:
            scene = (
                f"{player_name} crosses into the edge of {world_location}. Tar-sap and wet bark; light is scarce—"
                "yet ahead, between the trunks, something breathes warmth like embers or a shaded lantern. "
                "Behind you, twigs answer your stride with a patience that doesn't feel like wind alone."
            )
            choices = [
                "Move toward the faint glow between the trees",
                "Hold still and listen to the wood",
                "Leave the path and break the line of sight",
            ]
        return scene, choices

    if setting == "water":
        if lang == "ru":
            scene = (
                f"{player_name} выходит к «{world_location}». Воздух солёный и холодный; на набережной редко горят окна, "
                "но где-то ближе к причалу слышен смех и звон посуды — и чьи-то шаги держатся на одном и том же расстоянии позади."
            )
            choices = [
                "Найти трактир у причала",
                "Осмотреть причал и суда",
                "Скрыться за складами и бочками",
            ]
        else:
            scene = (
                f"{player_name} comes down to {world_location}. The air is salt-cold; few windows burn along the waterfront, "
                "but nearer the docks there's clatter and laughter—and footsteps behind you hold the same distance no matter how you slow."
            )
            choices = [
                "Head for a dockside inn",
                "Scan the piers and boats",
                "Slip between sheds and stacked casks",
            ]
        return scene, choices

    if setting == "urban":
        if lang == "ru":
            scene = (
                f"{player_name} выходит к «{world_location}». День клонится к вечеру; фонари ещё не везде зажжены, "
                "но из-за угла тянет жаром кухни, а дверь трактира приоткрыта. Шаги позади не догоняют — но и не отстают."
            )
            choices = [
                "Зайти в трактир",
                "Остановиться и осмотреться",
                "Скользнуть в ближайший переулок",
            ]
        else:
            scene = (
                f"{player_name} arrives at {world_location}. Evening is gathering; lamps aren't all lit yet, "
                "but heat and noise spill from a kitchen doorway, and a tavern stands ajar. Whoever follows you neither hurries nor falls behind."
            )
            choices = [
                "Step inside for food and a corner",
                "Pause and read the street",
                "Slip down the nearest alley",
            ]
        return scene, choices

    # wild: roads, hills, desert, steppe, anything not matched above
    if lang == "ru":
        scene = (
            f"{player_name} держит путь к «{world_location}». Небо широкое, дорога пустая; впереди единственный намёк на кров — "
            "дымок, остов постройки или чей-то очаг. Позади слышно, как гравий сдвигается под чужой поступью."
        )
        choices = [
            "Идти к дымку или огоньку вдали",
            "Осмотреться и приметить укрытие",
            "Сойти с дороги и залечь",
        ]
    else:
        scene = (
            f"{player_name} keeps toward {world_location}. The sky is wide and the road thin; ahead, the only promise of shelter—"
            "a thread of smoke, a ruin's outline, someone's small fire. Behind you, gravel shifts under a second set of boots."
        )
        choices = [
            "Walk toward the distant smoke or glow",
            "Stop and pick a defensible spot",
            "Leave the road and go to ground",
        ]
    return scene, choices


def _rest_quest_seed(lang: str, setting: str) -> tuple[str, str]:
    if setting == "forest":
        if lang == "ru":
            return (
                "Найти место отдыха",
                "Переждать ночь: костёр путников, полый ствол, сухой шалаш — любое укрытие без лишних глаз.",
            )
        return (
            "Find a place to rest",
            "Wait out the night—a traveler's fire, a hollow tree, a lean-to—any dry cover away from prying eyes.",
        )
    if setting == "water":
        if lang == "ru":
            return (
                "Найти место отдыха",
                "Укрытие у воды: постоялый двор, каюта на судне или сухой склад — где не задают лишних вопросов.",
            )
        return (
            "Find a place to rest",
            "Shelter by the water—an inn, a ship's berth, a dry warehouse—somewhere questions stay few.",
        )
    if setting == "urban":
        if lang == "ru":
            return (
                "Найти место отдыха",
                "Где переждать ночь: трактир, постоялый двор или тихий двор без лишних вопросов.",
            )
        return (
            "Find a place to rest",
            "Learn where you can wait out the night—a tavern, an inn, or a quiet corner without too many questions.",
        )
    if lang == "ru":
        return (
            "Найти место отдыха",
            "Ночлег в открытой местности: стоянка, руины, чей-то лагерь — где можно не спать под небом.",
        )
    return (
        "Find a place to rest",
        "Shelter in the open—waystation, ruin ring, or a stranger's camp—anywhere you're not sleeping under raw sky.",
    )


def _skills_from_backstory(backstory: str) -> dict[str, int]:
    text = (backstory or "").lower()
    scores = {k: 0 for k in BASE_SKILLS}
    pairs: list[tuple[list[str], str]] = [
        (["climb", "run", "jump", "swim", "лез", "бег", "прыг", "сил"], "athletics"),
        (["sneak", "hide", "quiet", "крад", "тих", "скрыт"], "stealth"),
        (["listen", "watch", "track", "слуш", "замет", "ищ", "вид"], "perception"),
        (["talk", "charm", "negot", "говор", "убежд", "торг"], "persuasion"),
        (["wild", "forest", "trail", "camp", "лес", "охот", "след", "дорог"], "survival"),
        (["magic", "spell", "arcane", "маг", "заклин", "руны"], "arcana"),
        (["heal", "herb", "poison", "лекар", "яд", "ран", "целит"], "medicine"),
        (["read", "lie", "motive", "чувств", "лже", "намер"], "insight"),
        (["threat", "scare", "intimid", "запуг", "страх"], "intimidation"),
        (["search", "clue", "puzzle", "осмотр", "улик", "разгад"], "investigation"),
    ]
    for keys, skill in pairs:
        for k in keys:
            if k in text:
                scores[skill] += 1
                break
    out: dict[str, int] = {}
    for k in BASE_SKILLS:
        v = scores[k]
        out[k] = min(3, max(-2, v)) if v else 0
    return out


def _is_mad_turn(turn_before_increment: int) -> bool:
    n = max(1, int(settings.madness_light_per_mad))
    cycle = n + 1
    return (turn_before_increment % cycle) == n


def _format_player_action(choice: str, free_text: str, roll_dice: bool = False) -> str:
    c = (choice or "").strip()
    f = (free_text or "").strip()
    parts: list[str] = []
    if c:
        parts.append(f"Chosen button: {c}")
    if f:
        parts.append(f"Player says/does: {f}")
    if roll_dice:
        parts.append("Player explicitly asks to roll dice for this interaction.")
    if not parts and roll_dice:
        parts.append("Player rolls the dice and lets fate decide the moment.")
    return "\n".join(parts)


def _mixed_skill_check(
    action_text: str,
    lang: str,
    skills: dict[str, int],
    danger: int,
    *,
    force_roll: bool = False,
) -> tuple[str | None, str | None]:
    """Returns (prompt_line, short_tag for effects)."""
    t = (action_text or "").lower()
    if len(t) < 6 and not force_roll:
        return None, None
    # keyword → skill
    rules: list[tuple[tuple[str, ...], str]] = [
        (("climb", "jump", "swim", "run", "lift", "лез", "прыг", "плы", "бег", "сил"), "athletics"),
        (("hide", "sneak", "quiet", "крад", "тих", "скры"), "stealth"),
        (("listen", "look", "search", "track", "слуш", "смотр", "ищ", "осмотр"), "perception"),
        (("talk", "persuade", "lie", "charm", "говор", "убежд", "лже"), "persuasion"),
        (("wild", "trail", "camp", "forest", "лес", "дорог", "след"), "survival"),
        (("magic", "spell", "arcane", "маг", "заклин"), "arcana"),
        (("heal", "treat", "poison", "лекар", "яд", "ран"), "medicine"),
        (("read", "intent", "motive", "чувств", "намер"), "insight"),
        (("threat", "scare", "intimid", "запуг"), "intimidation"),
        (("investigate", "clue", "study", "улик", "разгад"), "investigation"),
    ]
    picked: str | None = None
    for keys, sk in rules:
        if any(k in t for k in keys):
            picked = sk
            break
    if not picked and force_roll:
        ranked = sorted(
            ((int(skills.get(sk, 0)), sk) for sk in BASE_SKILLS),
            reverse=True,
        )
        best_mod, best_skill = ranked[0] if ranked else (0, "fortune")
        if best_mod > 0:
            picked = best_skill
        else:
            picked = "fortune"
    if not picked:
        return None, None
    mod = int(skills.get(picked, 0)) if picked in skills else 0
    dc = min(20, max(8, 12 + danger // 2))
    d20 = secrets.randbelow(20) + 1
    total = d20 + mod
    ok = total >= dc
    if lang == "ru":
        line = f"Проверка: {picked} — d20({d20}){mod:+d} = {total} против СЛ {dc}: {'успех' if ok else 'провал'}."
        tag = f"check:{picked}|{d20}|{mod}|{dc}|{'ok' if ok else 'fail'}"
    else:
        line = f"Check: {picked} — d20({d20}){mod:+d} = {total} vs DC {dc}: {'success' if ok else 'failure'}."
        tag = f"check:{picked}|{d20}|{mod}|{dc}|{'ok' if ok else 'fail'}"
    return line, tag


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SYSTEM_PROMPT_BASE = """You are a dark fantasy game master.

Use current game state:
{state_json}

OUTPUT FORMAT (critical):
- Your entire message must be ONE valid JSON object and nothing else.
- First character must be {{ and last character must be }}.
- Do not use markdown code fences (no ```).
- Do not use XML tags, role headers, or "thinking" blocks—only the JSON object.
- "choices" must be a JSON array of 2-4 short strings (not a single string).

Schema:
{{"scene":"...","choices":["...","..."],"effects_hint":"short hidden note for engine; optional tags: hp+/-N gold+/-N danger+/-N time+1 flag:name item+:Name item-:Name trust:NPCName+/-N quest+:title|desc quest~:id|completed|note"}}"""

STORY_MODE_MAD_RULES = """
Pacing mode: MAD (1 in {cycle} turns).
Rules:
- Never write passive descriptions only
- NPCs must be proactive
- Every turn must change the situation
- Every action must have consequences
- Include at least one hidden element (do not reveal it plainly in scene; put a clue in effects_hint only)
- End the JSON with 2-4 player choices (short labels, actionable)
"""

STORY_MODE_LIGHT_RULES = """
Pacing mode: LIGHT ({n} of every {cycle} turns).
Rules:
- Write a short calm slice of atmosphere (about 2-4 sentences). Grounded, sensory, everyday.
- Do NOT escalate into cosmic horror, prophecy, chosen-one destiny, or world-ending stakes.
- Do NOT pressure the player with urgent "you must choose now" rhetoric; no cliffhanger questions.
- Still change one small concrete detail in the environment (sound, smell, light, object, passerby).
- NPCs may appear but keep interactions ordinary.
- End with 2-4 mild exploratory choices (low stakes).
"""


def compact_state_for_prompt(u: UnifiedStateView) -> dict[str, Any]:
    inv = u.player.inventory[:12]
    active_q = u.quests.active[:6]
    npcs = [{"n": n.name, "t": n.trust, "h": (n.hidden_intent[:40] + "…") if len(n.hidden_intent) > 40 else n.hidden_intent} for n in u.world.npcs[:6]]
    sk = {k: int(u.player.skills.get(k, 0)) for k in BASE_SKILLS}
    return {
        "player": {
            "name": u.player.name,
            "hp": u.player.hp,
            "gold": u.player.gold,
            "status": u.player.status,
            "skills": sk,
            "inv": inv,
            "flags": dict(list(u.player.flags.items())[:16]),
        },
        "world": {
            "loc": u.world.location,
            "danger": u.world.danger_level,
            "time": u.world.time,
            "secrets_n": len(u.world.secrets),
            "turn": u.world.turn,
            "npcs": npcs,
        },
        "quests": [
            {
                "id": q.get("id"),
                "t": q.get("title"),
                "d": str(q.get("description", ""))[:220],
                "s": q.get("status"),
                "last_note": str((q.get("notes") or [{}])[-1].get("text", ""))[:160]
                if isinstance(q.get("notes"), list) and q.get("notes")
                else "",
            }
            for q in active_q
        ],
    }


def build_user_prompt(last_scene: str, action_block: str, recent_lines: list[str], check_line: str | None = None) -> str:
    return _build_turn_context(last_scene, action_block, recent_lines, check_line) + (
        "\n\nNarrate the next beat. Reply with the JSON object only, starting with {."
    )


def _build_turn_context(
    last_scene: str,
    action_block: str,
    recent_lines: list[str],
    check_line: str | None = None,
) -> str:
    parts = []
    if recent_lines:
        parts.append("Recent:\n" + "\n".join(recent_lines[-4:]))
    if last_scene:
        parts.append("Previous scene:\n" + last_scene[:800])
    if check_line:
        parts.append("Dice / skill result:\n" + check_line)
    parts.append(f"Player action:\n{action_block.strip()[:900]}")
    return "\n\n".join(parts)


def build_scene_image_prompt(scene: str, unified: UnifiedStateView, lang: str) -> str:
    npc_names = ", ".join(n.name for n in unified.world.npcs[:3] if n.name) or ("none" if lang != "ru" else "нет")
    quest_titles = ", ".join(str(q.get("title", "")).strip() for q in unified.quests.active[:2] if str(q.get("title", "")).strip())
    inventory = ", ".join(unified.player.inventory[:4]) or ("none" if lang != "ru" else "нет")
    style_line = (
        "Create a cinematic dark fantasy illustration with grounded medieval textures, dramatic light, and clear focal subjects."
        if lang != "ru"
        else "Создай кинематографичную иллюстрацию тёмного фэнтези с приземлёнными средневековыми фактурами, драматичным светом и ясным фокусом."
    )
    prompt = (
        f"{style_line}\n"
        f"Scene:\n{scene[:1400]}\n\n"
        f"Location: {unified.world.location}\n"
        f"Time of day: {unified.world.time}\n"
        f"Danger level: {unified.world.danger_level}/10\n"
        f"Important NPCs: {npc_names}\n"
        f"Player inventory cues: {inventory}\n"
        f"Active quest cues: {quest_titles or ('none' if lang != 'ru' else 'нет')}\n"
        "Avoid text overlays, UI, speech bubbles, watermarks, logos, and split panels.\n"
        "Prefer one coherent moment from the current scene, suitable for a story splash image."
    )
    return prompt[:3000]


def build_full_prompt(state_json: str, user_block: str, lang: str, story_mode: str) -> str:
    n = max(1, int(settings.madness_light_per_mad))
    cycle = n + 1
    system = SYSTEM_PROMPT_BASE.format(state_json=state_json)
    if story_mode == "mad":
        system += STORY_MODE_MAD_RULES.format(cycle=cycle)
    else:
        system += STORY_MODE_LIGHT_RULES.format(n=n, cycle=cycle)
    system = f"{system}\nLanguage rule: {_lang_instruction(lang)}"
    full = system + "\n\n" + user_block
    if len(full) > settings.max_prompt_chars:
        full = full[: settings.max_prompt_chars] + "\n\n[truncated]"
    return full


def _trimmed_list(value: Any, *, limit: int = 4, item_limit: int = 160) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:limit]:
        text = str(item).strip()
        if text:
            out.append(text[:item_limit])
    return out


def _coerce_int(value: Any, default: int = 0, minimum: int = -999, maximum: int = 999) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _sanitize_world_stage(obj: dict[str, Any]) -> dict[str, Any]:
    npcs_raw = obj.get("npcs")
    npcs: list[dict[str, Any]] = []
    if isinstance(npcs_raw, list):
        for row in npcs_raw[:4]:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()[:80]
            if not name:
                continue
            npcs.append(
                {
                    "name": name,
                    "trust_delta": _coerce_int(row.get("trust_delta", 0), minimum=-3, maximum=3),
                    "hidden_intent": str(row.get("hidden_intent", "")).strip()[:160],
                }
            )
    return {
        "summary": str(obj.get("summary", "")).strip()[:300],
        "location": str(obj.get("location", "")).strip()[:120],
        "danger_delta": _coerce_int(obj.get("danger_delta", 0), minimum=-3, maximum=3),
        "advance_time": bool(obj.get("advance_time", False)),
        "secrets_add": _trimmed_list(obj.get("secrets_add"), limit=3),
        "npcs": npcs,
    }


def _sanitize_player_stage(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": str(obj.get("summary", "")).strip()[:300],
        "hp_delta": _coerce_int(obj.get("hp_delta", 0), minimum=-25, maximum=25),
        "gold_delta": _coerce_int(obj.get("gold_delta", 0), minimum=-50, maximum=50),
        "status": str(obj.get("status", "")).strip()[:80],
        "inventory_add": _trimmed_list(obj.get("inventory_add"), limit=4, item_limit=80),
        "inventory_remove": _trimmed_list(obj.get("inventory_remove"), limit=4, item_limit=80),
        "flags_add": _trimmed_list(obj.get("flags_add"), limit=6, item_limit=60),
    }


def _sanitize_quest_stage(obj: dict[str, Any]) -> dict[str, Any]:
    adds: list[dict[str, Any]] = []
    if isinstance(obj.get("quests_add"), list):
        for row in obj["quests_add"][:3]:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title", "")).strip()[:120]
            if not title:
                continue
            adds.append(
                {
                    "title": title,
                    "description": str(row.get("description", "")).strip()[:240] or "New objective",
                }
            )
    updates: list[dict[str, Any]] = []
    if isinstance(obj.get("quests_update"), list):
        for row in obj["quests_update"][:5]:
            if not isinstance(row, dict):
                continue
            qid = _coerce_int(row.get("id"), default=-1, minimum=-1, maximum=999999)
            if qid < 0:
                continue
            status = str(row.get("status", "active")).strip().lower()
            if status not in {"active", "completed", "failed"}:
                status = "active"
            updates.append(
                {
                    "id": qid,
                    "status": status,
                    "note": str(row.get("note", "")).strip()[:200],
                }
            )
    return {
        "summary": str(obj.get("summary", "")).strip()[:300],
        "quests_add": adds,
        "quests_update": updates,
    }


def _sanitize_interaction_stage(obj: dict[str, Any]) -> dict[str, Any]:
    choices = _trimmed_list(obj.get("choices"), limit=4, item_limit=120)
    return {
        "summary": str(obj.get("summary", "")).strip()[:300],
        "choices": choices[:4] if len(choices) >= 2 else [],
        "effects_hint": str(obj.get("effects_hint", "")).strip()[:400],
    }


def _append_unique(items: list[str], value: str) -> bool:
    norm = value.strip().lower()
    if not norm:
        return False
    if any(str(item).strip().lower() == norm for item in items):
        return False
    items.append(value)
    return True


def _apply_world_stage(stage: dict[str, Any], unified: UnifiedStateView) -> list[str]:
    applied: list[str] = []
    location = stage.get("location", "")
    if location and location != unified.world.location:
        unified.world.location = location
        applied.append("world:location")
    delta = int(stage.get("danger_delta", 0))
    if delta:
        unified.world.danger_level = max(0, min(10, unified.world.danger_level + delta))
        applied.append("world:danger")
    if stage.get("advance_time"):
        unified.world.time = _advance_time(unified.world.time)
        applied.append("world:time")
    for secret in stage.get("secrets_add", []):
        if _append_unique(unified.world.secrets, secret):
            applied.append("world:secret")
    for row in stage.get("npcs", []):
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        existing = next((n for n in unified.world.npcs if n.name.lower() == name.lower()), None)
        if existing is None:
            unified.world.npcs.append(
                NPCState(
                    name=name,
                    trust=max(-10, min(10, int(row.get("trust_delta", 0)))),
                    hidden_intent=str(row.get("hidden_intent", "")).strip(),
                )
            )
            applied.append("world:npc+")
            continue
        delta = _coerce_int(row.get("trust_delta", 0), minimum=-3, maximum=3)
        if delta:
            existing.trust = max(-10, min(10, existing.trust + delta))
            applied.append("world:npc~")
        intent = str(row.get("hidden_intent", "")).strip()
        if intent:
            existing.hidden_intent = intent
            applied.append("world:intent")
    return applied


def _apply_player_stage(stage: dict[str, Any], unified: UnifiedStateView) -> list[str]:
    applied: list[str] = []
    hp_delta = int(stage.get("hp_delta", 0))
    if hp_delta:
        unified.player.hp = max(0, min(999, unified.player.hp + hp_delta))
        applied.append("player:hp")
    gold_delta = int(stage.get("gold_delta", 0))
    if gold_delta:
        unified.player.gold = max(0, unified.player.gold + gold_delta)
        applied.append("player:gold")
    status = str(stage.get("status", "")).strip()
    if status and status != unified.player.status:
        unified.player.status = status
        applied.append("player:status")
    inv = list(unified.player.inventory)
    for item in stage.get("inventory_add", []):
        if _append_unique(inv, item):
            applied.append("player:item+")
    remove_norm = {str(item).strip().lower() for item in stage.get("inventory_remove", [])}
    if remove_norm:
        new_inv = [item for item in inv if item.split(" x")[0].strip().lower() not in remove_norm]
        if len(new_inv) != len(inv):
            applied.append("player:item-")
        inv = new_inv
    unified.player.inventory = inv
    for flag in stage.get("flags_add", []):
        key = str(flag).strip()
        if key:
            unified.player.flags[key] = True
            applied.append(f"flag:{key}")
    return applied


def _quest_note(text: str) -> dict[str, str]:
    return {"timestamp": _utc_now(), "text": text[:200]}


def _update_quest_status(unified: UnifiedStateView, qid: int, status: str, note: str = "") -> bool:
    found: dict[str, Any] | None = None
    source = unified.quests.active
    for bucket in (unified.quests.active, unified.quests.completed):
        for idx, quest in enumerate(bucket):
            if int(quest.get("id", -1)) == qid:
                found = deepcopy(quest)
                del bucket[idx]
                source = bucket
                break
        if found is not None:
            break
    if found is None:
        return False
    found["status"] = status
    notes = found.get("notes")
    if not isinstance(notes, list):
        notes = []
    if note:
        notes.append(_quest_note(note))
    found["notes"] = notes
    target = unified.quests.completed if status in {"completed", "failed"} else unified.quests.active
    target.append(found)
    return True


def _apply_quest_stage(stage: dict[str, Any], unified: UnifiedStateView) -> list[str]:
    applied: list[str] = []
    next_id = max([int(q.get("id", 0)) for q in unified.quests.active + unified.quests.completed] or [0]) + 1
    for row in stage.get("quests_add", []):
        unified.quests.active.append(
            {
                "id": next_id,
                "title": row["title"],
                "description": row["description"],
                "status": "active",
                "created_at": _utc_now(),
                "notes": [],
            }
        )
        next_id += 1
        applied.append(f"quest+:{row['title']}")
    for row in stage.get("quests_update", []):
        if _update_quest_status(unified, int(row["id"]), str(row["status"]), str(row.get("note", ""))):
            applied.append(f"quest~:{row['id']}")
    return applied


def _quest_match_score(quest: dict[str, Any], action_text: str, scene: str, unified: UnifiedStateView) -> int:
    blob = f"{quest.get('title', '')} {quest.get('description', '')}".lower()
    hay = " ".join(
        [
            action_text.lower(),
            scene.lower(),
            unified.world.location.lower(),
            " ".join(item.lower() for item in unified.player.inventory),
        ]
    )
    special_pairs = (
        ("rest", ("rest", "sleep", "inn", "tavern", "camp", "shelter")),
        ("отдых", ("отдых", "ночлег", "укры", "лагер", "трактир", "постоял")),
        ("shelter", ("rest", "sleep", "camp", "shelter", "inn", "tavern")),
        ("укры", ("отдых", "ночлег", "укры", "лагер", "трактир", "постоял")),
    )
    for marker, keys in special_pairs:
        if marker in blob and any(key in hay for key in keys):
            return 3
    words = [w for w in re.findall(r"[a-zA-Zа-яА-ЯёЁ]{4,}", blob) if w not in {"quest", "find", "place", "rest", "goal", "цель", "найти", "место"}]
    hits = sum(1 for word in set(words) if word in hay)
    return hits


def _auto_complete_quests(
    unified: UnifiedStateView,
    action_text: str,
    scene: str,
    lang: str,
) -> list[str]:
    applied: list[str] = []
    completion_note = (
        "Auto-completed from the turn outcome."
        if lang != "ru"
        else "Автозавершено по итогу этого хода."
    )
    for quest in list(unified.quests.active):
        score = _quest_match_score(quest, action_text, scene, unified)
        if score >= 2 and _update_quest_status(unified, int(quest.get("id", -1)), "completed", completion_note):
            applied.append(f"quest~:{quest.get('id')}")
    return applied


def _json_prompt(prefix: str, state_json: str, context: str, schema: str, lang: str, extras: str = "") -> str:
    prompt = (
        f"{prefix}\n\nCurrent state:\n{state_json}\n\nTurn context:\n{context}\n\n"
        f"Language rule: {_lang_instruction(lang)}\n"
        "Return one JSON object only. No markdown, no commentary.\n"
        f"Schema:\n{schema}"
    )
    if extras:
        prompt += "\n" + extras
    if len(prompt) > settings.max_prompt_chars:
        prompt = prompt[: settings.max_prompt_chars] + "\n\n[truncated]"
    return prompt


def _build_world_stage_prompt(state_json: str, context: str, lang: str, prior_summaries: list[str]) -> str:
    extras = (
        "Focus only on world changes caused by the action: location, danger, time, secrets, and NPC trust/intent. "
        "Keep changes small and concrete. Use empty strings, zeros, or empty arrays when nothing changes.\n"
        f"Prior stage notes:\n{chr(10).join(prior_summaries) if prior_summaries else '(none)'}"
    )
    schema = '{"summary":"...", "location":"", "danger_delta":0, "advance_time":false, "secrets_add":[""], "npcs":[{"name":"", "trust_delta":0, "hidden_intent":""}]}'
    return _json_prompt("You update the WORLD layer of a dark fantasy session.", state_json, context, schema, lang, extras)


def _build_player_stage_prompt(state_json: str, context: str, lang: str, prior_summaries: list[str]) -> str:
    extras = (
        "Focus only on the player state: hp, gold, status, inventory, and flags. "
        "Do not narrate the whole scene; return deltas only.\n"
        f"Prior stage notes:\n{chr(10).join(prior_summaries) if prior_summaries else '(none)'}"
    )
    schema = '{"summary":"...", "hp_delta":0, "gold_delta":0, "status":"", "inventory_add":[""], "inventory_remove":[""], "flags_add":[""]}'
    return _json_prompt("You update the PLAYER layer of a dark fantasy session.", state_json, context, schema, lang, extras)


def _build_quest_stage_prompt(state_json: str, context: str, lang: str, prior_summaries: list[str]) -> str:
    extras = (
        "Focus only on quest progress. Treat the quest description as the source of truth for what counts as success or failure. "
        "Complete or fail quests when the action, resolved state, or immediate interaction fallout clearly satisfies their goal. "
        "Add at most one or two new quests when the turn naturally creates them.\n"
        f"Prior stage notes:\n{chr(10).join(prior_summaries) if prior_summaries else '(none)'}"
    )
    schema = '{"summary":"...", "quests_add":[{"title":"", "description":""}], "quests_update":[{"id":1, "status":"completed", "note":""}]}'
    return _json_prompt("You update the QUESTS layer of a dark fantasy session.", state_json, context, schema, lang, extras)


def _build_interaction_stage_prompt(state_json: str, context: str, lang: str, prior_summaries: list[str]) -> str:
    extras = (
        "Focus on immediate interaction fallout and the next actionable options. "
        "Use effects_hint only for simple engine tags like trust, flag, hp, gold, item, or danger changes that came from the interaction layer.\n"
        f"Prior stage notes:\n{chr(10).join(prior_summaries) if prior_summaries else '(none)'}"
    )
    schema = '{"summary":"...", "choices":["...", "..."], "effects_hint":""}'
    return _json_prompt("You update the INTERACTION layer of a dark fantasy session.", state_json, context, schema, lang, extras)


def _build_final_summary_prompt(
    state_json: str,
    context: str,
    lang: str,
    story_mode: str,
    stage_summaries: list[str],
    suggested_choices: list[str],
) -> str:
    summary_block = "\n".join(stage_summaries) if stage_summaries else "(none)"
    choice_block = "\n".join(f"- {c}" for c in suggested_choices) if suggested_choices else "(none)"
    narrator_context = (
        f"Resolved stage summaries:\n{summary_block}\n\n"
        f"Suggested next actions from the interaction layer:\n{choice_block}\n\n"
        f"{context}"
    )
    return build_full_prompt(state_json, narrator_context, lang, story_mode)


def _run_json_stage(
    llm: LlamaCppClient,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float,
    parser: Callable[[str], tuple[dict[str, Any] | None, str | None]],
    on_llm_attempt: Callable[[int, int, int], None] | None = None,
) -> tuple[dict[str, Any] | None, int]:
    total_attempts = 0
    for wave in range(1, LLM_PARSE_WAVES + 1):
        wave_prompt = prompt
        if wave > 1:
            wave_prompt += "\n\nReminder: return one valid JSON object only."

        def _attempt_cb(cur: int, mx: int, w: int = wave) -> None:
            if on_llm_attempt is not None:
                on_llm_attempt(cur, mx, w)

        raw, attempts, _err = llm.complete_with_retries(
            wave_prompt,
            max_tokens=max_tokens,
            on_attempt=_attempt_cb,
            temperature=temperature,
        )
        total_attempts += attempts
        parsed, _parse_err = parser(raw)
        if parsed is not None:
            return parsed, total_attempts
    return None, total_attempts


def extract_notices(scene: str, unified: UnifiedStateView) -> list[str]:
    """Keyword chips: danger words, NPC names, inventory tokens."""
    notices: list[str] = []
    lower = scene.lower()
    danger_words = ("blood", "bone", "shadow", "rot", "curse", "blade", "fire", "hollow", "watching", "teeth")
    for w in danger_words:
        if w in lower and w not in notices:
            notices.append(w)
    for n in unified.world.npcs:
        if n.name and n.name.lower() in lower:
            notices.append(n.name)
    for inv in unified.player.inventory[:8]:
        base = inv.split(" x")[0].strip().lower()
        if len(base) > 2 and base in lower:
            notices.append(inv.split(" x")[0].strip())
    return notices[:10]


def _advance_time(current: str) -> str:
    cur = current.lower().strip()
    if cur in TIME_ORDER:
        i = TIME_ORDER.index(cur)
        return TIME_ORDER[(i + 1) % len(TIME_ORDER)]
    return "night"


def apply_effects_hint(hint: str, unified: UnifiedStateView) -> list[str]:
    applied: list[str] = []
    if not hint:
        return applied
    # Split on common separators
    tokens = re.split(r"[|;\n]+", hint)
    for raw in tokens:
        t = raw.strip().lower()
        if not t:
            continue
        m = re.match(r"hp\+(\d+)", t)
        if m:
            unified.player.hp = min(999, unified.player.hp + int(m.group(1)))
            applied.append("hp+")
            continue
        m = re.match(r"hp-(\d+)", t)
        if m:
            unified.player.hp = max(0, unified.player.hp - int(m.group(1)))
            applied.append("hp-")
            continue
        m = re.match(r"gold\+(\d+)", t)
        if m:
            unified.player.gold = max(0, unified.player.gold + int(m.group(1)))
            applied.append("gold+")
            continue
        m = re.match(r"gold-(\d+)", t)
        if m:
            unified.player.gold = max(0, unified.player.gold - int(m.group(1)))
            applied.append("gold-")
            continue
        m = re.match(r"danger\+(\d+)", t)
        if m:
            unified.world.danger_level = min(10, unified.world.danger_level + int(m.group(1)))
            applied.append("danger+")
            continue
        m = re.match(r"danger-(\d+)", t)
        if m:
            unified.world.danger_level = max(0, unified.world.danger_level - int(m.group(1)))
            applied.append("danger-")
            continue
        if t == "time+1" or t.startswith("time+"):
            unified.world.time = _advance_time(unified.world.time)
            applied.append("time+")
            continue
        if t.startswith("flag:"):
            key = raw.split(":", 1)[1].strip()
            if key:
                unified.player.flags[key] = True
                applied.append(f"flag:{key}")
            continue
        if t.startswith("item+:"):
            item = raw.split(":", 1)[1].strip()
            if item:
                summaries = list(unified.player.inventory)
                summaries.append(item)
                unified.player.inventory = summaries
                applied.append(f"item+:{item}")
            continue
        if t.startswith("item-:"):
            item = raw.split(":", 1)[1].strip().lower()
            if item:
                new_inv: list[str] = []
                for s in unified.player.inventory:
                    base = s.split(" x")[0].strip().lower()
                    if base != item:
                        new_inv.append(s)
                unified.player.inventory = new_inv
                applied.append(f"item-:{item}")
            continue
        if t.startswith("trust:"):
            rest = raw.split(":", 1)[1].strip()
            m2 = re.match(r"^(.+)([+-]\d+)$", rest.strip())
            if m2:
                name = m2.group(1).replace("_", " ").strip()
                delta = int(m2.group(2))
                for npc in unified.world.npcs:
                    if npc.name.lower() == name.lower():
                        npc.trust = max(-10, min(10, npc.trust + delta))
                        applied.append(f"trust:{npc.name}")
                        break
            continue
        if t.startswith("quest+:"):
            rest = raw.split(":", 1)[1].strip()
            title, _, desc = rest.partition("|")
            title = title.strip()
            desc = desc.strip() or "New objective"
            if title:
                new_id = max([int(q.get("id", 0)) for q in unified.quests.active + unified.quests.completed] or [0]) + 1
                unified.quests.active.append(
                    {
                        "id": new_id,
                        "title": title,
                        "description": desc,
                        "status": "active",
                        "created_at": _utc_now(),
                        "notes": [],
                    }
                )
                applied.append(f"quest+:{title}")
            continue
        if t.startswith("quest~:"):
            rest = raw.split(":", 1)[1].strip()
            parts = rest.split("|")
            if len(parts) >= 2:
                try:
                    qid = int(parts[0].strip())
                except ValueError:
                    continue
                status = parts[1].strip().lower()
                note = parts[2].strip() if len(parts) > 2 else ""
                new_active: list[dict[str, Any]] = []
                moved: dict[str, Any] | None = None
                for q in unified.quests.active:
                    if int(q.get("id", -1)) == qid:
                        qc = deepcopy(q)
                        qc["status"] = status
                        if note:
                            notes = qc.get("notes")
                            if not isinstance(notes, list):
                                notes = []
                            notes.append({"timestamp": _utc_now(), "text": note})
                            qc["notes"] = notes
                        moved = qc
                    else:
                        new_active.append(q)
                if moved:
                    unified.quests.active = new_active
                    if status == "completed":
                        unified.quests.completed.append(moved)
                    else:
                        unified.quests.active.append(moved)
                    applied.append(f"quest~:{qid}")
            continue
    return applied


def deterministic_turn_tick(unified: UnifiedStateView, choice_index: int | None) -> list[str]:
    """Always mutate state slightly so the situation changes even if LLM is vague."""
    applied: list[str] = []
    unified.world.turn += 1
    applied.append("turn+1")
    # Rotate time every 2 turns
    if unified.world.turn % 2 == 0:
        unified.world.time = _advance_time(unified.world.time)
        applied.append("time_tick")
    # Danger oscillates slightly with choice
    if choice_index is not None:
        delta = (choice_index % 3) - 1
        unified.world.danger_level = max(0, min(10, unified.world.danger_level + delta))
        applied.append("danger_tick")
    return applied


def run_turn(
    sf: SessionFiles,
    choice: str,
    free_text: str = "",
    roll_dice: bool = False,
    llm: LlamaCppClient | None = None,
    on_llm_attempt: Callable[[int, int, int], None] | None = None,
) -> tuple[str, list[str], UnifiedStateView, list[str], bool, int, bool, str | None, list[str]]:
    """
    Returns scene, choices, unified, effects_applied, llm_ok, llm_attempts, llm_fallback,
    skill_check_line, extra_notices.

    On LLM/parse failure: previous scene/choices and disk state are preserved (no backup story).
    """
    llm = llm or LlamaCppClient()
    runtime_cfg = get_provider_settings()
    unified = merge_to_unified(sf)
    lang = _normalize_lang(unified.player.flags.get("language"))

    messages = sf.history.get("messages", [])
    if not isinstance(messages, list):
        messages = []
    recent = []
    for m in messages[-6:]:
        if isinstance(m, dict):
            role = m.get("role", "")
            content = str(m.get("content", ""))[:400]
            recent.append(f"{role}: {content}")

    last_scene = str(sf.history.get("pending_scene", "") or "")
    action_block = _format_player_action(choice, free_text, roll_dice=roll_dice)
    sk_map = {k: int(unified.player.skills.get(k, 0)) for k in BASE_SKILLS}
    check_line, check_tag = _mixed_skill_check(
        action_block,
        lang,
        sk_map,
        unified.world.danger_level,
        force_roll=roll_dice,
    )
    context_block = _build_turn_context(last_scene, action_block, recent, check_line=check_line)

    llm_ok = True
    llm_fallback = False
    total_attempts = 0
    working = deepcopy(unified)
    stage_summaries: list[str] = []
    effects_applied: list[str] = []
    interaction_choices: list[str] = []

    def _compact_working() -> str:
        return json.dumps(compact_state_for_prompt(working), separators=(",", ":"), ensure_ascii=False)

    stage_specs: list[tuple[str, Callable[[dict[str, Any]], dict[str, Any]], Callable[[dict[str, Any], UnifiedStateView], list[str]], int]] = [
        ("world", _sanitize_world_stage, _apply_world_stage, 320),
        ("player", _sanitize_player_stage, _apply_player_stage, 280),
        ("interaction", _sanitize_interaction_stage, lambda stage, state: apply_effects_hint(str(stage.get("effects_hint", "")), state), 280),
        ("quests", _sanitize_quest_stage, _apply_quest_stage, 320),
    ]

    for stage_name, sanitize, apply_stage, max_tokens in stage_specs:
        if stage_name == "world":
            prompt = _build_world_stage_prompt(_compact_working(), context_block, lang, stage_summaries)
        elif stage_name == "player":
            prompt = _build_player_stage_prompt(_compact_working(), context_block, lang, stage_summaries)
        elif stage_name == "quests":
            prompt = _build_quest_stage_prompt(_compact_working(), context_block, lang, stage_summaries)
        else:
            prompt = _build_interaction_stage_prompt(_compact_working(), context_block, lang, stage_summaries)

        parsed_stage, att = _run_json_stage(
            llm,
            prompt,
            max_tokens=max_tokens,
            temperature=max(0.1, settings.llm_game_temperature - 0.05),
            parser=parse_llm_json_object,
            on_llm_attempt=on_llm_attempt,
        )
        total_attempts += att
        if not parsed_stage:
            continue
        stage = sanitize(parsed_stage)
        summary = str(stage.get("summary", "")).strip()
        if summary:
            stage_summaries.append(f"{stage_name}: {summary}")
        if stage_name == "interaction":
            interaction_choices = [str(c).strip() for c in stage.get("choices", []) if str(c).strip()][:4]
        effects_applied.extend(apply_stage(stage, working))

    story_mode = "mad" if _is_mad_turn(working.world.turn) else "light"

    auto_quest_effects = _auto_complete_quests(working, action_block, last_scene, lang)
    if auto_quest_effects:
        effects_applied.extend(auto_quest_effects)

    final_prompt = _build_final_summary_prompt(
        _compact_working(),
        context_block,
        lang,
        story_mode,
        stage_summaries,
        interaction_choices,
    )
    parsed, att = _run_json_stage(
        llm,
        final_prompt,
        max_tokens=int(runtime_cfg.get("llm_game_max_tokens", settings.llm_game_max_tokens)),
        temperature=settings.llm_game_temperature,
        parser=parse_llm_game_response,
        on_llm_attempt=on_llm_attempt,
    )
    total_attempts += att

    if not parsed:
        llm_ok = False
        llm_fallback = False
        prev_scene = str(sf.history.get("pending_scene", "") or "")
        prev_raw = sf.history.get("pending_choices") or []
        prev_choices = (
            [str(c) for c in prev_raw if str(c).strip()] if isinstance(prev_raw, list) else []
        )
        unified_unchanged = merge_to_unified(sf)
        return (
            prev_scene,
            prev_choices,
            unified_unchanged,
            [],
            llm_ok,
            total_attempts,
            llm_fallback,
            check_line,
            [_model_failed_notice(lang)],
        )

    scene = str(parsed["scene"])
    choices = list(parsed["choices"])
    post_scene_quest_effects = _auto_complete_quests(working, action_block, scene, lang)
    if post_scene_quest_effects:
        effects_applied.extend(post_scene_quest_effects)

    # Choice index: match pressed button to previous pending choices
    prev_choices = sf.history.get("pending_choices") or []
    choice_idx = None
    c_only = (choice or "").strip()
    if isinstance(prev_choices, list) and c_only:
        try:
            norm = c_only.lower()
            for i, c in enumerate(prev_choices):
                if str(c).strip().lower() == norm:
                    choice_idx = i
                    break
        except Exception:
            pass

    unified = working
    eff = list(effects_applied)
    if check_tag:
        eff.append(check_tag)
    eff.extend(deterministic_turn_tick(unified, choice_idx))

    user_log = action_block[:2000]
    messages.append({"role": "user", "content": user_log, "timestamp": _utc_now()})
    messages.append({"role": "assistant", "content": scene[:4000], "timestamp": _utc_now()})

    sf.history = {
        "messages": messages[-80:],
        "pending_scene": scene,
        "pending_choices": choices,
        "pending_scene_image": "",
        "pending_scene_image_prompt": "",
    }

    apply_unified_to_files(sf, unified)
    sf.save()

    return scene, choices, unified, eff, llm_ok, total_attempts, llm_fallback, check_line, []


def bootstrap_if_empty(
    sf: SessionFiles,
    language: str | None = None,
    player_name: str | None = None,
    player_backstory: str | None = None,
    player_appearance: str | None = None,
    world_location: str | None = None,
    world_premise: str | None = None,
) -> None:
    """Ensure minimal files exist for new sessions."""
    lang = _normalize_lang(language)
    seed_name = (player_name or "").strip() or "Wanderer"
    seed_backstory = (player_backstory or "").strip()
    seed_appearance = (player_appearance or "").strip()
    seed_location = (world_location or "").strip() or "Ashen Gate"
    seed_premise = (world_premise or "").strip()
    seed_setting = _opening_setting(seed_location, seed_premise)
    opening_scene, opening_choices = _opening_seed_payload(lang, seed_name, seed_location, seed_premise)
    quest_title, quest_desc = _rest_quest_seed(lang, seed_setting)
    derived_skills = _skills_from_backstory(seed_backstory)
    if seed_setting == "forest":
        warden = (
            {"name": "Странник у костра", "trust": 0, "hidden_intent": "скрывает, откуда знает вашу дорогу"}
            if lang == "ru"
            else {"name": "Wayfarer by the fire", "trust": 0, "hidden_intent": "won't say how they knew your route"}
        )
    elif seed_setting == "water":
        warden = (
            {"name": "Старший причала", "trust": 0, "hidden_intent": "считает швартовые и чужие лица"}
            if lang == "ru"
            else {"name": "Dock marshal", "trust": 0, "hidden_intent": "counts ropes and strangers alike"}
        )
    else:
        warden = (
            {"name": "Привратник", "trust": 0, "hidden_intent": "ищет слабое место в словах"}
            if lang == "ru"
            else {"name": "Gate Warden", "trust": 0, "hidden_intent": "tests the desperate"}
        )
    starter_item = (
        {"name": "Ржавый кинжал", "quantity": 1, "description": "", "added_at": _utc_now()}
        if lang == "ru"
        else {"name": "Rusty dagger", "quantity": 1, "description": "", "added_at": _utc_now()}
    )
    changed = False
    if not sf.main_character:
        sf.main_character = {
            "name": seed_name,
            "description": seed_appearance
            or ("Hollow-eyed and careful" if lang != "ru" else "С внимательным взглядом и осторожными руками"),
            "backstory": seed_backstory,
            "hp": 100,
            "gold": 0,
            "status": "steady",
            "flags": {"language": lang},
            "skills": derived_skills,
            "created_at": _utc_now(),
        }
        changed = True
    elif isinstance(sf.main_character, dict):
        flags = sf.main_character.get("flags")
        if not isinstance(flags, dict):
            flags = {}
        if not flags.get("language"):
            flags["language"] = lang
            sf.main_character["flags"] = flags
            changed = True
        if seed_backstory and not sf.main_character.get("backstory"):
            sf.main_character["backstory"] = seed_backstory
            changed = True
        if seed_appearance and not sf.main_character.get("description"):
            sf.main_character["description"] = seed_appearance
            changed = True
        if seed_name and (not sf.main_character.get("name") or sf.main_character.get("name") == "Wanderer"):
            sf.main_character["name"] = seed_name
            changed = True
        sk0 = sf.main_character.get("skills")
        if not isinstance(sk0, dict) or len(sk0) == 0:
            sf.main_character["skills"] = _skills_from_backstory(str(sf.main_character.get("backstory", "")))
            changed = True
    if not sf.world or (isinstance(sf.world, dict) and not str(sf.world.get("location", "")).strip()):
        sf.world = {
            "location": seed_location,
            "danger_level": 2,
            "time": "night",
            "secrets": [
                seed_premise
                or (
                    (
                        "на коре старого дуба — свежая засохшая кровь в форме руны"
                        if lang == "ru"
                        else "fresh blood dried in a rune-shape on an old oak's bark"
                    )
                    if seed_setting == "forest"
                    else (
                        "под причалом слышен металлический стук, когда прилив поднимается"
                        if lang == "ru"
                        else "a metallic knock under the pier when the tide lifts"
                    )
                    if seed_setting == "water"
                    else (
                        "царапина в виде сигила под порогом"
                        if lang == "ru"
                        else "a sigil scratched under the lintel"
                    )
                )
            ],
            "npcs": [warden],
            "ascii_map": (
                DEFAULT_BOOTSTRAP_ASCII_MAP_RU
                if lang == "ru"
                else DEFAULT_BOOTSTRAP_ASCII_MAP
            ),
            "turn": 0,
        }
        changed = True
    if not isinstance(sf.inventory, list) or len(sf.inventory) == 0:
        sf.inventory = [starter_item]
        changed = True
    if not isinstance(sf.quests, list) or len(sf.quests) == 0:
        sf.quests = [
            {
                "id": 1,
                "title": quest_title,
                "description": quest_desc,
                "status": "active",
                "created_at": _utc_now(),
                "notes": [],
            }
        ]
        changed = True
    if not isinstance(sf.history, dict):
        sf.history = {
            "messages": [],
            "pending_scene": "",
            "pending_choices": [],
            "pending_scene_image": "",
            "pending_scene_image_prompt": "",
        }
        changed = True
    hist = sf.history
    if not hist.get("messages"):
        hist = {
            "messages": [],
            "pending_scene": hist.get("pending_scene") or opening_scene,
            "pending_choices": hist.get("pending_choices") or opening_choices,
            "pending_scene_image": str(hist.get("pending_scene_image", "") or ""),
            "pending_scene_image_prompt": str(hist.get("pending_scene_image_prompt", "") or ""),
        }
        sf.history = hist
        changed = True
    elif not str(hist.get("pending_scene", "")).strip():
        hist["pending_scene"] = opening_scene
        hist.setdefault(
            "pending_choices",
            opening_choices,
        )
        hist.setdefault("pending_scene_image", "")
        hist.setdefault("pending_scene_image_prompt", "")
        sf.history = hist
        changed = True
    if changed:
        sf.save()
