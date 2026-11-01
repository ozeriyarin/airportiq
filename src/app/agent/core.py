"""Per-turn service: input checks → guard → budget reserve → agent run → settle → typed Turn."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx2
from pydantic_ai import (
    Agent,
    ModelAPIError,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    RunContext,
    ToolCallPart,
    ToolReturnPart,
    UsageLimits,
    capture_run_messages,
)
from pydantic_ai.exceptions import FallbackExceptionGroup, UsageLimitExceeded
from pydantic_ai.models import Model

from app.agent import prompts
from app.agent.schema import AnswerOut, Turn
from app.agent.tools import ToolContext, build_toolset
from app.config import LimitsConfig, Price
from app.decide.guard import Guard, check_input
from app.llm.budget import Budget, BudgetExceeded, estimate_cost
from app.llm.models import cache_settings, failed_attempts, served_by

log = logging.getLogger(__name__)


def data_instructions(deps: ToolContext) -> str:
    """Facts injected per run so the prompt can never be stale relative to the snapshot and the config."""
    return deps.data_facts


def build_agent(model: Model, *, cache: bool = True) -> Agent[ToolContext, AnswerOut]:
    agent: Agent[ToolContext, AnswerOut] = Agent(
        model,
        deps_type=ToolContext,
        output_type=AnswerOut,
        instructions=prompts.INSTRUCTIONS,
        toolsets=[build_toolset()],
        retries=1,
        model_settings=cache_settings(cache),
    )

    @agent.instructions
    def data_facts(ctx: RunContext[ToolContext]) -> str:
        return data_instructions(ctx.deps)

    return agent


@dataclass
class Conversation:
    """Message history for one session, trimmed to the last `max_turns` exchanges."""

    max_turns: int
    history: list[ModelMessage] = field(default_factory=list)
    turns: int = 0
    last_question: str | None = None  # guard context for follow-ups such as 'and the year before?'

    def extend(self, new_messages: list[ModelMessage]) -> None:
        self.history.extend(new_messages)
        self.turns += 1
        # Each turn appends at least a request and a response; keep roughly max_turns exchanges.
        while self.turns > self.max_turns and len(self.history) >= 2:
            del self.history[:2]
            self.turns -= 1

    def reset(self) -> None:
        self.history.clear()
        self.turns = 0
        self.last_question = None


def tool_results_of(messages: list[ModelMessage]) -> list[str]:
    """The tool outputs exactly as the model saw them, for the eval grounding check."""
    return [
        p.model_response_str() for m in messages if isinstance(m, ModelRequest)
        for p in m.parts if isinstance(p, ToolReturnPart)
    ]


def tool_call_trace(messages: list[ModelMessage]) -> list[str]:
    """Tool names in call order plus 'retry' markers, for the log line when a turn hits the request limit."""
    trace: list[str] = []
    for m in messages:
        if isinstance(m, ModelResponse):
            trace += [f"{p.tool_name}{p.args_as_dict()}" for p in m.parts if isinstance(p, ToolCallPart) and p.tool_name != "final_result"]
        elif isinstance(m, ModelRequest):
            trace += ["retry" for p in m.parts if isinstance(p, RetryPromptPart)]
    return trace


def tools_used(messages: list[ModelMessage]) -> list[str]:
    names: list[str] = []
    for m in messages:
        if isinstance(m, ModelResponse):
            names += [p.tool_name for p in m.parts if isinstance(p, ToolCallPart) and p.tool_name != "final_result"]
    return list(dict.fromkeys(names))


class Service:
    def __init__(
        self,
        agent: Agent[ToolContext, AnswerOut],
        guard: Guard,
        budget: Budget,
        limits: LimitsConfig,
        prices: dict[str, Price],
        deps: ToolContext,
    ) -> None:
        self.agent, self.guard, self.budget, self.limits, self.prices, self.deps = agent, guard, budget, limits, prices, deps

    async def ask(self, conversation: Conversation, message: str) -> Turn:
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        if rejection := check_input(message, self.limits.max_message_chars):
            if rejection.reason == "injection":
                return Turn(status="refused_injection", answer=prompts.REFUSAL_INJECTION, guardrail="regex", latency_ms=elapsed())
            return Turn(status="rejected_input", answer=rejection.detail, guardrail="regex", latency_ms=elapsed())

        if intro := prompts.intro_reply(message):
            conversation.last_question = message
            return Turn(status="answered", answer=intro, sources=["intro"], guardrail="intro", latency_ms=elapsed())

        try:
            rid = self.budget.reserve(self.limits.per_turn_estimate_usd, kind="turn", model="pending")
        except BudgetExceeded as e:
            log.warning("budget: %s", e)
            return Turn(status="budget_exhausted", answer=prompts.BUDGET_EXHAUSTED, latency_ms=elapsed())

        cost = 0.0
        captured: list[ModelMessage] = []
        try:
            verdict = await self.guard.screen(message, previous=conversation.last_question)
            if verdict.label != "in_scope":
                self.budget.release(rid, failed=False)
                status = "refused_injection" if verdict.label == "injection" else "refused_off_topic"
                text = prompts.REFUSAL_INJECTION if verdict.label == "injection" else prompts.REFUSAL_OFF_TOPIC
                return Turn(status=status, answer=text, guardrail=verdict.decided_by, latency_ms=elapsed())

            with capture_run_messages() as captured:
                result = await self.agent.run(
                    message,
                    deps=self.deps,
                    message_history=list(conversation.history),
                    usage_limits=UsageLimits(
                        request_limit=self.limits.model_requests_per_turn, cost_limit=self.limits.per_turn_usd  # type: ignore[arg-type]
                    ),
                )
        except UsageLimitExceeded as e:
            self.budget.release(rid, failed=True)
            log.warning("turn stopped by usage limit: %s; tool calls: %s", e, tool_call_trace(captured))
            return Turn(status="cannot_answer", answer="I had to stop before finishing this answer. Try a narrower question.", latency_ms=elapsed())
        except (ModelAPIError, FallbackExceptionGroup, httpx2.HTTPError) as e:  # transport errors after retries
            self.budget.release(rid, failed=True)
            log.error("all models failed: %r", e)
            return Turn(status="unavailable", answer=prompts.UNAVAILABLE, latency_ms=elapsed())
        except BaseException:
            self.budget.release(rid, failed=True)
            raise

        usage = result.usage
        model_name = served_by(result.response)
        cost = float(usage.cost) if getattr(usage, "cost", None) is not None else estimate_cost(
            self.prices, model_name, usage.input_tokens, usage.output_tokens
        )
        self.budget.settle(
            rid, cost_usd=cost, model=model_name, input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens, latency_ms=elapsed(),
        )
        new_messages = result.new_messages()
        conversation.extend(new_messages)
        conversation.last_question = message
        out = result.output
        return Turn(
            status=out.status,
            answer=out.answer,
            sources=out.sources,
            limitations=out.limitations,
            served_by=model_name,
            failed_attempts=failed_attempts(result.response),
            tools_used=tools_used(new_messages),
            tool_results=tool_results_of(new_messages),
            facts=data_instructions(self.deps),
            model_requests=usage.requests,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=cost,
            latency_ms=elapsed(),
        )
