import json
import queue
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.models.schemas import (
    ActionRequest,
    ActionResponse,
    CreateSessionRequest,
    SessionGetResponse,
    SessionsListResponse,
)
from app.services import game_engine
from app.services.game_engine import bootstrap_if_empty, extract_notices, run_turn
from app.services.state_store import (
    list_session_ids,
    load_session,
    merge_to_unified,
    validate_session_id,
    wipe_session_json_files,
)

router = APIRouter()


def _run_action_core(session_id: str, body: ActionRequest) -> ActionResponse:
    sf = load_session(session_id, settings.sessions_dir)
    bootstrap_if_empty(sf)
    sf.load()
    (
        scene,
        choices,
        unified,
        eff,
        llm_ok,
        llm_attempts,
        llm_fallback,
        sk_line,
        extra_notices,
    ) = run_turn(
        sf,
        (body.choice or "").strip(),
        (body.free_text or "").strip(),
        roll_dice=bool(body.roll_dice),
    )
    notices = extract_notices(scene, unified) + extra_notices
    return ActionResponse(
        session_id=session_id,
        scene=scene,
        choices=choices,
        notices=notices,
        state=unified,
        llm_ok=llm_ok,
        effects_applied=eff,
        llm_attempts=llm_attempts,
        llm_fallback=llm_fallback,
        last_skill_check=sk_line,
    )


@router.get("/sessions", response_model=SessionsListResponse)
def get_sessions_list() -> SessionsListResponse:
    return SessionsListResponse(sessions=list_session_ids(settings.sessions_dir))


@router.post("/sessions", response_model=SessionGetResponse)
def create_session(body: CreateSessionRequest) -> SessionGetResponse:
    try:
        sid = validate_session_id(body.session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    sdir: Path = settings.sessions_dir / sid
    marker = sdir / "main_character.json"
    if marker.exists() and not body.overwrite:
        raise HTTPException(
            status_code=409,
            detail="session_already_exists",
        )

    sdir.mkdir(parents=True, exist_ok=True)
    if body.overwrite:
        wipe_session_json_files(sdir)

    sf = load_session(sid, settings.sessions_dir)
    bootstrap_if_empty(
        sf,
        language=body.language,
        player_name=body.player.name if body.player else None,
        player_backstory=body.player.backstory if body.player else None,
        world_location=body.world.location if body.world else None,
        world_premise=body.world.premise if body.world else None,
    )
    sf.load()
    unified = merge_to_unified(sf)
    last = str(sf.history.get("pending_scene", ""))
    choices = sf.history.get("pending_choices") or []
    if not isinstance(choices, list):
        choices = []
    choices = [str(c) for c in choices if str(c).strip()]
    notices = extract_notices(last, unified) if last else []
    return SessionGetResponse(
        session_id=sid,
        state=unified,
        last_scene=last,
        choices=choices,
        notices=notices,
    )


@router.get("/session/{session_id}", response_model=SessionGetResponse)
def get_session(session_id: str) -> SessionGetResponse:
    if not session_id or ".." in session_id or "/" in session_id:
        raise HTTPException(status_code=400, detail="invalid session id")
    sf = load_session(session_id, settings.sessions_dir)
    bootstrap_if_empty(sf)
    sf.load()
    unified = merge_to_unified(sf)
    last = str(sf.history.get("pending_scene", ""))
    choices = sf.history.get("pending_choices") or []
    if not isinstance(choices, list):
        choices = []
    choices = [str(c) for c in choices if str(c).strip()]
    notices = extract_notices(last, unified) if last else []
    return SessionGetResponse(
        session_id=session_id,
        state=unified,
        last_scene=last,
        choices=choices,
        notices=notices,
    )


@router.post("/session/{session_id}/action", response_model=ActionResponse)
def post_action(session_id: str, body: ActionRequest) -> ActionResponse:
    if not session_id or ".." in session_id or "/" in session_id:
        raise HTTPException(status_code=400, detail="invalid session id")
    return _run_action_core(session_id, body)


@router.post("/session/{session_id}/action/stream")
def post_action_stream(session_id: str, body: ActionRequest) -> StreamingResponse:
    """NDJSON stream: `llm_attempt` lines, then one `result` with full ActionResponse JSON."""
    if not session_id or ".." in session_id or "/" in session_id:
        raise HTTPException(status_code=400, detail="invalid session id")

    def generate():
        q: queue.Queue[str | None] = queue.Queue()
        fatal: list[BaseException | None] = [None]

        def worker() -> None:
            try:
                sf = load_session(session_id, settings.sessions_dir)
                bootstrap_if_empty(sf)
                sf.load()

                def on_try(cur: int, mx: int, wave: int) -> None:
                    evt = {
                        "type": "llm_attempt",
                        "current": cur,
                        "max": mx,
                        "wave": wave,
                        "max_waves": game_engine.LLM_PARSE_WAVES,
                    }
                    q.put(json.dumps(evt, ensure_ascii=False) + "\n")

                (
                    scene,
                    choices,
                    unified,
                    eff,
                    llm_ok,
                    llm_attempts,
                    llm_fallback,
                    sk_line,
                    extra_notices,
                ) = run_turn(
                    sf,
                    (body.choice or "").strip(),
                    (body.free_text or "").strip(),
                    roll_dice=bool(body.roll_dice),
                    on_llm_attempt=on_try,
                )
                notices = extract_notices(scene, unified) + extra_notices
                resp = ActionResponse(
                    session_id=session_id,
                    scene=scene,
                    choices=choices,
                    notices=notices,
                    state=unified,
                    llm_ok=llm_ok,
                    effects_applied=eff,
                    llm_attempts=llm_attempts,
                    llm_fallback=llm_fallback,
                    last_skill_check=sk_line,
                )
                payload = json.dumps(
                    {"type": "result", "payload": resp.model_dump(mode="json")},
                    ensure_ascii=False,
                )
                q.put(payload + "\n")
            except Exception as e:
                fatal[0] = e
            finally:
                q.put(None)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            line = q.get()
            if line is None:
                if fatal[0] is not None:
                    err_line = json.dumps(
                        {"type": "error", "message": str(fatal[0])},
                        ensure_ascii=False,
                    )
                    yield err_line.encode("utf-8") + b"\n"
                break
            yield line.encode("utf-8")

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson; charset=utf-8",
    )
