"""
Turn loop: compact prompt -> LLM JSON -> validate -> deterministic state updates.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.models.schemas import UnifiedStateView
from app.services.llm_client import LlamaCppClient, parse_llm_game_response
from app.services.state_store import SessionFiles, apply_unified_to_files, merge_to_unified

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


def _fallback_payload(lang: str) -> dict[str, Any]:
    if lang == "ru":
        return {
            "scene": "Коридор дрожит, из щелей тянет золой и шепотом. Впереди что-то сдвинулось — слишком осмысленно для ветра. Твой выбор уже отозвался, и тьма отвечает давлением в спину.",
            "choices": [
                "Идти вперед, держа оружие наготове",
                "Замереть и прислушаться к шагам",
                "Искать обходной путь",
                "Окликнуть неизвестного и спровоцировать ответ",
            ],
            "effects_hint": "danger+1|time+1",
        }
    return {
        "scene": "The corridor shifts; a draft carries ash and whispers. Something has moved ahead—too deliberate to be wind. Your choice still echoes, and the dark answers with pressure at your back.",
        "choices": [
            "Press forward, blade ready",
            "Listen and mark what follows",
            "Search for another path",
            "Call out and force a reaction",
        ],
        "effects_hint": "danger+1|time+1",
    }


def _opening_seed_payload(lang: str, player_name: str, world_location: str) -> tuple[str, list[str], str]:
    if lang == "ru":
        scene = (
            f"{player_name} останавливается у '{world_location}'. Холодный воздух идёт из камня, "
            "будто за стеной дышит что-то живое. На пороге заметен свежий след золы, но второго шага нет."
        )
        choices = [
            "Проверить след и осмотреть порог",
            "Позвать стража и предложить сделку",
            "Обойти ворота, ища тайный проход",
        ]
        quest_title = "Переступить порог"
    else:
        scene = (
            f"{player_name} pauses at '{world_location}'. Cold air leaks through the stone as if something behind it is breathing. "
            "A fresh ash print marks the threshold, but there is no second step."
        )
        choices = [
            "Inspect the ash print and threshold",
            "Call for the warden and offer a bargain",
            "Circle the gate and search for a hidden way in",
        ]
        quest_title = "Cross the threshold"
    return scene, choices, quest_title


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SYSTEM_PROMPT_TEMPLATE = """You are a dark fantasy game master.

Rules:
- Never write passive descriptions only
- NPCs must be proactive
- Every turn must change the situation
- Every action must have consequences
- Include at least one hidden element (do not reveal it plainly in scene; put a clue in effects_hint only)
- End the JSON with 2-4 player choices (short labels, actionable)

Use current game state:
{state_json}

