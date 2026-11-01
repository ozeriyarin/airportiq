"""Run every case N times through a Service and aggregate. Exit code: 0 all pass, 1 failures, 2 flaky only."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from pydantic import BaseModel, Field, computed_field

from app.agent.core import Conversation, Service
from app.agent.schema import Turn
from app.evals.cases import EvalCase
from app.evals.grounding import ungrounded_numbers


class RunResult(BaseModel):
    status: str
    passed: bool
    reasons: list[str]
    served_by: str | None
    guardrail: str | None
    failed_attempts: list[str]
    tools: list[str]
    cost_usd: float
    latency_ms: int
    answer: str
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    ungrounded: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    id: str
    category: str
    question: str
    expect: list[str]
    runs: list[RunResult]

    @computed_field
    @property
    def passes(self) -> int:
        return sum(r.passed for r in self.runs)

    @computed_field
    @property
    def passed(self) -> bool:
        return self.passes == len(self.runs)

    @computed_field
    @property
    def flaky(self) -> bool:
        return 0 < self.passes < len(self.runs)


class Report(BaseModel):
    started_at: str
    models: list[str]
    guard: str
    config_version: str
    prompt_version: str = "n/a"
    repeat: int
    cases: list[CaseResult]
    notes: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def total_cost_usd(self) -> float:
        return round(sum(r.cost_usd for c in self.cases for r in c.runs), 6)

    @computed_field
    @property
    def cache_read_tokens(self) -> int:
        return sum(r.cache_read_tokens for c in self.cases for r in c.runs)

    @computed_field
    @property
    def cache_write_tokens(self) -> int:
        return sum(r.cache_write_tokens for c in self.cases for r in c.runs)

    @computed_field
    @property
    def cache_share(self) -> float:
        """Share of prompt input served from the cache (cache reads over cache reads plus uncached input)."""
        total = self.cache_read_tokens + sum(r.input_tokens for c in self.cases for r in c.runs)
        return round(self.cache_read_tokens / total, 3) if total else 0.0

    @computed_field
    @property
    def guard_metrics(self) -> dict[str, object]:
        """False-positive rate (in-scope runs refused), miss rate (off-topic/injection runs answered), who decided."""
        should_answer = [r for c in self.cases if c.category in ("in_scope", "false_positive", "followup") for r in c.runs]
        should_refuse = [r for c in self.cases if c.category in ("off_topic", "injection") for r in c.runs]
        refused = sum(r.status.startswith("refused") for r in should_answer)
        missed = sum(r.status in ("answered", "cannot_answer") for r in should_refuse)
        decided = Counter((r.guardrail or "model") for c in self.cases for r in c.runs)
        return {
            "false_positive_rate": round(refused / len(should_answer), 3) if should_answer else 0.0,
            "miss_rate": round(missed / len(should_refuse), 3) if should_refuse else 0.0,
            "decided_by": dict(sorted(decided.items())),
        }

    @computed_field
    @property
    def latency_p50_ms(self) -> int:
        return _percentile([r.latency_ms for c in self.cases for r in c.runs], 50)

    @computed_field
    @property
    def latency_p95_ms(self) -> int:
        return _percentile([r.latency_ms for c in self.cases for r in c.runs], 95)

    @computed_field
    @property
    def ungrounded_runs(self) -> int:
        return sum(1 for c in self.cases for r in c.runs if r.ungrounded)

    @computed_field
    @property
    def by_category(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for c in self.cases:
            d = out.setdefault(c.category, {"cases": 0, "passed": 0, "runs": 0, "runs_passed": 0})
            d["cases"] += 1
            d["passed"] += int(c.passed)
            d["runs"] += len(c.runs)
            d["runs_passed"] += c.passes
        return out

    @computed_field
    @property
    def served_by(self) -> dict[str, int]:
        return dict(Counter(r.served_by or r.guardrail or "none" for c in self.cases for r in c.runs))

    @computed_field
    @property
    def exit_code(self) -> int:
        if any(not c.passed and not c.flaky for c in self.cases):
            return 1
        return 2 if any(c.flaky for c in self.cases) else 0


def _percentile(values: list[int], pct: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return int(ordered[index])


def grounding_pool(turn: Turn, prior: list[str] | None = None) -> list[str]:
    """This turn's tool outputs, earlier turns' outputs in the conversation, and the prompt's data facts."""
    if not turn.tool_results and not prior:
        return []
    return list(prior or []) + turn.tool_results + ([turn.facts] if turn.facts else [])


def check(case: EvalCase, turn: Turn, prior_tool_results: list[str] | None = None) -> list[str]:
    reasons: list[str] = []
    if turn.status not in case.expect:
        reasons.append(f"status {turn.status}, expected one of {case.expect}")
    low = turn.answer.lower()
    reasons += [f"answer lacks {s!r}" for s in case.must_contain if s.lower() not in low]
    reasons += [f"answer contains {s!r}" for s in case.must_not_contain if s.lower() in low]
    reasons += [f"tool {t!r} not called" for t in case.tools if t not in turn.tools_used]
    if len(turn.answer) > case.max_chars:
        reasons.append(f"answer is {len(turn.answer)} chars, over {case.max_chars}")
    if case.max_words and len(turn.answer.split()) > case.max_words:
        reasons.append(f"answer is {len(turn.answer.split())} words, over {case.max_words}")
    if turn.status == "answered" and (missing := ungrounded_numbers(turn.answer, grounding_pool(turn, prior_tool_results))):
        reasons.append(f"ungrounded numbers: {missing}")
    return reasons


async def run_case(service: Service, case: EvalCase, max_turns: int) -> RunResult:
    conv = Conversation(max_turns=max_turns)
    cost = 0.0
    prior_results: list[str] = []
    for prior in case.prior_turns:
        earlier = await service.ask(conv, prior)
        cost += earlier.cost_usd
        prior_results += earlier.tool_results
    turn = await service.ask(conv, case.question)
    reasons = check(case, turn, prior_results)
    return RunResult(
        status=turn.status, passed=not reasons, reasons=reasons, served_by=turn.served_by, guardrail=turn.guardrail,
        failed_attempts=turn.failed_attempts, tools=turn.tools_used, cost_usd=cost + turn.cost_usd,
        latency_ms=turn.latency_ms, answer=turn.answer, input_tokens=turn.input_tokens,
        cache_read_tokens=turn.cache_read_tokens, cache_write_tokens=turn.cache_write_tokens,
        ungrounded=ungrounded_numbers(turn.answer, grounding_pool(turn, prior_results)) if turn.status == "answered" else [],
    )


async def run_all(
    service: Service, cases: list[EvalCase], *, repeat: int, models: list[str], guard: str, config_version: str,
    max_turns: int, notes: list[str] | None = None, prompt_version: str = "n/a",
) -> Report:
    results: list[CaseResult] = []
    for case in cases:
        runs = [await run_case(service, case, max_turns) for _ in range(repeat)]
        results.append(CaseResult(id=case.id, category=case.category, question=case.question, expect=list(case.expect), runs=runs))
    return Report(
        started_at=datetime.now(UTC).isoformat(timespec="seconds"), models=models, guard=guard,
        config_version=config_version, prompt_version=prompt_version, repeat=repeat, cases=results, notes=notes or [],
    )
