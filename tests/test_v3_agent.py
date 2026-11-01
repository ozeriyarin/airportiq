"""Acceptance criteria of agent-os/specs/2026-11-01-v3-agent, one test per criterion, all offline."""

from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from app import cli as cli_module
from app.agent import prompts
from app.agent.tools import build_toolset
from app.config import ROOT
from app.evals.cases import load_cases

BRIEF_TOOLS = {"rank_airports", "compare_airports", "traffic_mix", "unmet_demand"}


def _report(tag: str) -> dict:
    return json.loads((ROOT / "evals" / "results" / f"{tag}.json").read_text(encoding="utf-8"))


def test_criterion_1_prompt_names_every_tool_and_the_rules():
    names = set(build_toolset().tools)
    for n in names:
        assert f"- {n}:" in prompts.TOOL_GUIDE, n
    text = prompts.INSTRUCTIONS
    flat = " ".join(text.split())
    for phrase in ("Never add, subtract, average", "lens", "denominator", "service volume", "Ambiguous", "percentile", "never multiply"):
        assert phrase in flat, phrase
    assert re.fullmatch(r"\d+\.\d+\.\d+", prompts.PROMPT_VERSION) and prompts.PROMPT_VERSION >= "0.2.0"


def test_criterion_2_brief_questions_are_pinned_with_engine_facts_and_tools():
    cases = {c.id: c for c in load_cases(ROOT / "evals" / "cases.yaml")}
    for q in prompts.EXAMPLE_QUESTIONS:
        assert any(c.question == q for c in cases.values()), q
    assert "BOS" in cases["brief-1-new-england-expansion"].must_contain and cases["brief-1-new-england-expansion"].tools == ["rank_airports"]
    assert set(cases["brief-2-lax-vs-sna-congestion"].must_contain) == {"LAX", "SNA"} and cases["brief-2-lax-vs-sna-congestion"].tools == ["compare_airports"]
    assert "31.0" in cases["brief-3-anc-long-haul"].must_contain and cases["brief-3-anc-long-haul"].tools == ["traffic_mix"]
    assert cases["brief-4-sfo-unmet-demand"].tools == ["unmet_demand"] and "profile" in cases["sfo-capacity-source"].must_contain


def test_criterion_3_every_category_has_three_cases_and_followups_use_prior_turns():
    cases = load_cases(ROOT / "evals" / "cases.yaml")
    assert len(cases) >= 18
    by_cat: dict[str, list] = {}
    for c in cases:
        by_cat.setdefault(c.category, []).append(c)
    for cat in ("off_topic", "injection", "false_positive", "followup"):
        assert len(by_cat[cat]) >= 3, cat
    assert all(c.prior_turns for c in by_cat["followup"])


def test_criterion_4_smoke_set_asserts_the_brief_tools_offline(tmp_path: Path, monkeypatch):
    smoke = {c.question: c for c in load_cases(ROOT / "evals" / "smoke.yaml")}
    assert {t for q in prompts.EXAMPLE_QUESTIONS for t in smoke[q].tools} == BRIEF_TOOLS
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ledger.db"))
    result = CliRunner().invoke(cli_module.cli, ["eval", "--test", "--tag", "smoke", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output


def test_criterion_5_baseline_report_passes_with_grounding_and_metadata():
    r = _report("v3-baseline")
    assert r["exit_code"] in (0, 2) and r["repeat"] >= 2 and not any(not c["passed"] and not c["flaky"] for c in r["cases"])
    assert len(r["cases"]) >= 30
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if r["prompt_version"] != prompts.PROMPT_VERSION:  # a newer prompt without a re-run must say so in the README
        assert f"Prompt {prompts.PROMPT_VERSION}" in readme and "not re-run" in readme, "README must state the prompt moved on without a baseline re-run"
    assert r["config_version"] and r["total_cost_usd"] > 0
    assert r["ungrounded_runs"] <= 2 and "cache_share" in r and r["latency_p95_ms"] > 0
    assert r["models"][0] == "anthropic:claude-sonnet-5-5"


def test_criterion_6_anthropic_down_report_is_served_by_gemini():
    r = _report("v3-anthropic-down")
    assert any("simulated outage: anthropic" in n for n in r["notes"]) and not any(m.startswith("anthropic") for m in r["models"])
    answered = [run for c in r["cases"] for run in c["runs"] if run["status"] in ("answered", "cannot_answer")]
    assert answered and all(run["served_by"].startswith("gemini") for run in answered)
    assert sum(c["passed"] for c in r["cases"]) >= len(r["cases"]) * 0.8


def test_criterion_7_readme_lists_both_reports():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    base, down = _report("v3-baseline"), _report("v3-anthropic-down")
    for tag, r in (("v3-baseline", base), ("v3-anthropic-down", down)):
        assert f"`evals/results/{tag}`" in readme, tag
        passed = sum(c["passed"] for c in r["cases"])
        assert f"{passed}/{len(r['cases'])}" in readme, tag
    roadmap = (ROOT / "agent-os" / "product" / "roadmap.md").read_text(encoding="utf-8")
    assert "**v3 agent**" in roadmap


async def test_criterion_8_repeated_tool_call_returns_repeated_instead_of_rerunning(config, prices, budget, caplog):
    from pydantic_ai import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from app.agent.core import Conversation, Service, build_agent, tool_call_trace
    from app.agent.tools import ToolContext
    from tests.fakes import USAGE, final, screening_model

    calls = {"n": 0}

    def repeating(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        if calls["n"] <= 3:
            return ModelResponse(parts=[ToolCallPart("list_airports", {"area": "New England"})], usage=USAGE, model_name="rep")
        return final({"status": "answered", "answer": "ok", "sources": [], "limitations": []}, model_name="rep")

    from app.data.registry import AirportRegistry

    deps = ToolContext(product_name="t", registry=AirportRegistry.load())
    from app.decide.guard import Guard

    svc = Service(build_agent(FunctionModel(repeating, model_name="rep")), Guard(screening_model()), budget, config.limits, prices, deps)
    conv = Conversation(max_turns=5)
    turn = await svc.ask(conv, "Which airports do you cover in New England?")
    returns = [p for m in conv.history for p in m.parts if isinstance(p, ToolReturnPart) and p.tool_name == "list_airports"]
    assert turn.status == "answered" and len(returns) == 3
    assert "BOS" in str(returns[0].content) and "Repeated" in type(returns[1].content).__name__ and "already" in str(returns[2].content)
    assert tool_call_trace(conv.history) == ["list_airports{'area': 'New England'}"] * 3
