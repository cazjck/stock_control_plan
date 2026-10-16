"""Lưu trữ SQLite: kế hoạch từng mã, cảnh báo, snapshot hằng ngày, ghi đè luật và nhật ký đổi luật."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..models import AlertCandidate, AlertRecord, PositionPlan
from ..util import now_vn

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
  broker TEXT NOT NULL, account_id TEXT NOT NULL, symbol TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'swing', entry_date TEXT, has_thesis INTEGER,
  ladder_done INTEGER NOT NULL DEFAULT 0, note TEXT, updated_at TEXT NOT NULL,
  PRIMARY KEY (broker, account_id, symbol)
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, broker TEXT NOT NULL, account_id TEXT NOT NULL,
  key TEXT NOT NULL, rule TEXT NOT NULL, severity TEXT NOT NULL, title TEXT NOT NULL,
  message TEXT NOT NULL, symbol TEXT, data TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'open', first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  resolution_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_lookup ON alerts (broker, account_id, key, status);
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, broker TEXT NOT NULL, account_id TEXT NOT NULL,
  nav REAL, positions_value REAL, cash REAL, debt REAL, interest_per_day REAL,
  min_rtt_gap REAL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (day, broker, account_id)
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rule_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, diff TEXT NOT NULL, had_open_positions INTEGER NOT NULL
);
"""


def _row_to_alert(r: sqlite3.Row) -> AlertRecord:
    return AlertRecord(
        id=r["id"], key=r["key"], rule=r["rule"], severity=r["severity"], title=r["title"], message=r["message"],
        symbol=r["symbol"], data=json.loads(r["data"]), status=r["status"], broker=r["broker"],
        account_id=r["account_id"], first_seen=datetime.fromisoformat(r["first_seen"]),
        last_seen=datetime.fromisoformat(r["last_seen"]), resolution_note=r["resolution_note"])


