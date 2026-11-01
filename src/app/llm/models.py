"""Build the model chain: per-model HTTP retries, then FallbackModel across models and vendors.

Retry map (see Pydantic AI retries guide, "the layers"):
- transport: retries 429/5xx/network per model, honouring Retry-After, capped;
- SDK: disabled (max_retries=0) so a dead provider fails over at once;
- FallbackModel: moves to the next model on ModelAPIError or a truncated reply.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import httpx2
from pydantic_ai import ModelAPIError, ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.retries import AsyncHTTPX2TenacityTransport, RetryConfig, wait_retry_after
from tenacity import retry_if_exception, stop_after_attempt, wait_exponential

from app.config import ModelsConfig, Settings

log = logging.getLogger(__name__)

HttpClientFactory = Callable[[], httpx2.AsyncClient]


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx2.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or 500 <= code < 600
    return isinstance(exc, httpx2.TimeoutException | httpx2.ConnectError | httpx2.RemoteProtocolError)


def retrying_http_client(
    *, attempts: int, timeout_s: float, max_wait_s: float, wrapped: httpx2.AsyncBaseTransport | None = None, validate: bool = True
) -> httpx2.AsyncClient:
    """An httpx client whose transport retries 429/5xx/network errors with Retry-After or exponential backoff.
    `validate=False` returns 4xx/5xx responses instead of raising (the acceptance pass expects 401 and 422)."""
    transport = AsyncHTTPX2TenacityTransport(
        config=RetryConfig(
            retry=retry_if_exception(_retryable),
            wait=wait_retry_after(fallback_strategy=wait_exponential(multiplier=1, max=max_wait_s), max_wait=max_wait_s),
            stop=stop_after_attempt(attempts),
            reraise=True,
        ),
        wrapped=wrapped,
        validate_response=(lambda r: r.raise_for_status()) if validate else None,
    )
    return httpx2.AsyncClient(transport=transport, timeout=timeout_s)


def build_model(name: str, api_key: str, http_client: httpx2.AsyncClient) -> Model:
    """One Pydantic AI model with SDK retries off, so the transport and FallbackModel own the policy."""
    vendor, model_name = name.split(":", 1)
    if vendor == "anthropic":
        from anthropic import AsyncAnthropic
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        client = AsyncAnthropic(api_key=api_key, http_client=http_client, max_retries=0)
        return AnthropicModel(model_name, provider=AnthropicProvider(anthropic_client=client))
    if vendor == "openrouter":
        from openai import AsyncOpenAI
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        client = AsyncOpenAI(
            api_key=api_key, base_url="https://openrouter.ai/api/v1", http_client=http_client, max_retries=0
        )
        return OpenAIChatModel(model_name, provider=OpenRouterProvider(openai_client=client))
    if vendor == "google-gla":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        return GoogleModel(model_name, provider=GoogleProvider(api_key=api_key, http_client=http_client))
    if vendor == "typesafe":
        from pydantic_ai.models.typesafe import TypeSafeModel
        from pydantic_ai.providers.typesafe import TypeSafeProvider
        from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

        client = AsyncTypeSafeClient(api_key=api_key, retry=RetryPolicy(max_retries=0))
        return TypeSafeModel(model_name, provider=TypeSafeProvider(typesafe_client=client))
    raise ValueError(f"unsupported model vendor in {name!r}")


@dataclass(frozen=True)
class Chain:
    model: Model
    names: list[str]  # models actually in the chain, in order
    skipped: list[str]  # configured models dropped for a missing key


def truncated(response: ModelResponse) -> bool:
    return response.finish_reason == "length"


def cache_settings(cache: bool) -> dict | None:
    """Anthropic prompt-cache settings for the agent; other vendors ignore the prefixed keys."""
    if not cache:
        return None
    return {"anthropic_cache_instructions": True, "anthropic_cache_tool_definitions": True, "anthropic_cache_messages": True}


def answer_chain(chain: list[str], down: list[str] | None = None, only: str | None = None) -> list[str]:
    """The model ids to build: one model for an experiment, else the chain minus simulated outages."""
    return [only] if only else without_vendors(chain, down)


def without_vendors(names: list[str], down: list[str] | None) -> list[str]:
    """Chain entries minus the vendors in `down` (prefix match), to simulate an outage."""
    return [m for m in names if not any(m.startswith(d) for d in (down or []))]


def build_chain(
    names: list[str],
    settings: Settings,
    cfg: ModelsConfig,
    *,
    http_client_factory: HttpClientFactory | None = None,
    builder: Callable[[str, str, httpx2.AsyncClient], Model] = build_model,
) -> Chain:
    """FallbackModel over every configured model whose vendor key is present. MODEL_MODE=test → TestModel."""
    if settings.model_mode == "test":
        demo = TestModel(custom_output_args={
            "status": "answered", "answer": "(offline demo) I called my tools and this is a canned answer.",
            "sources": ["TestModel"], "limitations": ["MODEL_MODE=test: no real model was called"],
        })
        return Chain(demo, ["test"], [])
    make_client = http_client_factory or (
        lambda: retrying_http_client(
            attempts=cfg.retry_attempts, timeout_s=cfg.timeout_s, max_wait_s=cfg.retry_max_wait_s
        )
    )
    models: list[Model] = []
    kept: list[str] = []
    skipped: list[str] = []
    for name in names:
        key = settings.key_for(name)
        if not key:
            skipped.append(name)
            continue
        models.append(builder(name, key, make_client()))
        kept.append(name)
    if not models:
        raise RuntimeError(f"no model in the chain has a key; set one of the keys in .env.example ({names})")
    if skipped:
        log.info("models skipped for a missing key: %s", ", ".join(skipped))
    model = models[0] if len(models) == 1 else FallbackModel(*models, fallback_on=[ModelAPIError, httpx2.HTTPError, truncated])
    return Chain(model, kept, skipped)


def served_by(response: ModelResponse) -> str:
    return response.model_name or "unknown"


def failed_attempts(response: ModelResponse) -> list[str]:
    """Models that failed before the one that answered, as 'model: outcome' for logs and eval reports."""
    return [f"{a.model_name}: {a.outcome}" for a in (response.failed_attempts or [])]
