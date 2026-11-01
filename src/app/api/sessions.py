"""In-process conversation memory: idle TTL plus an LRU cap. Lost on restart by design (see DESIGN.md)."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from app.agent.core import Conversation


@dataclass
class Session:
    conversation: Conversation
    last_used: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # one turn at a time per session


class SessionStore:
    def __init__(
        self, *, max_turns: int, ttl_s: float, max_sessions: int = 500, now: Callable[[], float] = time.monotonic
    ) -> None:
        self._max_turns, self._ttl_s, self._max_sessions, self._now = max_turns, ttl_s, max_sessions, now
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def get_or_create(self, session_id: str | None) -> tuple[str, Session, bool]:
        """The session for `session_id` or a new one; the flag says a given id had expired."""
        now = self._now()
        self._sweep(now)
        if session_id and (s := self._sessions.get(session_id)):
            s.last_used = now
            self._sessions.move_to_end(session_id)
            return session_id, s, False
        new_id = secrets.token_urlsafe(16)
        s = Session(Conversation(max_turns=self._max_turns), last_used=now)
        self._sessions[new_id] = s
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)
        return new_id, s, session_id is not None

    def reset(self, session_id: str) -> bool:
        if s := self._sessions.get(session_id):
            s.conversation.reset()
            return True
        return False

    def _sweep(self, now: float) -> None:
        expired = [k for k, s in self._sessions.items() if now - s.last_used > self._ttl_s]
        for k in expired:
            del self._sessions[k]

    @property
    def max_sessions(self) -> int:
        return self._max_sessions

    def __len__(self) -> int:
        return len(self._sessions)
