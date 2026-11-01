"""The contract between the model and the rest of the system. Changing it is a spec change."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal[
    "answered", "cannot_answer", "refused_off_topic", "refused_injection", "rejected_input", "unavailable", "budget_exhausted"
]


class AnswerOut(BaseModel):
    """What the model must return. Validated by Pydantic AI; a bad reply is retried once with the error."""

    status: Literal["answered", "cannot_answer"]
    answer: str = Field(min_length=1, max_length=2000)  # brevity is a product rule; see prompts
    sources: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=10)


class Turn(BaseModel):
    """One completed exchange as the API, CLI and evals see it."""

    status: Status
    answer: str
    sources: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    served_by: str | None = None
    failed_attempts: list[str] = Field(default_factory=list)
    guardrail: str | None = None  # "regex" or the guard model name, when a guardrail decided
    tools_used: list[str] = Field(default_factory=list)
    model_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0  # prompt-cache reads (Anthropic); the saving is visible, not claimed
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    tool_results: list[str] = Field(default_factory=list, exclude=True)  # for the eval grounding check, not the API
    facts: str = Field(default="", exclude=True)  # the dynamic data facts the prompt stated this turn
    tool_results: list[str] = Field(default_factory=list, exclude=True)  # for the eval grounding check, not the API
