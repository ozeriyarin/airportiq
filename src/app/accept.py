"""`agent accept <url>`: the live acceptance pass against a deployed service. Endpoint checks plus the cases in
evals/accept/cases.yaml run over HTTP with session continuity, checked with the eval checker. Prints a pass/fail
table with evidence and returns 0 when every row passes, else 1. Grounding needs tool outputs the API does not
expose, so it is covered by `agent eval` on the same cases, not here."""

from __future__ import annotations

import time
from pathlib import Path

import httpx2
from pydantic import BaseModel, Field

from app.agent.schema import Turn
from app.config import ROOT
from app.evals.cases import EvalCase, load_cases
from app.evals.runner import check

ACCEPT_DIR = ROOT / "evals" / "accept"


class Row(BaseModel):
    check: str
    passed: bool
    evidence: str


class AcceptReport(BaseModel):
    url: str
    rows: list[Row] = Field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(r.passed for r in self.rows)

    @property
    def exit_code(self) -> int:
        return 0 if all(r.passed for r in self.rows) else 1


def _row(report: AcceptReport, name: str, ok: bool, evidence: str) -> None:
    report.rows.append(Row(check=name, passed=ok, evidence=evidence[:300]))


async def endpoint_checks(http: httpx2.AsyncClient, base: str, report: AcceptReport) -> None:
    r = await http.get(f"{base}/health")
    body = r.json() if r.status_code == 200 else {}
    data = body.get("data") or {}
    _row(report, "GET /health", r.status_code == 200 and body.get("status") == "ok" and bool(body.get("models")),
         f"{r.status_code}; models {body.get('models')}; guard {body.get('guard')}; airports {data.get('airports')}")
    r = await http.get(f"{base}/api/docs")
    _row(report, "GET /api/docs", r.status_code == 200 and "swagger" in r.text.lower(), f"{r.status_code}, swagger {'swagger' in r.text.lower()}")
    r = await http.get(f"{base}/")
    _row(report, "GET / chat page", r.status_code == 200 and "<title>airportiq</title>" in r.text, f"{r.status_code}, {len(r.text)} bytes, title present {'<title>airportiq</title>' in r.text}")
    r = await http.get(f"{base}/api/stats")
    r2 = await http.get(f"{base}/api/stats", headers={"Authorization": "Bearer wrong-token"})
    _row(report, "GET /api/stats without and with a wrong token", r.status_code == 401 and r2.status_code == 401, f"{r.status_code}, {r2.status_code}")
    r = await http.delete(f"{base}/api/sessions/does-not-exist")
    _row(report, "DELETE /api/sessions/{id}", r.status_code == 204, f"{r.status_code}")
    r = await http.post(f"{base}/api/chat", json={"message": ""})
    r2 = await http.post(f"{base}/api/chat", json={})
    _row(report, "POST /api/chat empty body / no message", r.status_code == 422 and r2.status_code == 422, f"{r.status_code}, {r2.status_code}")


async def ask(http: httpx2.AsyncClient, base: str, message: str, session_id: str | None) -> tuple[Turn, str | None, int]:
    started = time.perf_counter()
    r = await http.post(f"{base}/api/chat", json={"message": message, "session_id": session_id})
    wall = int((time.perf_counter() - started) * 1000)
    if r.status_code != 200:
        return Turn(status="unavailable", answer=f"HTTP {r.status_code}: {r.text[:120]}"), session_id, wall
    j = r.json()
    return Turn.model_validate(j), j.get("session_id", session_id), wall


async def case_checks(http: httpx2.AsyncClient, base: str, cases: list[EvalCase], report: AcceptReport) -> None:
    """Each case is a fresh session; prior turns run first in that session so follow-ups depend on real context."""
    for case in cases:
        session: str | None = None
        for prior in case.prior_turns:
            _, session, _ = await ask(http, base, prior, session)
        turn, session, wall = await ask(http, base, case.question, session)
        reasons = check(case, turn)
        words = len(turn.answer.split())
        evidence = (f"status {turn.status}; served_by {turn.served_by}; guardrail {turn.guardrail}; tools {turn.tools_used}; "
                    f"{turn.cost_usd:.4f} USD; {turn.latency_ms} ms; {words} words")
        if case.category in ("off_topic", "injection", "in_scope") and case.id.startswith("greet"):
            evidence += f"; cost {turn.cost_usd}"
        if reasons:
            evidence += "; FAIL: " + "; ".join(reasons)
        _row(report, f"{case.category}: {case.id}", not reasons, evidence)


def render(report: AcceptReport) -> str:
    lines = [f"# Acceptance — {report.url}", "", f"{report.passed}/{len(report.rows)} checks passed, exit code {report.exit_code}", "",
             "| Check | Result | Evidence |", "|---|---|---|"]
    for r in report.rows:
        lines.append(f"| {r.check} | {'PASS' if r.passed else 'FAIL'} | {r.evidence.replace('|', '/')} |")
    return "\n".join(lines)


async def run_accept(http: httpx2.AsyncClient, base: str, cases_path: Path = ACCEPT_DIR / "cases.yaml") -> AcceptReport:
    report = AcceptReport(url=base)
    await endpoint_checks(http, base, report)
    await case_checks(http, base, load_cases(cases_path), report)
    return report
