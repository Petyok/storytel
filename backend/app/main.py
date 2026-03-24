from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.sessions import router as sessions_router
from app.core.config import settings
from app.services.game_engine import LLM_PARSE_WAVES

app = FastAPI(title="Dark Fantasy Story", version="1.0.0")

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "llm_max_retries": settings.llm_max_retries,
        "llm_parse_waves": LLM_PARSE_WAVES,
    }
