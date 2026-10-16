"""Đọc/ghi bộ luật: mặc định từ YAML, ghi đè của người dùng trong SQLite, mọi thay đổi có nhật ký."""
from __future__ import annotations

from typing import Any

from ..risk.rules import Rules, build_rules, deep_merge, load_defaults
from ..storage.db import Store


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


class RulesService:
    def __init__(self, store: Store):
        self._store = store
        self._cached: Rules | None = None

    def get(self) -> Rules:
        if self._cached is None:
            self._cached = build_rules(self._store.get_rule_overrides())
        return self._cached

    def effective_dict(self) -> dict[str, Any]:
        return self.get().model_dump()

    def defaults_dict(self) -> dict[str, Any]:
        return build_rules().model_dump()

    def update(self, patch: dict[str, Any], *, had_open_positions: bool) -> Rules:
        """Gộp `patch` vào ghi đè hiện có, kiểm tra hợp lệ rồi lưu. Ném ValidationError nếu sai."""
        old = self.get()
        merged = deep_merge(self._store.get_rule_overrides(), patch)
        new = build_rules(merged)  # kiểm tra hợp lệ trước khi lưu
        old_flat, new_flat = _flatten(old.model_dump()), _flatten(new.model_dump())
        diff = {k: {"from": old_flat.get(k), "to": v} for k, v in new_flat.items() if old_flat.get(k) != v}
        if diff:
            self._store.set_rule_overrides(merged, diff, had_open_positions)
        self._cached = new
        return new

    def reset(self, *, had_open_positions: bool) -> Rules:
        old_flat = _flatten(self.get().model_dump())
        new = build_rules()
        new_flat = _flatten(new.model_dump())
        diff = {k: {"from": old_flat.get(k), "to": v} for k, v in new_flat.items() if old_flat.get(k) != v}
        self._store.set_rule_overrides({}, diff or {"reset": True}, had_open_positions)
        self._cached = new
        return new

    def has_overrides(self) -> bool:
        return bool(self._store.get_rule_overrides())

    def defaults_raw(self) -> dict[str, Any]:
        return load_defaults()
