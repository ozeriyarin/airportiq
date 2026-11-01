"""Retries per model, fallback across models, and the chain builder's key handling."""

from __future__ import annotations

import httpx2
import pytest
from pydantic_ai import Agent, ModelAPIError, ModelHTTPError
from pydantic_ai.exceptions import FallbackExceptionGroup
from pydantic_ai.models.fallback import FallbackModel

from app.config import ModelsConfig, Settings
from app.llm.models import build_chain, failed_attempts, retrying_http_client, served_by, truncated
from tests.fakes import failing_model, text_model

CFG = ModelsConfig(
    chain=["anthropic:a", "openai:b", "google-gla:c"], guard_decision="typesafe:jev-latest",
    guard_fallback="anthropic:h", guard_confidence=0.7, timeout_s=5, retry_attempts=3, retry_max_wait_s=0,
)


async def test_fallback_moves_to_next_model_on_api_error():
    down = failing_model(ModelHTTPError(status_code=503, model_name="primary", body="down"), model_name="primary")
    model = FallbackModel(down, text_model("hello", model_name="backup"), fallback_on=[ModelAPIError, truncated])
    result = await Agent(model).run("hi")
    assert result.output == "hello"
    assert served_by(result.response) == "backup"
    assert failed_attempts(result.response) == ["primary: error"]


async def test_fallback_moves_on_truncated_reply():
    short = text_model("The capital of France is", finish_reason="length", model_name="primary")
    model = FallbackModel(short, text_model("Paris.", model_name="backup"), fallback_on=[ModelAPIError, truncated])
    result = await Agent(model).run("capital?")
    assert result.output == "Paris."
    assert failed_attempts(result.response) == ["primary: rejected"]


async def test_all_models_down_raises_fallback_group():
    model = FallbackModel(
        failing_model(ModelHTTPError(status_code=500, model_name="a", body="x"), model_name="a"),
        failing_model(ModelHTTPError(status_code=429, model_name="b", body="y"), model_name="b"),
    )
    with pytest.raises(FallbackExceptionGroup):
        await Agent(model).run("hi")


async def test_transport_retries_429_then_succeeds():
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.path)
        if len(calls) < 3:
            return httpx2.Response(429, headers={"Retry-After": "0"}, json={"error": "slow down"})
        return httpx2.Response(200, json={"ok": True})

    client = retrying_http_client(attempts=3, timeout_s=5, max_wait_s=0, wrapped=httpx2.MockTransport(handler))
    r = await client.get("https://example.test/v1/x")
    assert r.status_code == 200 and len(calls) == 3


async def test_transport_gives_up_after_attempts():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, json={"error": "down"})

    client = retrying_http_client(attempts=2, timeout_s=5, max_wait_s=0, wrapped=httpx2.MockTransport(handler))
    with pytest.raises(httpx2.HTTPStatusError):
        await client.get("https://example.test/v1/x")


async def test_transport_does_not_retry_4xx_client_errors():
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(401, json={"error": "bad key"})

    client = retrying_http_client(attempts=3, timeout_s=5, max_wait_s=0, wrapped=httpx2.MockTransport(handler))
    with pytest.raises(httpx2.HTTPStatusError):
        await client.get("https://example.test/v1/x")
    assert len(calls) == 1


def test_build_chain_skips_models_without_a_key():
    settings = Settings(_env_file=None, anthropic_api_key="k1", google_api_key="k3")
    built = []
    chain = build_chain(
        CFG.chain, settings, CFG, http_client_factory=lambda: None,
        builder=lambda name, key, client: (built.append((name, key)), text_model(name, model_name=name))[1],
    )
    assert chain.names == ["anthropic:a", "google-gla:c"]
    assert chain.skipped == ["openai:b"]
    assert built == [("anthropic:a", "k1"), ("google-gla:c", "k3")]
    assert isinstance(chain.model, FallbackModel)


def test_build_chain_without_any_key_fails_loudly():
    with pytest.raises(RuntimeError, match="no model in the chain has a key"):
        build_chain(CFG.chain, Settings(_env_file=None), CFG, http_client_factory=lambda: None)


def test_build_chain_test_mode_uses_test_model():
    chain = build_chain(CFG.chain, Settings(_env_file=None, model_mode="test"), CFG)
    assert chain.names == ["test"]


async def test_transport_http_error_after_retries_falls_over_to_next_model():
    """A 429 that survives the transport's retries is an httpx2.HTTPStatusError, not a ModelAPIError."""
    request = httpx2.Request("POST", "https://api.example.test/v1/chat")
    err = httpx2.HTTPStatusError("429", request=request, response=httpx2.Response(429, request=request))
    model = FallbackModel(
        failing_model(err, model_name="primary"), text_model("hello", model_name="backup"),
        fallback_on=[ModelAPIError, httpx2.HTTPError, truncated],
    )
    result = await Agent(model).run("hi")
    assert result.output == "hello" and served_by(result.response) == "backup"
