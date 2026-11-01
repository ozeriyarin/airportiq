from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.core import Service, build_agent
from app.agent.schema import Turn
from app.agent.tools import ToolContext
from app.config import ROOT
from app.decide.guard import Guard
from app.evals.cases import EvalCase, load_cases
from app.evals.report import render_markdown
from app.evals.runner import check, run_all
from tests.fakes import answer_model, screening_model


def test_committed_cases_load_and_have_unique_ids():
    cases = load_cases(ROOT / "evals" / "cases.yaml")
    assert len(cases) >= 5 and len({c.id for c in cases}) == len(cases)
    assert {c.category for c in cases} >= {"in_scope", "off_topic", "injection", "false_positive"}


def test_duplicate_ids_are_rejected(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("cases:\n  - {id: a, category: x, question: q, expect: [answered]}\n  - {id: a, category: x, question: q, expect: [answered]}\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(p)


def test_check_reports_every_reason():
    case = EvalCase(id="c", category="in_scope", question="q", expect=["answered"], must_contain=["paris"], must_not_contain=["rome"], tools=["about"])
    turn = Turn(status="cannot_answer", answer="Rome it is", tools_used=[])
    reasons = check(case, turn)
    assert len(reasons) == 4 and any("status" in r for r in reasons) and any("'about'" in r for r in reasons)


async def test_runner_scores_pass_fail_and_flaky(config, prices, budget):
    svc = Service(build_agent(answer_model("hello paris")), Guard(screening_model()), budget, config.limits, prices, ToolContext(product_name="p"))
    cases = [
        EvalCase(id="ok", category="in_scope", question="q", expect=["answered"], must_contain=["paris"]),
        EvalCase(id="bad", category="in_scope", question="q", expect=["refused_off_topic"]),
        EvalCase(id="multi", category="followup", question="q", prior_turns=["first"], expect=["answered"]),
    ]
    report = await run_all(svc, cases, repeat=2, models=["fake"], guard="g", config_version="t", max_turns=5)
    assert report.exit_code == 1 and report.by_category["in_scope"] == {"cases": 2, "passed": 1, "runs": 4, "runs_passed": 2}
    assert report.cases[2].passed and report.cases[2].runs[0].cost_usd > report.cases[0].runs[0].cost_usd
    md = render_markdown(report)
    assert "1 of" not in md and "`bad`" in md and "Served by: fake-answer" in md
