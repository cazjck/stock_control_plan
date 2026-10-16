"""Lưu trữ sổ danh mục tổng trong cùng file SQLite. Chỉ ghi vào cơ sở dữ liệu của ứng dụng, không gọi broker."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any

from ..models import LedgerAccount, LedgerDebt, LedgerPosition
from ..util import now_vn
from .db import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_accounts (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual',
  source_broker TEXT, source_account TEXT, cash REAL NOT NULL DEFAULT 0,
  ratio_kind TEXT NOT NULL DEFAULT 'equity_over_value', ratio_pct REAL, ratio_ref_value REAL,
  initial_pct REAL, maintenance_pct REAL, liquidation_pct REAL, synced_at TEXT, note TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger_positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL REFERENCES ledger_accounts(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL, quantity INTEGER NOT NULL, avg_cost REAL NOT NULL, last_price REAL,
  bought_at TEXT, note TEXT, UNIQUE (account_id, symbol)
);
CREATE TABLE IF NOT EXISTS ledger_debts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL REFERENCES ledger_accounts(id) ON DELETE CASCADE,
  symbol TEXT, principal REAL NOT NULL, remaining_principal REAL NOT NULL, accrued_interest REAL NOT NULL DEFAULT 0,
  annual_rate_pct REAL, disbursement_date TEXT, due_date TEXT, note TEXT
);
"""

ACCOUNT_FIELDS = ("name", "cash", "ratio_kind", "ratio_pct", "ratio_ref_value", "initial_pct",
                  "maintenance_pct", "liquidation_pct", "note")


class LedgerError(ValueError):
    pass


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "danh-muc"


def _d(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, (date, datetime)) else v


