from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config import Price
from app.llm.budget import Budget, BudgetExceeded, estimate_cost

PRICES = {"claude-haiku-5-5": Price(input=1.0, output=5.0), "claude-sonnet-5-5": Price(input=3.0, output=15.0)}


def test_reserve_settle_counts_real_cost(budget: Budget):
    rid = budget.reserve(0.02, kind="turn", model="pending")
    budget.settle(rid, cost_usd=0.005, model="m", input_tokens=10, output_tokens=5, latency_ms=3)
    assert budget.month_to_date() == pytest.approx(0.005)
    s = budget.stats()
    assert s.calls == 1 and s.remaining_usd == pytest.approx(0.995) and s.recent[0].status == "settled"


def test_reserve_refuses_over_cap(tmp_path):
    b = Budget(tmp_path / "x.db", cap_usd=0.05)
    rid = b.reserve(0.03, kind="turn", model="pending")
    b.settle(rid, cost_usd=0.03, model="m", input_tokens=1, output_tokens=1, latency_ms=1)
    with pytest.raises(BudgetExceeded) as e:
        b.reserve(0.03, kind="turn", model="pending")
    assert e.value.spent == pytest.approx(0.03) and e.value.cap == 0.05


def test_reservations_in_flight_count_toward_cap(tmp_path):
    b = Budget(tmp_path / "x.db", cap_usd=0.05)
    b.reserve(0.03, kind="turn", model="pending")
    with pytest.raises(BudgetExceeded):
        b.reserve(0.03, kind="turn", model="pending")


def test_release_without_failure_frees_the_estimate(tmp_path):
    b = Budget(tmp_path / "x.db", cap_usd=0.05)
    rid = b.reserve(0.03, kind="turn", model="pending")
    b.release(rid, failed=False)
    b.reserve(0.03, kind="turn", model="pending")  # fits again


def test_release_after_failure_keeps_the_estimate_charged(tmp_path):
    b = Budget(tmp_path / "x.db", cap_usd=0.05)
    rid = b.reserve(0.03, kind="turn", model="pending")
    b.release(rid, failed=True)
    with pytest.raises(BudgetExceeded):
        b.reserve(0.03, kind="turn", model="pending")


def test_cap_is_per_month(tmp_path):
    clock = [datetime(2026, 10, 31, tzinfo=UTC)]
    b = Budget(tmp_path / "x.db", cap_usd=0.05, now=lambda: clock[0])
    rid = b.reserve(0.05, kind="turn", model="pending")
    b.settle(rid, cost_usd=0.05, model="m", input_tokens=1, output_tokens=1, latency_ms=1)
    clock[0] = datetime(2026, 11, 1, tzinfo=UTC)
    b.reserve(0.05, kind="turn", model="pending")
    assert b.month_to_date() == 0.0


def test_estimate_cost_known_and_unknown_models():
    assert estimate_cost(PRICES, "claude-haiku-5-5", 1_000_000, 0) == pytest.approx(1.0)
    assert estimate_cost(PRICES, "anthropic:claude-haiku-5-5", 0, 1_000_000) == pytest.approx(5.0)
    assert estimate_cost(PRICES, "mystery", 1_000_000, 0) == pytest.approx(3.0)  # most expensive row
