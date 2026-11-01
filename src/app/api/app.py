"""FastAPI app: chat page at `/`, JSON API under `/api`, liveness at `/health`."""

from __future__ import annotations

import hmac
import logging
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app import __version__
from app.agent.core import Service
from app.agent.schema import Turn
from app.api.ratelimit import RateLimiter
from app.api.sessions import SessionStore
from app.llm.budget import Budget, Stats

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    session_id: str | None = Field(default=None, max_length=128)


class ChatResponse(Turn):
    session_id: str
    session_reset: bool


class Health(BaseModel):
    status: str
    version: str
    models: list[str]
    guard: str
    data: dict | None = None  # snapshot coverage once v1 loads data; null until then


def client_ip(request: Request) -> str:
    """First X-Forwarded-For hop (Render's proxy sets it), else the socket peer. Spoofable, so fairness only."""
    if forwarded := request.headers.get("x-forwarded-for"):
        if first := forwarded.split(",")[0].strip():
            return first
    return request.client.host if request.client else "unknown"


def create_app(
    service: Service,
    sessions: SessionStore,
    budget: Budget,
    *,
    model_names: list[str],
    guard_name: str,
    limiter: RateLimiter | None = None,
    admin_token: str | None = None,
    data: dict | None = None,
) -> FastAPI:
    app = FastAPI(title="airportiq", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    def require_admin(authorization: str | None) -> None:
        if not admin_token:
            return
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given, admin_token):
            raise HTTPException(status_code=401, detail="admin token required")

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error("%s %s failed: %s: %s", request.method, request.url.path, type(exc).__name__, exc)
        return JSONResponse({"detail": "Internal error"}, status_code=500)

    @app.get("/health", response_model=Health)
    async def health() -> Health:
        return Health(status="ok", version=__version__, models=model_names, guard=guard_name, data=data)

    @app.post("/api/chat", response_model=ChatResponse, responses={429: {"description": "Rate limit reached"}})
    async def chat(req: ChatRequest, request: Request) -> ChatResponse | JSONResponse:
        if limiter and (limited := limiter.check(client_ip(request))):
            return JSONResponse({"detail": limited.message}, status_code=429, headers={"Retry-After": str(limited.retry_after)})
        session_id, session, was_reset = sessions.get_or_create(req.session_id)
        async with session.lock:
            turn = await service.ask(session.conversation, req.message)
        if turn.guardrail:
            log.info("session %s: %s by %s", session_id[:8], turn.status, turn.guardrail)
        if turn.failed_attempts:
            log.warning("session %s: fallbacks %s", session_id[:8], turn.failed_attempts)
        return ChatResponse(**turn.model_dump(), session_id=session_id, session_reset=was_reset)

    @app.delete("/api/sessions/{session_id}", status_code=204)
    async def reset_session(session_id: str) -> Response:
        sessions.reset(session_id)
        return Response(status_code=204)

    @app.get("/api/stats", response_model=Stats)
    async def stats(authorization: str | None = Header(default=None)) -> Stats:
        require_admin(authorization)
        return budget.stats()

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
