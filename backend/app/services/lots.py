"""Theo dõi từng lần mua: tự phát hiện mua thêm/bán ra từ thay đổi danh mục, khớp lô với khối lượng đang giữ,
và đánh giá luật lô mua thêm khi đang lỗ."""
from __future__ import annotations

from datetime import date

import pandas as pd

from ..models import Lot, LotEval, Position, UnknownLot
from ..risk.lots import evaluate_lot
from ..risk.rules import Rules
from ..storage.ledger import LedgerRepo
from ..storage.lots import LotRepo

MAX_IMPLIED_DEVIATION = 0.30  # giá suy ra lệch quá 30% so với giá hiện tại thì coi là ước tính


class LotService:
    def __init__(self, repo: LotRepo, ledger: LedgerRepo | None = None):
        self.repo = repo
        self.ledger = ledger

    # ---------- tự phát hiện ----------

    def observe(self, broker: str, account_id: str, positions: list[Position], today: date) -> list[str]:
        """So với lần đọc trước: khối lượng tăng thì ghi một lô mới (giá suy ra từ chênh lệch giá vốn),
        khối lượng giảm thì trừ vào lô mới nhất trước. Lần đầu chỉ ghi mốc, không tạo lô."""
        notes: list[str] = []
        seen = set()
        for p in positions:
            seen.add(p.symbol)
            prev = self.repo.last_obs(broker, account_id, p.symbol)
            if prev:
                q1, c1 = prev
                q2, c2 = p.quantity, p.avg_cost
                if q2 > q1:
                    dq = q2 - q1
                    implied = (q2 * c2 - q1 * c1) / dq
                    estimated = False
                    ref = p.price or c2
                    if implied <= 0 or (ref and abs(implied / ref - 1) > MAX_IMPLIED_DEVIATION):
                        implied, estimated = ref, True
                    self.repo.add(broker=broker, account_id=account_id, symbol=p.symbol, buy_date=today, quantity=dq,
                                  price=implied, source="auto", add_on_loss=implied < c1, estimated=estimated)
                    notes.append(f"{p.symbol}: phát hiện mua thêm {dq:,} cp giá khoảng {implied:,.0f}".replace(",", "."))
                elif q2 < q1:
                    self.repo.reduce_newest_first(broker, account_id, p.symbol, q1 - q2)
            self.repo.save_obs(broker, account_id, p.symbol, p.quantity, p.avg_cost)
        for sym in self.repo.symbols_observed(broker, account_id) - seen:   # đã bán hết
            self.repo.reduce_newest_first(broker, account_id, sym, 10**12)
            self.repo.drop_obs(broker, account_id, sym)
        return notes

    # ---------- nhóm lô của một vị thế ----------

    def _groups(self, broker: str, account_id: str, pos: Position, short: str) -> list[tuple[str, str, int, str]]:
        """(broker, tiểu khoản, khối lượng đang giữ, nhãn nguồn) cho từng nơi giữ mã này."""
        if broker != "ledger":
            return [(broker, account_id, pos.quantity, short)]
        out = []
        accs = {a.id: a for a in (self.ledger.accounts() if self.ledger else [])}
        for s in pos.sources:
            a = accs.get(s.account or "")
            if a is None:
                continue
            if a.source == "sync" and a.source_broker and a.source_account:
                out.append((a.source_broker, a.source_account, s.quantity, s.source))
            else:
                out.append(("ledger", a.id, s.quantity, s.source))
        return out

    def evaluate(self, broker: str, account_id: str, pos: Position, df: pd.DataFrame | None, rules: Rules,
                 today: date, short: str) -> tuple[list[LotEval], UnknownLot | None]:
        evals: list[LotEval] = []
        tracked = 0
        tracked_cost = 0.0
        for b, acc, qty, label in self._groups(broker, account_id, pos, short):
            open_lots = self.repo.lots(b, acc, pos.symbol, open_only=True)
            excess = sum(l.remaining for l in open_lots) - qty
            if excess > 0:   # đã bán bớt mà chưa quan sát được: trừ lô mới nhất trước
                self.repo.reduce_newest_first(b, acc, pos.symbol, excess)
            for lot in self.repo.lots(b, acc, pos.symbol):
                ev = evaluate_lot(lot, price=pos.price, df=df, rules=rules, today=today, label=label)
                self._remember_trigger(lot, ev, pos.price, today)
                if lot.trigger_date is None and ev.rule_status in ("stop", "time"):
                    ev = evaluate_lot(self.repo.get(lot.id), price=pos.price, df=df, rules=rules, today=today, label=label)
                evals.append(ev)
                tracked += lot.remaining
                tracked_cost += lot.remaining * lot.price
        unknown_q = pos.quantity - tracked
        unknown = None
        if unknown_q > 0 and tracked > 0:
            uc = (pos.quantity * pos.avg_cost - tracked_cost) / unknown_q
            unknown = UnknownLot(quantity=unknown_q, avg_cost=uc if uc > 0 else None)
        evals.sort(key=lambda e: (e.buy_date, e.id), reverse=True)
        return evals, unknown

    def _remember_trigger(self, lot: Lot, ev: LotEval, price: float | None, today: date) -> None:
        """Ghi phiên đầu tiên luật lô yêu cầu bán, để đếm số phiên chần chừ và tiền mất thêm. Điều kiện hết thì xoá."""
        firing = ev.rule_status in ("stop", "time")
        if firing and lot.trigger_date is None and price is not None:
            self.repo.update(lot.id, trigger_date=today, trigger_price=price)
        elif not firing and lot.trigger_date is not None and ev.rule_status != "closed":
            self.repo.update(lot.id, trigger_date=None, trigger_price=None)
