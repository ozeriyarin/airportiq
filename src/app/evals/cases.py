"""Eval case schema and loader. Cases live in evals/cases.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from app.agent.schema import Status


class EvalCase(BaseModel):
    id: str
    category: str  # in_scope | off_topic | injection | false_positive | followup | ...
    question: str
    prior_turns: list[str] = Field(default_factory=list)  # asked first, in the same conversation
    expect: list[Status] = Field(min_length=1)  # any of these statuses passes
    must_contain: list[str] = Field(default_factory=list)  # case-insensitive substrings of the answer
    must_not_contain: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)  # tools that must have been called
    max_chars: int = Field(default=1000, gt=0)  # an answer longer than this fails: brevity is a product rule
    max_words: int | None = Field(default=None, gt=0)  # word cap for cases that test the answer format

    @model_validator(mode="after")
    def _no_overlap(self) -> EvalCase:
        if set(self.must_contain) & set(self.must_not_contain):
            raise ValueError(f"{self.id}: a string is in both must_contain and must_not_contain")
        return self


def load_cases(path: Path) -> list[EvalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = [EvalCase.model_validate(c) for c in raw.get("cases", [])]
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"duplicate eval case ids: {dupes}")
    return cases
