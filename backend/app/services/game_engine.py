"""
Turn loop: compact prompt -> LLM JSON -> validate -> deterministic state updates.
"""

from __future__ import annotations

import json
import re
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.models.schemas import UnifiedStateView
from app.services.llm_client import LlamaCppClient, parse_llm_game_response
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


def _opening_seed_payload(lang: str, player_name: str, world_location: str) -> tuple[str, list[str]]:
    """Grounded opening oriented toward finding rest / a tavern."""
    if lang == "ru":
        scene = (
            f"{player_name} сворачивает к «{world_location}». Улица редкая; из-за угла тянет дымом и жаром — "
            "где-то готовят еду. Дверь трактира приоткрыта, но шаги позади не совпадают с вашим темпом."
        )
        choices = ["Зайти в трактир", "Остановиться и осмотреться", "Скрыться в переулке"]
    else:
        scene = (
            f"{player_name} reaches '{world_location}'. The street is sparse; smoke and heat drift from a side yard—someone is cooking. "
            "A tavern door stands ajar, but the footsteps behind you don't match your pace."
        )
        choices = ["Enter the tavern", "Pause and scan the street", "Slip into a side alley"]
    return scene, choices


def _rest_quest_seed(lang: str) -> tuple[str, str]:
    if lang == "ru":
        return (
            "Найти место отдыха",
            "Узнай, где можно переждать ночь: трактир, постоялый двор или укромный угол без лишних вопросов.",
        )
    return (
        "Find a place to rest",
        "Learn where you can wait out the night—a tavern, an inn, or a quiet corner without too many questions.",
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


def _format_player_action(choice: str, free_text: str) -> str:
    c = (choice or "").strip()
    f = (free_text or "").strip()
    parts: list[str] = []
    if c:
        parts.append(f"Chosen button: {c}")
    if f:
        parts.append(f"Player says/does: {f}")
    return "\n".join(parts)


def _mixed_skill_check(action_text: str, lang: str, skills: dict[str, int], danger: int) -> tuple[str | None, str | None]:
    """Returns (prompt_line, short_tag for effects)."""
    t = (action_text or "").lower()
    if len(t) < 6:
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
    if not picked:
        return None, None
    mod = int(skills.get(picked, 0))
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

Respond ONLY with a single JSON object (no markdown, no prose outside JSON):
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
    active_q = u.quests.active[:4]
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
        "quests": [{"id": q.get("id"), "t": q.get("title"), "s": q.get("status")} for q in active_q],
    }


def build_user_prompt(last_scene: str, action_block: str, recent_lines: list[str], check_line: str | None = None) -> str:
    parts = []
    if recent_lines:
        parts.append("Recent:\n" + "\n".join(recent_lines[-4:]))
    if last_scene:
        parts.append("Previous scene:\n" + last_scene[:800])
    if check_line:
        parts.append(check_line)
    parts.append(f"Player action:\n{action_block.strip()[:900]}")
    parts.append("Narrate the next beat. Output JSON only.")
    return "\n\n".join(parts)


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
    llm: LlamaCppClient | None = None,
) -> tuple[str, list[str], UnifiedStateView, list[str], bool, int, bool, str | None]:
    """
    Returns scene, choices, unified, effects_applied, llm_ok, llm_attempts, llm_fallback, skill_check_line.
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
    action_block = _format_player_action(choice, free_text)
    sk_map = {k: int(unified.player.skills.get(k, 0)) for k in BASE_SKILLS}
    check_line, check_tag = _mixed_skill_check(action_block, lang, sk_map, unified.world.danger_level)
    user_block = build_user_prompt(last_scene, action_block, recent, check_line=check_line)

    story_mode = "mad" if _is_mad_turn(unified.world.turn) else "light"
    state_json = json.dumps(compact_state_for_prompt(unified), separators=(",", ":"), ensure_ascii=False)
    prompt = build_full_prompt(state_json, user_block, lang, story_mode)

    llm_ok = True
    llm_fallback = False
    total_attempts = 0
    parsed: dict[str, Any] | None = None
    raw = ""

    for _wave in range(3):
        chunk, att, _http_err = llm.complete_with_retries(prompt)
        total_attempts += att
        raw = chunk
        parsed, _perr = parse_llm_game_response(raw)
        if parsed:
            break

    if not parsed:
        llm_ok = False
        llm_fallback = True
        parsed = _fallback_payload(lang)

    scene = str(parsed["scene"])
    choices = list(parsed["choices"])
    hint = str(parsed.get("effects_hint", ""))

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

    eff = apply_effects_hint(hint, unified)
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
    }

    apply_unified_to_files(sf, unified)
    sf.save()

    notices = extract_notices(scene, unified)
    return scene, choices, unified, eff, llm_ok, total_attempts, llm_fallback, check_line


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
    opening_scene, opening_choices = _opening_seed_payload(lang, seed_name, seed_location)
    quest_title, quest_desc = _rest_quest_seed(lang)
    derived_skills = _skills_from_backstory(seed_backstory)
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
            "description": "Hollow-eyed and careful" if lang != "ru" else "С внимательным взглядом и осторожными руками",
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
                    "царапина в виде сигила под порогом"
                    if lang == "ru"
                    else "a sigil scratched under the lintel"
                )
            ],
            "npcs": [warden],
            "ascii_map": DEFAULT_BOOTSTRAP_ASCII_MAP_RU if lang == "ru" else DEFAULT_BOOTSTRAP_ASCII_MAP,
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
