"""Lưu từng lần mua (lô) và lần quan sát danh mục gần nhất để tự phát hiện mua thêm. Chỉ ghi vào SQLite của ứng dụng."""
from __future__ import annotations

from datetime import date
from typing import Any

from ..models import Lot
from ..util import now_vn
from .db import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS lots (
  id INTEGER PRIMARY KEY AUTOINCREMENT, broker TEXT NOT NULL, account_id TEXT NOT NULL, symbol TEXT NOT NULL,
  buy_date TEXT NOT NULL, quantity INTEGER NOT NULL, remaining INTEGER NOT NULL, price REAL NOT NULL,
  source TEXT NOT NULL, add_on_loss INTEGER NOT NULL DEFAULT 0, stop_price REAL,
  trigger_date TEXT, trigger_price REAL, estimated INTEGER NOT NULL DEFAULT 0, note TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lots_pos ON lots (broker, account_id, symbol);
CREATE TABLE IF NOT EXISTS position_obs (
  broker TEXT NOT NULL, account_id TEXT NOT NULL, symbol TEXT NOT NULL,
  quantity INTEGER NOT NULL, avg_cost REAL NOT NULL, observed_at TEXT NOT NULL,
  PRIMARY KEY (broker, account_id, symbol)
);
"""


class LotError(ValueError):
    pass


def _row(r) -> Lot:
    d = dict(r)
    d.pop("created_at", None)
    d["add_on_loss"] = bool(d["add_on_loss"])
    d["estimated"] = bool(d["estimated"])
    return Lot(**d)


class LotRepo:
    def __init__(self, store: Store):
        self._db, self._lock = store._db, store._lock
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def lots(self, broker: str, account_id: str | None = None, symbol: str | None = None, *,
             open_only: bool = False) -> list[Lot]:
        q, args = "SELECT * FROM lots WHERE broker=?", [broker]
        if account_id:
            q += " AND account_id=?"; args.append(account_id)
        if symbol:
            q += " AND symbol=?"; args.append(symbol.upper())
        if open_only:
            q += " AND remaining > 0"
        with self._lock:
            return [_row(r) for r in self._db.execute(q + " ORDER BY buy_date, id", args).fetchall()]

    def get(self, lot_id: int) -> Lot:
        with self._lock:
            r = self._db.execute("SELECT * FROM lots WHERE id=?", (lot_id,)).fetchone()
        if not r:
            raise LotError("Không có lần mua này")
        return _row(r)

    def add(self, *, broker: str, account_id: str, symbol: str, buy_date: date, quantity: int, price: float,
            source: str, add_on_loss: bool, stop_price: float | None = None, estimated: bool = False,
            note: str | None = None) -> Lot:
        if quantity <= 0 or price <= 0:
            raise LotError("Số lượng và giá mua phải lớn hơn 0")
        if buy_date > now_vn().date():
            raise LotError("Ngày mua không được ở tương lai")
        with self._lock:
            cur = self._db.execute(
                """INSERT INTO lots (broker, account_id, symbol, buy_date, quantity, remaining, price, source, add_on_loss,
                   stop_price, estimated, note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (broker, account_id, symbol.upper(), buy_date.isoformat(), quantity, quantity, price, source,
                 int(add_on_loss), stop_price, int(estimated), note, now_vn().isoformat()))
            self._db.commit()
        return self.get(cur.lastrowid)

    def update(self, lot_id: int, **fields: Any) -> Lot:
        allowed = {"stop_price", "add_on_loss", "note", "buy_date", "price", "quantity", "remaining",
                   "trigger_date", "trigger_price"}
        cols = {k: v for k, v in fields.items() if k in allowed}
        lot = self.get(lot_id)
        if "quantity" in cols and "remaining" not in cols:
            sold = lot.quantity - lot.remaining
            cols["remaining"] = max(0, cols["quantity"] - sold)
        for k, v in list(cols.items()):
            if isinstance(v, date):
                cols[k] = v.isoformat()
            elif isinstance(v, bool):
                cols[k] = int(v)
        if cols:
            with self._lock:
                self._db.execute(f"UPDATE lots SET {', '.join(k + '=?' for k in cols)} WHERE id=?", (*cols.values(), lot_id))
                self._db.commit()
        return self.get(lot_id)

    def delete(self, lot_id: int) -> None:
        self.get(lot_id)
        with self._lock:
            self._db.execute("DELETE FROM lots WHERE id=?", (lot_id,))
            self._db.commit()

    def delete_for(self, broker: str, account_id: str, symbol: str | None = None) -> None:
        q, args = "DELETE FROM lots WHERE broker=? AND account_id=?", [broker, account_id]
        if symbol:
            q += " AND symbol=?"; args.append(symbol.upper())
        with self._lock:
            self._db.execute(q, args)
            self._db.commit()

    def reduce_newest_first(self, broker: str, account_id: str, symbol: str, sold: int) -> None:
        """Bán ra thì trừ vào lô mua gần nhất trước: lô mua thêm khi đang lỗ là lô luật yêu cầu bán trước."""
        for lot in reversed(self.lots(broker, account_id, symbol, open_only=True)):
            if sold <= 0:
                break
            take = min(sold, lot.remaining)
            self.update(lot.id, remaining=lot.remaining - take)
            sold -= take

    # ---------- quan sát danh mục ----------

    def last_obs(self, broker: str, account_id: str, symbol: str) -> tuple[int, float] | None:
        with self._lock:
            r = self._db.execute("SELECT quantity, avg_cost FROM position_obs WHERE broker=? AND account_id=? AND symbol=?",
                                 (broker, account_id, symbol)).fetchone()
        return (r["quantity"], r["avg_cost"]) if r else None

    def save_obs(self, broker: str, account_id: str, symbol: str, quantity: int, avg_cost: float) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO position_obs (broker, account_id, symbol, quantity, avg_cost, observed_at) VALUES (?,?,?,?,?,?)
                   ON CONFLICT (broker, account_id, symbol) DO UPDATE SET quantity=excluded.quantity,
                   avg_cost=excluded.avg_cost, observed_at=excluded.observed_at""",
                (broker, account_id, symbol, quantity, avg_cost, now_vn().isoformat()))
            self._db.commit()

    def symbols_observed(self, broker: str, account_id: str) -> set[str]:
        with self._lock:
            rows = self._db.execute("SELECT symbol FROM position_obs WHERE broker=? AND account_id=?", (broker, account_id)).fetchall()
        return {r["symbol"] for r in rows}

    def drop_obs(self, broker: str, account_id: str, symbol: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM position_obs WHERE broker=? AND account_id=? AND symbol=?", (broker, account_id, symbol))
            self._db.commit()