Respond ONLY with a single JSON object (no markdown, no prose outside JSON):
{{"scene":"...","choices":["...","..."],"effects_hint":"short hidden note for engine; optional tags: hp+/-N gold+/-N danger+/-N time+1 flag:name item+:Name item-:Name trust:NPCName+/-N quest+:title|desc quest~:id|completed|note"}}"""


def compact_state_for_prompt(u: UnifiedStateView) -> dict[str, Any]:
    inv = u.player.inventory[:12]
    active_q = u.quests.active[:4]
    npcs = [{"n": n.name, "t": n.trust, "h": (n.hidden_intent[:40] + "…") if len(n.hidden_intent) > 40 else n.hidden_intent} for n in u.world.npcs[:6]]
    return {
        "player": {
            "name": u.player.name,
            "hp": u.player.hp,
            "gold": u.player.gold,
            "status": u.player.status,
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
        "quests": [{"id": q.get("id"), "t": q.get("title"), "s": q.get("status")} for q in active_q],
    }


def build_user_prompt(last_scene: str, choice: str, recent_lines: list[str]) -> str:
    parts = []
    if recent_lines:
        parts.append("Recent:\n" + "\n".join(recent_lines[-4:]))
    if last_scene:
        parts.append("Previous scene:\n" + last_scene[:800])
    parts.append(f"Player choice:\n{choice.strip()[:500]}")
    parts.append("Narrate the next beat. Output JSON only.")
    return "\n\n".join(parts)


def build_full_prompt(state_json: str, user_block: str, lang: str) -> str:
    system = SYSTEM_PROMPT_TEMPLATE.format(state_json=state_json)
    system = f"{system}\nLanguage rule: {_lang_instruction(lang)}"
    full = system + "\n\n" + user_block
    if len(full) > settings.max_prompt_chars:
        full = full[: settings.max_prompt_chars] + "\n\n[truncated]"
    return full


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
    llm: LlamaCppClient | None = None,
) -> tuple[str, list[str], UnifiedStateView, list[str], bool]:
    """
    Returns scene, choices, new unified state, effects_applied, llm_ok.
    """
    llm = llm or LlamaCppClient()
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
    user_block = build_user_prompt(last_scene, choice, recent)
    state_json = json.dumps(compact_state_for_prompt(unified), separators=(",", ":"), ensure_ascii=False)
    prompt = build_full_prompt(state_json, user_block, lang)

    llm_ok = True
    raw = ""
    try:
        raw = llm.complete(prompt)
    except Exception:
        llm_ok = False
        raw = ""

    parsed, err = parse_llm_game_response(raw)
    if not parsed:
        llm_ok = False
        parsed = _fallback_payload(lang)

    scene = str(parsed["scene"])
    choices = list(parsed["choices"])
    hint = str(parsed.get("effects_hint", ""))

    # Choice index: match choice string to previous pending choices if possible
    prev_choices = sf.history.get("pending_choices") or []
    choice_idx = None
    if isinstance(prev_choices, list):
        try:
            norm = choice.strip().lower()
            for i, c in enumerate(prev_choices):
                if str(c).strip().lower() == norm:
                    choice_idx = i
                    break
        except Exception:
            pass

    eff = apply_effects_hint(hint, unified)
    eff.extend(deterministic_turn_tick(unified, choice_idx))

    # Append messages
    messages.append({"role": "user", "content": choice.strip()[:2000], "timestamp": _utc_now()})
    messages.append({"role": "assistant", "content": scene[:4000], "timestamp": _utc_now()})

    sf.history = {
        "messages": messages[-80:],
        "pending_scene": scene,
        "pending_choices": choices,
    }

    apply_unified_to_files(sf, unified)
    sf.save()

    notices = extract_notices(scene, unified)
    return scene, choices, unified, eff, llm_ok


def bootstrap_if_empty(
    sf: SessionFiles,
    language: str | None = None,
    player_name: str | None = None,
    player_backstory: str | None = None,
    world_location: str | None = None,
    world_premise: str | None = None,
) -> None:
    """Ensure minimal files exist for new sessions."""
    lang = _normalize_lang(language)
    seed_name = (player_name or "").strip() or "Wanderer"
    seed_backstory = (player_backstory or "").strip()
    seed_location = (world_location or "").strip() or "Ashen Gate"
    seed_premise = (world_premise or "").strip()
    opening_scene, opening_choices, default_quest_title = _opening_seed_payload(lang, seed_name, seed_location)
    changed = False
    if not sf.main_character:
        sf.main_character = {
            "name": seed_name,
            "description": "Hollow-eyed and careful",
            "backstory": seed_backstory,
            "hp": 100,
            "gold": 0,
            "status": "steady",
            "flags": {"language": lang},
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
        if seed_name and (not sf.main_character.get("name") or sf.main_character.get("name") == "Wanderer"):
            sf.main_character["name"] = seed_name
            changed = True
    if not sf.world or (isinstance(sf.world, dict) and not str(sf.world.get("location", "")).strip()):
        sf.world = {
            "location": seed_location,
            "danger_level": 2,
            "time": "night",
            "secrets": [seed_premise or ("царапина в виде сигила под порогом" if lang == "ru" else "a sigil scratched under the lintel")],
            "npcs": [{"name": "Gate Warden", "trust": 0, "hidden_intent": "tests the desperate"}],
            "ascii_map": DEFAULT_BOOTSTRAP_ASCII_MAP_RU if lang == "ru" else DEFAULT_BOOTSTRAP_ASCII_MAP,
            "turn": 0,
        }
        changed = True
    if not isinstance(sf.inventory, list) or len(sf.inventory) == 0:
        sf.inventory = [{"name": "Rusty dagger", "quantity": 1, "description": "", "added_at": _utc_now()}]
        changed = True
    if not isinstance(sf.quests, list) or len(sf.quests) == 0:
        sf.quests = [
            {
                "id": 1,
                "title": default_quest_title,
                "description": "Найди путь за врата и не потеряй себя." if lang == "ru" else "Find a way past the gate without losing yourself.",
                "status": "active",
                "created_at": _utc_now(),
                "notes": [],
            }
        ]
        changed = True
    if not isinstance(sf.history, dict):
        sf.history = {"messages": [], "pending_scene": "", "pending_choices": []}
        changed = True
    hist = sf.history
    if not hist.get("messages"):
        hist = {
            "messages": [],
            "pending_scene": hist.get("pending_scene") or opening_scene,
            "pending_choices": hist.get("pending_choices") or opening_choices,
        }
        sf.history = hist
        changed = True
    elif not str(hist.get("pending_scene", "")).strip():
        hist["pending_scene"] = opening_scene
        hist.setdefault(
            "pending_choices",
            opening_choices,
        )
        sf.history = hist
        changed = True
    if changed:
        sf.save()
