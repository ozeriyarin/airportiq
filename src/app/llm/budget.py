"""Spend ledger with a hard monthly cap, checked in code before every paid call.

Reserve an estimate inside one `BEGIN IMMEDIATE` transaction (atomic under concurrency), then settle with the
real cost or release on failure. Over the cap → BudgetExceeded, never a silent downgrade. The provider-side
spend limit is the second line of defence; this ledger is the first.
"""

from __future__ import annotations

import atexit
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
    name = model.split(":", 1)[-1]
    price = prices.get(model) or prices.get(name)
    if price is None:  # a versioned name such as jev-1.14.0 prices from its family row jev-latest
        family = name.split("-")[0]
        price = next((p for k, p in prices.items() if k.split("-")[0] == family), None)
    if price is None:
        price = max(prices.values(), key=lambda p: p.input + p.output) if prices else Price(input=15.0, output=75.0)
    return (input_tokens * price.input + output_tokens * price.output) / 1_000_000


@dataclass
class Budget:
    db_path: Path | str
    cap_usd: float
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    stale_after_min: int = 10  # a reservation older than this with no settle or release belongs to a dead process
    _open: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        self.release_stale()
        atexit.register(self.release_open)

    def release_open(self) -> int:
        """Release every reservation this process still holds (normal exit, or an unhandled crash on the way out).
        Trade-off, chosen by the owner: a call billed by the provider just before the crash is then not counted here;
        the provider-console caps are the backstop for that case."""
        open_ids, self._open = list(self._open), set()
        if not open_ids:
            return 0
        with self._connect() as conn:
            conn.executemany("DELETE FROM spend WHERE id=? AND status='reserved'", [(rid,) for rid in open_ids])
        return len(open_ids)

    def release_stale(self) -> int:
        """Delete reservations older than `stale_after_min` that no process can settle any more (a killed worker)."""
        cutoff = (self.now() - timedelta(minutes=self.stale_after_min)).isoformat()
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM spend WHERE status='reserved' AND at < ?", (cutoff,))
        return cur.rowcount

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
        self._open.add(rid)
        return rid

    def settle(
        self, rid: str, *, cost_usd: float, model: str, input_tokens: int, output_tokens: int, latency_ms: int
    ) -> None:
        self._open.discard(rid)
        with self._connect() as conn:
            conn.execute(
                "UPDATE spend SET cost_usd=?, model=?, input_tokens=?, output_tokens=?, latency_ms=?, status='settled' WHERE id=?",
                (cost_usd, model, input_tokens, output_tokens, latency_ms, rid),
            )

    def release(self, rid: str, *, failed: bool) -> None:
        """A call that never reached the provider costs nothing; one that errored mid-way keeps its estimate."""
        self._open.discard(rid)
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
