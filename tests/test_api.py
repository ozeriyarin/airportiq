from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.ratelimit import RateLimiter
from app.api.sessions import SessionStore


def make_client(service, budget, *, limiter=None, admin_token=None) -> TestClient:
    app = create_app(
        service, SessionStore(max_turns=5, ttl_s=60), budget, model_names=["fake"], guard_name="fake-guard",
        limiter=limiter, admin_token=admin_token,
    )
    return TestClient(app)


def test_health(service, budget):
    r = make_client(service, budget).get("/health")
    assert r.status_code == 200 and r.json()["models"] == ["fake"] and r.json()["guard"] == "fake-guard"


def test_index_serves_the_chat_page(service, budget):
    r = make_client(service, budget).get("/")
    assert r.status_code == 200 and "<title>airportiq</title>" in r.text


def test_chat_round_trip_keeps_the_session(service, budget):
    c = make_client(service, budget)
    r1 = c.post("/api/chat", json={"message": "Which airport is most congested?"})
    assert r1.status_code == 200
    body = r1.json()
    assert body["status"] == "answered" and body["answer"] == "ok" and body["session_reset"] is False
    r2 = c.post("/api/chat", json={"message": "again", "session_id": body["session_id"]})
    assert r2.json()["session_id"] == body["session_id"] and r2.json()["session_reset"] is False


def test_unknown_session_id_is_reported_as_reset(service, budget):
    r = make_client(service, budget).post("/api/chat", json={"message": "hi", "session_id": "gone"})
    assert r.status_code == 200 and r.json()["session_reset"] is True


def test_validation_errors_are_422(service, budget):
    assert make_client(service, budget).post("/api/chat", json={"message": ""}).status_code == 422


def test_rate_limit_returns_429_with_retry_after(service, budget):
    c = make_client(service, budget, limiter=RateLimiter(per_ip_per_hour=1, global_per_day=10))
    assert c.post("/api/chat", json={"message": "hi"}).status_code == 200
    r = c.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_stats_requires_admin_token_when_set(service, budget):
    c = make_client(service, budget, admin_token="secret")
    assert c.get("/api/stats").status_code == 401
    r = c.get("/api/stats", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200 and r.json()["cap_usd"] == 1.0


def test_session_reset(service, budget):
    c = make_client(service, budget)
    sid = c.post("/api/chat", json={"message": "hi"}).json()["session_id"]
    assert c.delete(f"/api/sessions/{sid}").status_code == 204
