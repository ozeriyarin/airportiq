"""Grounding check: every score, day count or percentage in an answer must appear in that turn's tool results."""

from __future__ import annotations

import re

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
# Candidates: decimals, percentages, integers followed by day/days, and "N of M days".
CANDIDATE = re.compile(
    r"(?<![\w.])(?:"
    r"(?P<pct>\d+(?:\.\d+)?)\s?%"
    r"|(?P<of>\d+)\s+of\s+(?P<ofm>\d+)\s+days?"
    r"|(?P<days>\d+(?:\.\d+)?)\s+(?:days?|day)\b"
    r"|(?P<dec>\d+\.\d+)"
    r")(?!\w)(?!\.\d)",  # a sentence-ending period is fine; a further digit is not
    re.IGNORECASE,
)
LIST_MARKER = re.compile(r"(?m)^\s*\d+\.\s")
TOLERANCE = 0.051  # 20.3 matches 20.34; 42.3 matches 42.30
SMALL_TOLERANCE = 0.0051  # below 1 the absolute tolerance would let 0.34 match a weight of 0.3


def _is_year(token: str) -> bool:
    return token.isdigit() and len(token) == 4 and 1900 <= int(token) <= 2100


def numbers_in(answer: str) -> list[str]:
    """Candidate numbers in an answer, as written, excluding years and list markers."""
    text = LIST_MARKER.sub("", answer)
    out: list[str] = []
    for m in CANDIDATE.finditer(text):
        tokens = [m.group("pct"), m.group("of"), m.group("ofm"), m.group("days"), m.group("dec")]
        for tok in tokens:
            if tok and not _is_year(tok) and tok not in out:
                out.append(tok)
    return out


def tool_numbers(tool_results: list[str]) -> list[float]:
    """Absolute values: a tool difference of -12.3 grounds an answer that says 12.3 more."""
    return [abs(float(x)) for text in tool_results for x in NUMBER.findall(text)]


def ungrounded_numbers(answer: str, tool_results: list[str]) -> list[str]:
    """Numbers in the answer that no tool result supports. Empty when the turn had no tool results.

    `tool_results` is the grounding pool: this turn's tool outputs, earlier turns' outputs in the same conversation
    (follow-ups reuse them) and the data facts the prompt states (data range, scoring version, hazard weights).
    """
    if not tool_results:
        return []
    pool = tool_numbers(tool_results)
    missing: list[str] = []
    for tok in numbers_in(answer):
        value = abs(float(tok))
        tolerance = TOLERANCE if value >= 1 else SMALL_TOLERANCE
        if not any(abs(value - p) <= tolerance for p in pool):
            missing.append(tok)
    return missing
