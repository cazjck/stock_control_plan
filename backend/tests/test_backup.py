"""Sao lưu SQLite: bản sao đọc được, quyền 600, giữ đúng số bản."""
from __future__ import annotations

import sqlite3
import stat
from datetime import date, timedelta

from app.services.backup import backup_sqlite


def test_backup_is_consistent_private_and_rotated(tmp_path):
    src = tmp_path / "stockctl.sqlite"
    con = sqlite3.connect(src)
    con.execute("CREATE TABLE t (x INTEGER)")
    con.execute("INSERT INTO t VALUES (42)")
    con.commit()
    dest = tmp_path / "backups"
    for i in range(5):
        out = backup_sqlite(src, dest, date(2026, 10, 1) + timedelta(days=i), keep=3)
    con.close()
    files = sorted(p.name for p in dest.glob("*.sqlite"))
    assert files == ["stockctl-20261003.sqlite", "stockctl-20261004.sqlite", "stockctl-20261005.sqlite"]
    assert sqlite3.connect(out).execute("SELECT x FROM t").fetchone() == (42,)
    assert stat.S_IMODE(out.stat().st_mode) == 0o600 and stat.S_IMODE(dest.stat().st_mode) == 0o700
