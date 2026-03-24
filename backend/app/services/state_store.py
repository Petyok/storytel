"""
Load/save game state from sessions/{id}/*.json as single source of truth.
Supports legacy shapes from storyteller_v2 (world key/value wrappers, plain history list).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.schemas import NPCState, PlayerView, QuestsView, UnifiedStateView, WorldView

BASE_SKILLS: tuple[str, ...] = (
    "athletics",
    "stealth",
    "perception",
    "persuasion",
    "survival",
    "arcana",
    "medicine",
    "insight",
    "intimidation",
    "investigation",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _world_value(world: dict[str, Any], key: str, default: str = "") -> str:
    raw = world.get(key)
    if isinstance(raw, dict) and "value" in raw:
        return str(raw.get("value", default))
    if raw is None:
        return default
    return str(raw)


def _normalize_main_character(raw: dict[str, Any]) -> dict[str, Any]:
    hp = raw.get("hp")
    if hp is None:
        hp = raw.get("health", 100)
    try:
        hp = int(hp)
    except (TypeError, ValueError):
        hp = 100
    gold = raw.get("gold", 0)
    try:
        gold = int(gold)
    except (TypeError, ValueError):
        gold = 0
    flags = raw.get("flags")
    if not isinstance(flags, dict):
        flags = {}
    status = str(raw.get("status", "steady"))
    sk_in = raw.get("skills")
    skills: dict[str, int] = {}
    if isinstance(sk_in, dict):
        for k in BASE_SKILLS:
            try:
                skills[k] = max(-5, min(5, int(sk_in.get(k, 0))))
            except (TypeError, ValueError):
                skills[k] = 0
    else:
        for k in BASE_SKILLS:
            skills[k] = 0
    return {
        "name": str(raw.get("name", "Wanderer")),
        "description": str(raw.get("description", "")),
        "backstory": str(raw.get("backstory", "")),
        "hp": max(0, min(999, hp)),
        "gold": max(0, gold),
        "status": status,
        "flags": flags,
        "skills": skills,
        "created_at": raw.get("created_at"),
    }


def _is_legacy_world(raw: dict[str, Any]) -> bool:
    """Legacy storyteller_v2 shape: multiple keys mapping to {value, updated_at}."""
    if not raw:
        return False
    dict_vals = [v for v in raw.values() if isinstance(v, dict)]
    if len(dict_vals) < 2:
        return False
    return all("value" in v for v in dict_vals)


def _normalize_world(raw: dict[str, Any]) -> dict[str, Any]:
    if not _is_legacy_world(raw):
        loc = raw.get("location") or raw.get("current_location") or ""
        if isinstance(loc, dict):
            loc = str(loc.get("value", ""))
        danger = raw.get("danger_level", 1)
        try:
            danger = int(danger)
        except (TypeError, ValueError):
            danger = 1
        time_s = str(raw.get("time", "night"))
        secrets = raw.get("secrets", [])
        if not isinstance(secrets, list):
            secrets = []
        secrets = [str(s) for s in secrets]
        npcs_raw = raw.get("npcs", [])
        npcs: list[dict[str, Any]] = []
        if isinstance(npcs_raw, list):
            for n in npcs_raw:
                if isinstance(n, dict):
                    try:
                        tr = int(n.get("trust", 0))
                    except (TypeError, ValueError):
                        tr = 0
                    npcs.append(
                        {
                            "name": str(n.get("name", "")),
                            "trust": tr,
                            "hidden_intent": str(n.get("hidden_intent", "")),
                        }
                    )
        turn = raw.get("turn", 0)
        try:
            turn = int(turn)
        except (TypeError, ValueError):
            turn = 0
        return {
            "location": str(loc) if loc else _world_value(raw, "Setting", "unknown"),
            "danger_level": max(0, min(10, danger)),
            "time": time_s,
            "secrets": secrets,
            "npcs": npcs,
            "ascii_map": str(raw.get("ascii_map", "")),
            "turn": turn,
            "extra": {k: v for k, v in raw.items() if k not in {"location", "danger_level", "time", "secrets", "npcs", "ascii_map", "turn"}},
        }

    location = _world_value(raw, "Setting") or _world_value(raw, "Location") or "unknown"
    danger_s = _world_value(raw, "DangerLevel") or _world_value(raw, "danger_level") or "1"
    try:
        danger = int(danger_s)
    except ValueError:
        danger = 1
    time_s = _world_value(raw, "Time") or _world_value(raw, "time") or "night"
    return {
        "location": location,
        "danger_level": max(0, min(10, danger)),
        "time": time_s,
        "secrets": [],
        "npcs": [],
        "ascii_map": "",
        "turn": 0,
        "extra": dict(raw),
    }


def _normalize_history(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        messages = raw.get("messages")
        if not isinstance(messages, list):
            messages = raw.get("turns") or []
        return {
            "messages": messages if isinstance(messages, list) else [],
            "pending_scene": str(raw.get("pending_scene", raw.get("last_scene", ""))),
            "pending_choices": list(raw.get("pending_choices", raw.get("last_choices", [])))
            if isinstance(raw.get("pending_choices", raw.get("last_choices", [])), list)
            else [],
            "pending_scene_image": str(raw.get("pending_scene_image", raw.get("last_scene_image", ""))),
            "pending_scene_image_prompt": str(
                raw.get("pending_scene_image_prompt", raw.get("last_scene_image_prompt", ""))
            ),
        }
    if isinstance(raw, list):
        return {
            "messages": raw,
            "pending_scene": "",
            "pending_choices": [],
            "pending_scene_image": "",
            "pending_scene_image_prompt": "",
        }
    return {
        "messages": [],
        "pending_scene": "",
        "pending_choices": [],
        "pending_scene_image": "",
        "pending_scene_image_prompt": "",
    }


def _inventory_summaries(inv: list[Any]) -> list[str]:
    out: list[str] = []
    for it in inv:
        if isinstance(it, dict):
            name = str(it.get("name", "item"))
            qty = it.get("quantity", 1)
            try:
                q = int(qty)
            except (TypeError, ValueError):
                q = 1
            out.append(f"{name} x{q}" if q != 1 else name)
        else:
            out.append(str(it))
    return out


@dataclass
class SessionFiles:
    session_id: str
    base_dir: Path
    main_character: dict[str, Any] = field(default_factory=dict)
    world: dict[str, Any] = field(default_factory=dict)
    history: dict[str, Any] = field(default_factory=dict)
    inventory: list[Any] = field(default_factory=list)
    quests: list[Any] = field(default_factory=list)

    @property
    def session_dir(self) -> Path:
        return self.base_dir / self.session_id

    def paths(self) -> dict[str, Path]:
        d = self.session_dir
        return {
            "main_character": d / "main_character.json",
            "world": d / "world.json",
            "history": d / "history.json",
            "inventory": d / "inventory.json",
            "quests": d / "quests.json",
        }

    def load(self) -> None:
        p = self.paths()
        self.main_character = _read_json(p["main_character"], {})
        self.world = _read_json(p["world"], {})
        self.history = _normalize_history(_read_json(p["history"], []))
        self.inventory = _read_json(p["inventory"], [])
        if not isinstance(self.inventory, list):
            self.inventory = []
        self.quests = _read_json(p["quests"], [])
        if not isinstance(self.quests, list):
            self.quests = []

    def save(self) -> None:
        p = self.paths()
        _write_json(p["main_character"], self.main_character)
        _write_json(p["world"], self.world)
        _write_json(p["history"], self.history)
        _write_json(p["inventory"], self.inventory)
        _write_json(p["quests"], self.quests)


def merge_to_unified(sf: SessionFiles) -> UnifiedStateView:
    mc = _normalize_main_character(sf.main_character if isinstance(sf.main_character, dict) else {})
    w = _normalize_world(sf.world if isinstance(sf.world, dict) else {})

    inv_summaries = _inventory_summaries(sf.inventory)

    active: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    for q in sf.quests:
        if not isinstance(q, dict):
            continue
        st = str(q.get("status", "active")).lower()
        if st in {"completed", "failed"}:
            completed.append(q)
        else:
            active.append(q)

    npcs = [NPCState(**n) for n in w.get("npcs", []) if isinstance(n, dict)]

    sk_map = mc.get("skills") if isinstance(mc.get("skills"), dict) else {}
    skills_out: dict[str, int] = {}
    for k in BASE_SKILLS:
        try:
            skills_out[k] = max(-5, min(5, int(sk_map.get(k, 0))))
        except (TypeError, ValueError):
            skills_out[k] = 0

    player = PlayerView(
        hp=mc["hp"],
        gold=mc["gold"],
        status=mc["status"],
        inventory=inv_summaries,
        flags=mc["flags"],
        name=mc["name"],
        skills=skills_out,
        backstory=str(mc.get("backstory", "")),
        appearance=str(mc.get("description", "")),
    )
    world = WorldView(
        location=w["location"],
        danger_level=w["danger_level"],
        time=w["time"],
        secrets=list(w.get("secrets", [])),
        npcs=npcs,
        ascii_map=w.get("ascii_map", ""),
        turn=int(w.get("turn", 0)),
    )
    quests = QuestsView(active=active, completed=completed)
    return UnifiedStateView(player=player, world=world, quests=quests)


def apply_unified_to_files(sf: SessionFiles, unified: UnifiedStateView) -> None:
    """Write unified view back into the five JSON shapes."""
    p = unified.player
    w = unified.world
    prev_mc = sf.main_character if isinstance(sf.main_character, dict) else {}
    sf.main_character = {
        "name": p.name,
        "description": p.appearance,
        "backstory": p.backstory,
        "hp": p.hp,
        "gold": p.gold,
        "status": p.status,
        "flags": dict(p.flags),
        "skills": {k: int(p.skills.get(k, 0)) for k in BASE_SKILLS},
        "created_at": prev_mc.get("created_at") or _utc_now(),
        "portrait_image": prev_mc.get("portrait_image", ""),
        "portrait_prompt": prev_mc.get("portrait_prompt", ""),
        "portrait_generated_turn": prev_mc.get("portrait_generated_turn", -1),
    }

    prev_world = sf.world if isinstance(sf.world, dict) else {}
    sf.world = {
        "location": w.location,
        "danger_level": w.danger_level,
        "time": w.time,
        "secrets": list(w.secrets),
        "npcs": [{"name": n.name, "trust": n.trust, "hidden_intent": n.hidden_intent} for n in w.npcs],
        "ascii_map": w.ascii_map,
        "turn": w.turn,
        "map_image": prev_world.get("map_image", ""),
        "map_image_prompt": prev_world.get("map_image_prompt", ""),
        "map_generated_turn": prev_world.get("map_generated_turn", -1),
        "map_generated_location": prev_world.get("map_generated_location", ""),
    }

    # Rebuild inventory list from summaries is lossy; keep file inventory in sync by only updating quantities we can parse
    _sync_inventory_from_summaries(sf, p.inventory)

    new_quests: list[dict[str, Any]] = []
    for q in unified.quests.active:
        new_quests.append(dict(q))
    for q in unified.quests.completed:
        qc = dict(q)
        qc["status"] = str(qc.get("status", "completed")).lower() or "completed"
        new_quests.append(qc)
    sf.quests = new_quests


def _sync_inventory_from_summaries(sf: SessionFiles, summaries: list[str]) -> None:
    """Best-effort: if engine changed inventory list, merge names; preserve extra item fields."""
    by_name: dict[str, dict[str, Any]] = {}
    for it in sf.inventory:
        if isinstance(it, dict):
            by_name[str(it.get("name", "")).lower()] = dict(it)

    new_list: list[dict[str, Any]] = []
    for s in summaries:
        s = s.strip()
        if " x" in s.lower():
            parts = s.rsplit(" x", 1)
            name = parts[0].strip()
            try:
                qty = int(parts[1].strip())
            except ValueError:
                qty = 1
        else:
            name = s
            qty = 1
        key = name.lower()
        if key in by_name:
            row = dict(by_name[key])
            row["quantity"] = qty
            new_list.append(row)
        else:
            new_list.append(
                {
                    "name": name,
                    "quantity": qty,
                    "description": "",
                    "added_at": _utc_now(),
                }
            )
    sf.inventory = new_list


def list_session_ids(sessions_dir: Path) -> list[str]:
    if not sessions_dir.exists():
        return []
    return sorted(d.name for d in sessions_dir.iterdir() if d.is_dir())


def load_session(session_id: str, sessions_dir: Path) -> SessionFiles:
    sf = SessionFiles(session_id=session_id, base_dir=sessions_dir)
    sf.session_dir.mkdir(parents=True, exist_ok=True)
    sf.load()
    return sf


SESSION_JSON_FILES: tuple[str, ...] = (
    "main_character.json",
    "world.json",
    "history.json",
    "inventory.json",
    "quests.json",
)


def validate_session_id(session_id: str) -> str:
    import re

    sid = session_id.strip()
    if not sid or len(sid) > 64:
        raise ValueError("invalid session id length or empty")
    if ".." in sid or "/" in sid or "\\" in sid:
        raise ValueError("invalid session id characters")
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", sid):
        raise ValueError("invalid session id format")
    return sid


def wipe_session_json_files(session_dir: Path) -> None:
    """Remove canonical session JSON files (directory may remain)."""
    for name in SESSION_JSON_FILES:
        p = session_dir / name
        if p.exists():
            p.unlink()