class LedgerRepo:
    def __init__(self, store: Store):
        self._db = store._db
        self._lock = store._lock
        with self._lock:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.executescript(SCHEMA)
            self._db.commit()

    # ---------- tiểu danh mục ----------

    def accounts(self) -> list[LedgerAccount]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM ledger_accounts ORDER BY source DESC, created_at").fetchall()
        return [LedgerAccount(**{k: r[k] for k in r.keys() if k != "created_at"}) for r in rows]

    def account(self, account_id: str) -> LedgerAccount:
        a = next((x for x in self.accounts() if x.id == account_id), None)
        if not a:
            raise LedgerError(f"Không có tiểu danh mục '{account_id}'")
        return a

    def create_account(self, name: str, **fields: Any) -> LedgerAccount:
        name = name.strip()
        if not name:
            raise LedgerError("Cần đặt tên cho tiểu danh mục, ví dụ SSI hoặc VPS")
        if any(a.name.lower() == name.lower() for a in self.accounts()):
            raise LedgerError(f"Đã có tiểu danh mục tên '{name}'")
        base, i = _slug(name), 1
        existing = {a.id for a in self.accounts()} | {"all"}
        aid = base
        while aid in existing:
            i += 1
            aid = f"{base}-{i}"
        cols = {k: fields[k] for k in ACCOUNT_FIELDS if k in fields and k != "name"}
        with self._lock:
            self._db.execute(
                f"INSERT INTO ledger_accounts (id, name, created_at{''.join(', ' + k for k in cols)}) "
                f"VALUES (?, ?, ?{', ?' * len(cols)})", (aid, name, now_vn().isoformat(), *cols.values()))
            self._db.commit()
        return self.account(aid)

    def update_account(self, account_id: str, **fields: Any) -> LedgerAccount:
        a = self.account(account_id)
        cols = {k: v for k, v in fields.items() if k in ACCOUNT_FIELDS}
        if a.source == "sync":
            cols = {k: v for k, v in cols.items() if k in ("name", "note")}
        if cols:
            with self._lock:
                self._db.execute(f"UPDATE ledger_accounts SET {', '.join(k + '=?' for k in cols)} WHERE id=?",
                                 (*cols.values(), account_id))
                self._db.commit()
        return self.account(account_id)

    def delete_account(self, account_id: str) -> None:
        self.account(account_id)
        with self._lock:
            self._db.execute("DELETE FROM ledger_accounts WHERE id=?", (account_id,))
            self._db.commit()

    def _require_manual(self, account_id: str) -> LedgerAccount:
        a = self.account(account_id)
        if a.source == "sync":
            raise LedgerError(f"'{a.name}' được đồng bộ từ {a.source_broker}, không sửa tay. Hãy đồng bộ lại để cập nhật.")
        return a

    # ---------- cổ phiếu ----------

    def positions(self, account_id: str | None = None) -> list[LedgerPosition]:
        q, args = "SELECT * FROM ledger_positions", ()
        if account_id:
            q, args = q + " WHERE account_id=?", (account_id,)
        with self._lock:
            rows = self._db.execute(q + " ORDER BY symbol", args).fetchall()
        return [LedgerPosition(**dict(r)) for r in rows]

    def record_purchase(self, account_id: str, symbol: str, quantity: int, *, price: float | None = None,
                        total_amount: float | None = None, bought_at: date | None = None) -> LedgerPosition:
        """Ghi một lần mua. Nếu mã đã có trong tiểu danh mục thì cộng dồn và tính lại giá vốn bình quân."""
        self._require_manual(account_id)
        symbol = symbol.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{2,10}", symbol):
            raise LedgerError("Mã cổ phiếu không hợp lệ")
        if quantity <= 0:
            raise LedgerError("Số lượng phải lớn hơn 0")
        if (price is None) == (total_amount is None):
            raise LedgerError("Nhập giá mua mỗi cổ phiếu hoặc tổng tiền mua, chỉ một trong hai")
        cost = total_amount if total_amount is not None else price * quantity  # type: ignore[operator]
        if cost <= 0:
            raise LedgerError("Giá mua hoặc tổng tiền phải lớn hơn 0")
        with self._lock:
            r = self._db.execute("SELECT * FROM ledger_positions WHERE account_id=? AND symbol=?", (account_id, symbol)).fetchone()
            if r:
                q = r["quantity"] + quantity
                avg = (r["quantity"] * r["avg_cost"] + cost) / q
                self._db.execute("UPDATE ledger_positions SET quantity=?, avg_cost=? WHERE id=?", (q, avg, r["id"]))
                pid = r["id"]
            else:
                cur = self._db.execute(
                    "INSERT INTO ledger_positions (account_id, symbol, quantity, avg_cost, last_price, bought_at) VALUES (?,?,?,?,?,?)",
                    (account_id, symbol, quantity, cost / quantity, cost / quantity, _d(bought_at)))
                pid = cur.lastrowid
            self._db.commit()
        return next(p for p in self.positions(account_id) if p.id == pid)

    def _position(self, pid: int) -> LedgerPosition:
        p = next((x for x in self.positions() if x.id == pid), None)
        if not p:
            raise LedgerError("Không có dòng cổ phiếu này")
        return p

    def update_position(self, pid: int, *, quantity: int | None = None, avg_cost: float | None = None,
                        last_price: float | None = None, bought_at: date | None = None) -> LedgerPosition:
        p = self._position(pid)
        self._require_manual(p.account_id)
        if quantity is not None and quantity <= 0:
            raise LedgerError("Số lượng phải lớn hơn 0. Muốn bỏ mã này thì xoá dòng.")
        if avg_cost is not None and avg_cost <= 0:
            raise LedgerError("Giá vốn phải lớn hơn 0")
        with self._lock:
            self._db.execute(
                "UPDATE ledger_positions SET quantity=COALESCE(?, quantity), avg_cost=COALESCE(?, avg_cost), "
                "last_price=COALESCE(?, last_price), bought_at=COALESCE(?, bought_at) WHERE id=?",
                (quantity, avg_cost, last_price, _d(bought_at), pid))
            self._db.commit()
        return self._position(pid)

    def delete_position(self, pid: int) -> None:
        p = self._position(pid)
        self._require_manual(p.account_id)
        with self._lock:
            self._db.execute("DELETE FROM ledger_positions WHERE id=?", (pid,))
            self._db.commit()

    # ---------- nợ margin ----------

    def debts(self, account_id: str | None = None) -> list[LedgerDebt]:
        q, args = "SELECT * FROM ledger_debts", ()
        if account_id:
            q, args = q + " WHERE account_id=?", (account_id,)
        with self._lock:
            rows = self._db.execute(q + " ORDER BY due_date IS NULL, due_date", args).fetchall()
        return [LedgerDebt(**dict(r)) for r in rows]

    def add_debt(self, account_id: str, *, principal: float, remaining_principal: float | None = None,
                 accrued_interest: float = 0.0, annual_rate_pct: float | None = None, symbol: str | None = None,
                 disbursement_date: date | None = None, due_date: date | None = None, note: str | None = None) -> LedgerDebt:
        self._require_manual(account_id)
        if principal <= 0:
            raise LedgerError("Nợ gốc phải lớn hơn 0")
        remaining = principal if remaining_principal is None else remaining_principal
        if remaining < 0 or accrued_interest < 0:
            raise LedgerError("Nợ còn lại và lãi dồn không được âm")
        if annual_rate_pct is not None and not 0 <= annual_rate_pct <= 100:
            raise LedgerError("Lãi suất năm phải nằm trong 0 đến 100%")
        with self._lock:
            cur = self._db.execute(
                """INSERT INTO ledger_debts (account_id, symbol, principal, remaining_principal, accrued_interest,
                   annual_rate_pct, disbursement_date, due_date, note) VALUES (?,?,?,?,?,?,?,?,?)""",
                (account_id, symbol.strip().upper() if symbol else None, principal, remaining, accrued_interest,
                 annual_rate_pct, _d(disbursement_date), _d(due_date), note))
            self._db.commit()
        return next(d for d in self.debts(account_id) if d.id == cur.lastrowid)

    def _debt(self, did: int) -> LedgerDebt:
        d = next((x for x in self.debts() if x.id == did), None)
        if not d:
            raise LedgerError("Không có khoản nợ này")
        return d

    def update_debt(self, did: int, **fields: Any) -> LedgerDebt:
        d = self._debt(did)
        self._require_manual(d.account_id)
        allowed = ("symbol", "principal", "remaining_principal", "accrued_interest", "annual_rate_pct",
                   "disbursement_date", "due_date", "note")
        cols = {k: _d(v) for k, v in fields.items() if k in allowed}
        for k in ("principal", "remaining_principal", "accrued_interest"):
            if k in cols and cols[k] is not None and cols[k] < 0:
                raise LedgerError("Số tiền không được âm")
        if cols:
            with self._lock:
                self._db.execute(f"UPDATE ledger_debts SET {', '.join(k + '=?' for k in cols)} WHERE id=?", (*cols.values(), did))
                self._db.commit()
        return self._debt(did)

    def delete_debt(self, did: int) -> None:
        d = self._debt(did)
        self._require_manual(d.account_id)
        with self._lock:
            self._db.execute("DELETE FROM ledger_debts WHERE id=?", (did,))
            self._db.commit()

    # ---------- đồng bộ ----------

    def replace_synced(self, account: LedgerAccount, positions: list[dict[str, Any]], debts: list[dict[str, Any]]) -> None:
        """Thay toàn bộ nội dung một tiểu danh mục đồng bộ trong một giao dịch."""
        with self._lock:
            try:
                self._db.execute("DELETE FROM ledger_accounts WHERE id=?", (account.id,))
                self._db.execute(
                    """INSERT INTO ledger_accounts (id, name, source, source_broker, source_account, cash, ratio_kind,
                       ratio_pct, ratio_ref_value, initial_pct, maintenance_pct, liquidation_pct, synced_at, note, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (account.id, account.name, "sync", account.source_broker, account.source_account, account.cash,
                     account.ratio_kind, account.ratio_pct, account.ratio_ref_value, account.initial_pct,
                     account.maintenance_pct, account.liquidation_pct, _d(account.synced_at), account.note,
                     now_vn().isoformat()))
                for p in positions:
                    self._db.execute(
                        "INSERT INTO ledger_positions (account_id, symbol, quantity, avg_cost, last_price) VALUES (?,?,?,?,?)",
                        (account.id, p["symbol"], p["quantity"], p["avg_cost"], p.get("last_price")))
                for d in debts:
                    self._db.execute(
                        """INSERT INTO ledger_debts (account_id, symbol, principal, remaining_principal, accrued_interest,
                           annual_rate_pct, disbursement_date, due_date) VALUES (?,?,?,?,?,?,?,?)""",
                        (account.id, d.get("symbol"), d["principal"], d["remaining_principal"], d.get("accrued_interest", 0),
                         d.get("annual_rate_pct"), _d(d.get("disbursement_date")), _d(d.get("due_date"))))
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
