"""Tools the model may call. Every tool is deterministic code over the data; the model only chooses and explains.

Tools never raise: an unknown airport, area or lens comes back as `NotFound` with the valid values, and missing
data as `Unavailable`. v0 ships `about` only; v2 adds the capacity tools.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app import __version__
from app.agent.prompts import SCOPE_DESCRIPTION


@dataclass
class ToolContext:
    """Everything tools need. Built once at startup by `cli.compose`, injected per run as `deps`."""

    product_name: str
    data_facts: str = "Scoring data is not loaded yet: only `about` works; say so when asked for figures."


class About(BaseModel):
    product: str
    version: str
    scope: str


class NotFound(BaseModel):
    kind: str = Field(description="what was not found: airport, area or lens")
    query: str
    valid: list[str]
    hint: str


class Unavailable(BaseModel):
    reason: str


def about(ctx: RunContext[ToolContext]) -> About:
    """What this assistant is and what it covers. Call when the user asks what you can do."""
    return About(product=ctx.deps.product_name, version=__version__, scope=SCOPE_DESCRIPTION)


def build_toolset() -> FunctionToolset[ToolContext]:
    toolset: FunctionToolset[ToolContext] = FunctionToolset()
    for fn in (about,):
        toolset.add_function(fn)
    return toolset
