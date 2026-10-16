"""Quyết định gồng có kế hoạch (mục 6c). Chỉ ghi vào SQLite của ứng dụng."""
from __future__ import annotations

from datetime import date

from ..models import HoldDecision
from ..util import now_vn
from .db import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS hold_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, broker TEXT NOT NULL, account_id TEXT NOT NULL, symbol TEXT NOT NULL,
  decided_at TEXT NOT NULL, exit_close_below REAL NOT NULL, ratio_floor_pct REAL, review_on TEXT NOT NULL,
  reason TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE (broker, account_id, symbol)
);
"""


def _row(r) -> HoldDecision:
    d = dict(r)
    d.pop("created_at", None)
    return HoldDecision(**d)


class HoldRepo:
    def __init__(self, store: Store):
        self._db, self._lock = store._db, store._lock
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def list(self, broker: str, account_id: str | None = None) -> list[HoldDecision]:
        q, args = "SELECT * FROM hold_decisions WHERE broker=?", [broker]
        if account_id:
            q += " AND account_id=?"; args.append(account_id)
        with self._lock:
            return [_row(r) for r in self._db.execute(q + " ORDER BY symbol", args).fetchall()]

    def get(self, broker: str, account_id: str, symbol: str) -> HoldDecision | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM hold_decisions WHERE broker=? AND account_id=? AND symbol=?",
                                 (broker, account_id, symbol.upper())).fetchone()
        return _row(r) if r else None

    def by_id(self, hold_id: int) -> HoldDecision | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM hold_decisions WHERE id=?", (hold_id,)).fetchone()
        return _row(r) if r else None

    def upsert(self, *, broker: str, account_id: str, symbol: str, exit_close_below: float,
               ratio_floor_pct: float | None, review_on: date, reason: str, decided_at: date | None = None) -> HoldDecision:
        old = self.get(broker, account_id, symbol)
        decided = (old.decided_at if old else None) or decided_at or now_vn().date()
        with self._lock:
            self._db.execute(
                """INSERT INTO hold_decisions (broker, account_id, symbol, decided_at, exit_close_below, ratio_floor_pct,
                   review_on, reason, created_at) VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (broker, account_id, symbol) DO UPDATE SET exit_close_below=excluded.exit_close_below,
                   ratio_floor_pct=excluded.ratio_floor_pct, review_on=excluded.review_on, reason=excluded.reason""",
                (broker, account_id, symbol.upper(), decided.isoformat(), exit_close_below, ratio_floor_pct,
                 review_on.isoformat(), reason, now_vn().isoformat()))
            self._db.commit()
        return self.get(broker, account_id, symbol)  # type: ignore[return-value]

    def delete(self, hold_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM hold_decisions WHERE id=?", (hold_id,))
            self._db.commit()
