"""Scripted models built on Pydantic AI's FunctionModel: deterministic, offline, inspectable."""

from __future__ import annotations

from collections.abc import Callable

from pydantic_ai import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

USAGE = RequestUsage(input_tokens=100, output_tokens=20)


def final(payload: dict, *, model_name: str = "fake") -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart("final_result", payload)], usage=USAGE, model_name=model_name)


def answer_model(
    text: str = "ok", *, status: str = "answered", sources: list[str] | None = None, tools: list[str] | None = None,
    model_name: str = "fake-answer",
) -> FunctionModel:
    """Calls each tool in `tools` once (one per request), then returns the structured answer."""

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        called = {p.tool_name for m in messages if isinstance(m, ModelResponse) for p in m.parts if isinstance(p, ToolCallPart)}
        for t in tools or []:
            if t not in called:
                return ModelResponse(parts=[ToolCallPart(t, {})], usage=USAGE, model_name=model_name)
        return final({"status": status, "answer": text, "sources": sources or [], "limitations": []}, model_name=model_name)

    return FunctionModel(fn, model_name=model_name)


def screening_model(*, in_scope: bool = True, injection: bool = False, model_name: str = "fake-guard") -> FunctionModel:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return final({"in_scope": in_scope, "injection": injection}, model_name=model_name)

    return FunctionModel(fn, model_name=model_name)


def failing_model(exc: Exception, *, model_name: str = "fake-down") -> FunctionModel:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise exc

    return FunctionModel(fn, model_name=model_name)


def text_model(text: str, *, finish_reason: str | None = None, model_name: str = "fake-text") -> FunctionModel:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(text)], usage=USAGE, model_name=model_name, finish_reason=finish_reason)

    return FunctionModel(fn, model_name=model_name)


def last_tool_return(messages: list[ModelMessage]) -> ToolReturnPart | None:
    for m in reversed(messages):
        for p in getattr(m, "parts", []):
            if isinstance(p, ToolReturnPart):
                return p
    return None


Fn = Callable[[list[ModelMessage], AgentInfo], ModelResponse]
