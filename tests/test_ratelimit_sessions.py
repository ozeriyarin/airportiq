from __future__ import annotations

from app.api.ratelimit import RateLimiter
from app.api.sessions import SessionStore


def test_per_ip_window_slides():
    clock = [0.0]
    rl = RateLimiter(per_ip_per_hour=2, global_per_day=100, now=lambda: clock[0])
    assert rl.check("a") is None and rl.check("a") is None
    limited = rl.check("a")
    assert limited and limited.scope == "ip" and limited.retry_after >= 1
    assert rl.check("b") is None  # another address is unaffected
    clock[0] = 3601.0
    assert rl.check("a") is None


def test_global_daily_cap():
    rl = RateLimiter(per_ip_per_hour=100, global_per_day=2, now=lambda: 0.0)
    assert rl.check("a") is None and rl.check("b") is None
    assert rl.check("c").scope == "global"


def test_sessions_expire_and_lru_cap():
    clock = [0.0]
    store = SessionStore(max_turns=3, ttl_s=10, max_sessions=2, now=lambda: clock[0])
    sid, _, reset = store.get_or_create(None)
    assert reset is False
    same, _, reset = store.get_or_create(sid)
    assert same == sid and reset is False
    clock[0] = 11.0
    _, _, reset = store.get_or_create(sid)
    assert reset is True  # expired, new session started
    store.get_or_create(None)
    store.get_or_create(None)
    assert len(store) == 2
