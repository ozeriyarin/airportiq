"""Acceptance criteria of agent-os/specs/2026-11-01-v5-voice, one test per criterion, all offline (served HTML)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.sessions import SessionStore


def _page(service, budget) -> str:
    client = TestClient(create_app(service, SessionStore(max_turns=5, ttl_s=60), budget, model_names=["fake"], guard_name="g"))
    r = client.get("/")
    assert r.status_code == 200
    return r.text


def test_criterion_1_mic_hidden_until_supported_and_toggle_with_aria_state(service, budget):
    html = _page(service, budget)
    assert re.search(r'<button id="mic"[^>]*hidden', html) and 'id="speak"' in html and 'aria-pressed="false"' in html
    assert "window.SpeechRecognition || window.webkitSpeechRecognition" in html and "mic.hidden = false" in html
    assert html.count("<svg") >= 2 and not re.search(r"<script[^>]+src=", html)


def test_criterion_2_recognition_submits_and_spoken_questions_are_read_back(service, budget):
    html = _page(service, budget)
    assert "rec.onresult" in html and "requestSubmit()" in html and "spoken = true" in html
    assert "const wanted = spoken || readAloud" in html and "sayAnswer(j.answer)" in html
    assert "sayAnswer(j.sources" not in html and "sayAnswer(tech" not in html


def test_criterion_3_read_aloud_preference_persists_and_cancels(service, budget):
    html = _page(service, budget)
    assert "localStorage.getItem('airportiq.readAloud')" in html and "localStorage.setItem('airportiq.readAloud'" in html
    assert "if (!readAloud && window.speechSynthesis) speechSynthesis.cancel();" in html
    assert html.count("try {") >= 2  # private windows throw on localStorage


def test_criterion_4_no_external_script_and_only_text_reaches_the_server(service, budget):
    html = _page(service, budget)
    script = html.split("<script>")[1]
    assert "https://" not in script and "fetch('/api/chat'" in script and "fetch('/health')" in script
    assert script.count("fetch(") == 2 and "audio" not in script.lower()
