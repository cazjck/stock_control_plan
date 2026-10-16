"""Nhật ký đảo hàng (mục 6b): người dùng tự ghi lần bán và mua lại. Chỉ ghi vào SQLite của ứng dụng."""
from __future__ import annotations

from datetime import date

from ..models import RotationTrade
from ..util import now_vn
from .db import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS rotation_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, broker TEXT NOT NULL, account_id TEXT NOT NULL, symbol TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('sell','buy')), trade_date TEXT NOT NULL, quantity INTEGER NOT NULL,
  price REAL NOT NULL, note TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rotation_pos ON rotation_trades (broker, account_id, symbol);
"""


def _row(r) -> RotationTrade:
    d = dict(r)
    d.pop("created_at", None)
    return RotationTrade(**d)


class RotationRepo:
    def __init__(self, store: Store):
        self._db, self._lock = store._db, store._lock
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def trades(self, broker: str, account_id: str | None = None, symbol: str | None = None) -> list[RotationTrade]:
        q, args = "SELECT * FROM rotation_trades WHERE broker=?", [broker]
        if account_id:
            q += " AND account_id=?"; args.append(account_id)
        if symbol:
            q += " AND symbol=?"; args.append(symbol.upper())
        with self._lock:
            return [_row(r) for r in self._db.execute(q + " ORDER BY trade_date, id", args).fetchall()]

    def add(self, *, broker: str, account_id: str, symbol: str, side: str, trade_date: date, quantity: int,
            price: float, note: str | None = None) -> RotationTrade:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO rotation_trades (broker, account_id, symbol, side, trade_date, quantity, price, note, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (broker, account_id, symbol.upper(), side, trade_date.isoformat(), quantity, price, note,
                 now_vn().isoformat()))
            self._db.commit()
            r = self._db.execute("SELECT * FROM rotation_trades WHERE id=?", (cur.lastrowid,)).fetchone()
        return _row(r)

    def get(self, trade_id: int) -> RotationTrade | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM rotation_trades WHERE id=?", (trade_id,)).fetchone()
        return _row(r) if r else None

    def delete(self, trade_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM rotation_trades WHERE id=?", (trade_id,))
            self._db.commit()
