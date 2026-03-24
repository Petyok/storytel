from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.schemas import (
    ActionRequest,
    ActionResponse,
    SessionGetResponse,
    SessionsListResponse,
)
from app.services.game_engine import bootstrap_if_empty, extract_notices, run_turn
from app.services.state_store import list_session_ids, load_session, merge_to_unified

router = APIRouter()


@router.get("/sessions", response_model=SessionsListResponse)
def get_sessions_list() -> SessionsListResponse:
    return SessionsListResponse(sessions=list_session_ids(settings.sessions_dir))


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
    sf = load_session(session_id, settings.sessions_dir)
    bootstrap_if_empty(sf)
    sf.load()
    scene, choices, unified, eff, llm_ok = run_turn(sf, body.choice)
    notices = extract_notices(scene, unified)
    return ActionResponse(
        session_id=session_id,
        scene=scene,
        choices=choices,
        notices=notices,
        state=unified,
        llm_ok=llm_ok,
        effects_applied=eff,
    )
