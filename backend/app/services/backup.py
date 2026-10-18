"""Sao lưu SQLite của ứng dụng mỗi ngày (bản sao nhất quán bằng backup API của sqlite3), giữ N bản gần nhất.
Chỉ ghi vào thư mục dữ liệu của ứng dụng; dev-01 kéo các bản này về bằng scripts/pull-backups.sh."""
from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path


def backup_sqlite(src: Path, dest_dir: Path, today: date, keep: int = 14) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(dest_dir, 0o700)
    out = dest_dir / f"stockctl-{today:%Y%m%d}.sqlite"
    tmp = out.with_suffix(".tmp")
    s = sqlite3.connect(src)
    d = sqlite3.connect(tmp)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    os.chmod(tmp, 0o600)
    tmp.replace(out)
    files = sorted(dest_dir.glob("stockctl-*.sqlite"))
    for old in files[:-keep] if keep > 0 else []:
        old.unlink()
    return out
