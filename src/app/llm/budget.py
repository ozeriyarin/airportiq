"""Spend ledger with a hard monthly cap, checked in code before every paid call.

Reserve an estimate inside one `BEGIN IMMEDIATE` transaction (atomic under concurrency), then settle with the
real cost or release on failure. Over the cap → BudgetExceeded, never a silent downgrade. The provider-side
spend limit is the second line of defence; this ledger is the first.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from app.config import Price


class BudgetExceeded(RuntimeError):
    def __init__(self, spent: float, estimate: float, cap: float) -> None:
        super().__init__(f"monthly budget reached: spent {spent:.4f} USD, next call ~{estimate:.4f}, cap {cap:.2f}")
        self.spent, self.estimate, self.cap = spent, estimate, cap


class CallRecord(BaseModel):
    id: str
    month: str
    kind: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    status: str
    at: str


class Stats(BaseModel):
    cap_usd: float
    month: str
    spent_usd: float
    remaining_usd: float
    calls: int
    recent: list[CallRecord]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS spend (
  id TEXT PRIMARY KEY, month TEXT NOT NULL, kind TEXT NOT NULL, model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL, latency_ms INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK (status IN ('reserved','settled','failed')), at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS spend_month ON spend(month);
"""


def estimate_cost(prices: dict[str, Price], model: str, input_tokens: int, output_tokens: int) -> float:
    """Price a call from the table; an unknown model is charged the most expensive row (refusing is recoverable)."""
    price = prices.get(model) or prices.get(model.split(":", 1)[-1])
    if price is None:
        price = max(prices.values(), key=lambda p: p.input + p.output) if prices else Price(input=15.0, output=75.0)
    return (input_tokens * price.input + output_tokens * price.output) / 1_000_000


@dataclass
class Budget:
    db_path: Path | str
    cap_usd: float
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def __post_init__(self) -> None:
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _month(self) -> str:
        return self.now().strftime("%Y-%m")

    def reserve(self, estimate_usd: float, *, kind: str, model: str) -> str:
        """Hold `estimate_usd` against this month (settled + reserved + failed); BudgetExceeded past the cap."""
        month, rid = self._month(), uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            spent = conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM spend WHERE month=?", (month,)).fetchone()[0]
            if spent + estimate_usd > self.cap_usd:
                conn.execute("ROLLBACK")
                raise BudgetExceeded(spent, estimate_usd, self.cap_usd)
            conn.execute(
                "INSERT INTO spend VALUES (?,?,?,?,0,0,?,0,'reserved',?)",
                (rid, month, kind, model, estimate_usd, self.now().isoformat()),
            )
            conn.execute("COMMIT")
        return rid

    def settle(
        self, rid: str, *, cost_usd: float, model: str, input_tokens: int, output_tokens: int, latency_ms: int
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE spend SET cost_usd=?, model=?, input_tokens=?, output_tokens=?, latency_ms=?, status='settled' WHERE id=?",
                (cost_usd, model, input_tokens, output_tokens, latency_ms, rid),
            )

    def release(self, rid: str, *, failed: bool) -> None:
        """A call that never reached the provider costs nothing; one that errored mid-way keeps its estimate."""
        with self._connect() as conn:
            if failed:
                conn.execute("UPDATE spend SET status='failed' WHERE id=?", (rid,))
            else:
                conn.execute("DELETE FROM spend WHERE id=?", (rid,))

    def month_to_date(self) -> float:
        with self._connect() as conn:
            return float(
                conn.execute(
                    "SELECT COALESCE(SUM(cost_usd),0) FROM spend WHERE month=? AND status='settled'", (self._month(),)
                ).fetchone()[0]
            )

    def stats(self, recent: int = 20) -> Stats:
        month = self._month()
        with self._connect() as conn:
            spent = float(
                conn.execute(
                    "SELECT COALESCE(SUM(cost_usd),0) FROM spend WHERE month=? AND status='settled'", (month,)
                ).fetchone()[0]
            )
            calls = conn.execute("SELECT COUNT(*) FROM spend WHERE month=? AND status='settled'", (month,)).fetchone()[0]
            rows = conn.execute("SELECT * FROM spend WHERE month=? ORDER BY at DESC LIMIT ?", (month, recent)).fetchall()
        return Stats(
            cap_usd=self.cap_usd,
            month=month,
            spent_usd=spent,
            remaining_usd=max(0.0, self.cap_usd - spent),
            calls=calls,
            recent=[CallRecord(**dict(r)) for r in rows],
        )