class Store:
    def __init__(self, path: Path):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    # ---------- plans ----------

    def get_plans(self, broker: str, account_id: str) -> dict[str, PositionPlan]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM plans WHERE broker=? AND account_id=?", (broker, account_id)).fetchall()
        return {r["symbol"]: PositionPlan(
            broker=broker, account_id=account_id, symbol=r["symbol"], mode=r["mode"],
            entry_date=date.fromisoformat(r["entry_date"]) if r["entry_date"] else None,
            has_thesis=None if r["has_thesis"] is None else bool(r["has_thesis"]),
            ladder_done=r["ladder_done"], note=r["note"]) for r in rows}

    def upsert_plan(self, p: PositionPlan) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO plans (broker, account_id, symbol, mode, entry_date, has_thesis, ladder_done, note, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (broker, account_id, symbol) DO UPDATE SET
                     mode=excluded.mode, entry_date=excluded.entry_date, has_thesis=excluded.has_thesis,
                     ladder_done=excluded.ladder_done, note=excluded.note, updated_at=excluded.updated_at""",
                (p.broker, p.account_id, p.symbol, p.mode, p.entry_date.isoformat() if p.entry_date else None,
                 None if p.has_thesis is None else int(p.has_thesis), p.ladder_done, p.note, now_vn().isoformat()))
            self._db.commit()

    # ---------- alerts ----------

    def sync_alerts(self, broker: str, account_id: str, candidates: list[AlertCandidate]) -> None:
        """Mở cảnh báo mới, cập nhật cảnh báo đang mở, đóng (cleared) cảnh báo mà điều kiện không còn."""
        now = now_vn().isoformat()
        keys = {c.key for c in candidates}
        with self._lock:
            open_rows = self._db.execute(
                "SELECT id, key FROM alerts WHERE broker=? AND account_id=? AND status IN ('open','acked')",
                (broker, account_id)).fetchall()
            existing = {r["key"]: r["id"] for r in open_rows}
            for c in candidates:
                if c.key in existing:
                    self._db.execute(
                        "UPDATE alerts SET message=?, severity=?, title=?, data=?, last_seen=? WHERE id=?",
                        (c.message, c.severity.value, c.title, json.dumps(c.data, default=str), now, existing[c.key]))
                else:
                    self._db.execute(
                        """INSERT INTO alerts (broker, account_id, key, rule, severity, title, message, symbol, data, status, first_seen, last_seen)
                           VALUES (?,?,?,?,?,?,?,?,?,'open',?,?)""",
                        (broker, account_id, c.key, c.rule, c.severity.value, c.title, c.message, c.symbol,
                         json.dumps(c.data, default=str), now, now))
            for key, aid in existing.items():
                if key not in keys:
                    self._db.execute("UPDATE alerts SET status='cleared', last_seen=? WHERE id=?", (now, aid))
            self._db.commit()

    def list_alerts(self, broker: str | None = None, account_id: str | None = None,
                    status: str | None = None, limit: int = 200) -> list[AlertRecord]:
        q, args = "SELECT * FROM alerts WHERE 1=1", []
        if broker:
            q += " AND broker=?"; args.append(broker)
        if account_id:
            q += " AND account_id=?"; args.append(account_id)
        if status == "active":
            q += " AND status IN ('open','acked')"
        elif status:
            q += " AND status=?"; args.append(status)
        q += """ ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'acked' THEN 1 ELSE 2 END,
                 CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, last_seen DESC LIMIT ?"""
        args.append(limit)
        with self._lock:
            return [_row_to_alert(r) for r in self._db.execute(q, args).fetchall()]

    def set_alert_status(self, alert_id: int, status: str, note: str | None = None) -> AlertRecord | None:
        with self._lock:
            self._db.execute("UPDATE alerts SET status=?, resolution_note=COALESCE(?, resolution_note), last_seen=? WHERE id=?",
                             (status, note, now_vn().isoformat(), alert_id))
            self._db.commit()
            r = self._db.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        return _row_to_alert(r) if r else None

    # ---------- snapshots ----------

    def save_snapshot(self, day: date, broker: str, account_id: str, *, nav: float, positions_value: float,
                      cash: float, debt: float, interest_per_day: float, min_rtt_gap: float | None,
                      payload: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO snapshots (day, broker, account_id, nav, positions_value, cash, debt, interest_per_day, min_rtt_gap, payload, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (day, broker, account_id) DO UPDATE SET nav=excluded.nav, positions_value=excluded.positions_value,
                     cash=excluded.cash, debt=excluded.debt, interest_per_day=excluded.interest_per_day,
                     min_rtt_gap=excluded.min_rtt_gap, payload=excluded.payload, created_at=excluded.created_at""",
                (day.isoformat(), broker, account_id, nav, positions_value, cash, debt, interest_per_day, min_rtt_gap,
                 json.dumps(payload, default=str), now_vn().isoformat()))
            self._db.commit()

    def list_snapshots(self, broker: str, account_id: str, days: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """SELECT day, nav, positions_value, cash, debt, interest_per_day, min_rtt_gap FROM snapshots
                   WHERE broker=? AND account_id=? ORDER BY day DESC LIMIT ?""", (broker, account_id, days)).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ---------- rules ----------

    def get_rule_overrides(self) -> dict[str, Any]:
        with self._lock:
            r = self._db.execute("SELECT value FROM kv WHERE key='rule_overrides'").fetchone()
        return json.loads(r["value"]) if r else {}

    def set_rule_overrides(self, overrides: dict[str, Any], diff: dict[str, Any], had_open_positions: bool) -> None:
        with self._lock:
            self._db.execute("INSERT INTO kv (key, value) VALUES ('rule_overrides', ?) ON CONFLICT (key) DO UPDATE SET value=excluded.value",
                             (json.dumps(overrides),))
            self._db.execute("INSERT INTO rule_changes (at, diff, had_open_positions) VALUES (?,?,?)",
                             (now_vn().isoformat(), json.dumps(diff, default=str), int(had_open_positions)))
            self._db.commit()

    def list_rule_changes(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT at, diff, had_open_positions FROM rule_changes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"at": r["at"], "diff": json.loads(r["diff"]), "had_open_positions": bool(r["had_open_positions"])} for r in rows]

    def close(self) -> None:
        with self._lock:
            self._db.close()
