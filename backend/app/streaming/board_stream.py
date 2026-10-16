"""Bảng giá thời gian thực.

TCBS: một kết nối WebSocket tới wss://openapi.tcbs.com.vn/ws/thesis/v1/stream/normal (chỉ đọc giá).
Giao thức là chuỗi văn bản phân tách bằng '|':
  gửi  d|a|||<base64 token>              xác thực, chờ d|0|{"success":true,...}
  gửi  d|s|tk|bp+bi+tm+mp+op+fe|A,B      đăng ký mã; d|s|si|rt|1 đăng ký chỉ số (1 = VN-INDEX)
  gửi  d|p|||                            nhịp tim mỗi 2 giây (tắt ping nhị phân của thư viện)
  nhận s|<kênh>|<JSON>                   1 mua, 2 bán, 3 khối ngoại, 4 trần/sàn/TC, 5 phiên, 6 khớp, 8 chỉ số
Demo: sinh nhịp giá giả để thử giao diện.

Trạng thái bảng giá được giữ trong bộ nhớ và phát tới mọi người đang xem qua hàng đợi asyncio.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import random
import time
from typing import Any, Awaitable, Callable

from ..models import BoardIndex, BoardQuote, BookLevel

log = logging.getLogger("stockctl.stream")

TCBS_WS = "wss://openapi.tcbs.com.vn/ws/thesis/v1/stream/normal"
INDEX_NAMES = {1: "VNINDEX", 2: "VN30"}


def _f(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def apply_message(quotes: dict[str, BoardQuote], index: dict[str, BoardIndex], raw: str) -> tuple[str, str] | None:
    """Áp một tin nhắn TCBS vào trạng thái. Trả về ("quote", mã) hoặc ("index", tên) nếu có thay đổi."""
    if not raw.startswith("s|"):
        return None
    parts = raw.split("|", 2)
    if len(parts) < 3:
        return None
    try:
        ch, d = int(parts[1]), json.loads(parts[2])
    except (ValueError, json.JSONDecodeError):
        return None
    if ch == 8:
        name = INDEX_NAMES.get(int(_f(d.get("indexNumber")) or 0))
        if not name:
            return None
        index[name] = BoardIndex(symbol=name, value=_f(d.get("index")), change=_f(d.get("change")),
                                 change_pct=_f(d.get("changePercent")))
        return ("index", name)
    sym = str(d.get("symbol", "")).upper()
    if not sym:
        return None
    q = quotes.get(sym) or BoardQuote(symbol=sym)
    u: dict[str, Any] = {}
    if ch in (1, 2):
        side = "bid" if ch == 1 else "offer"
        u[side] = [BookLevel(price=_f(d.get(f"{side}Price0{i}")) or 0, qty=_f(d.get(f"{side}Qtty0{i}")) or 0)
                   for i in (1, 2, 3) if _f(d.get(f"{side}Price0{i}"))]
    elif ch == 3:
        u.update(foreign_buy=_f(d.get("buyForeignQtty")), foreign_sell=_f(d.get("sellForeignQtty")), room=_f(d.get("room")))
    elif ch == 4:
        u.update(ceil=_f(d.get("ceilPrice")), floor=_f(d.get("floorPrice")), ref=_f(d.get("refPrice")))
    elif ch == 5:
        u.update(high=_f(d.get("high")), low=_f(d.get("low")), avg=_f(d.get("avg")), open=_f(d.get("open")))
    elif ch == 6:
        u.update(price=_f(d.get("matchPrice")) or q.price, match_qty=_f(d.get("matchQtty")), change=_f(d.get("change")),
                 change_pct=_f(d.get("changePercent")), total_vol=_f(d.get("totalVolume")))
    else:
        return None
    quotes[sym] = q.model_copy(update={k: v for k, v in u.items() if v is not None or k in ("bid", "offer")})
    return ("quote", sym)


class BoardHub:
    """Một luồng bảng giá cho một nguồn giá. Người xem đăng ký hàng đợi; luồng tự dừng khi không còn ai xem."""

    IDLE_STOP_SECONDS = 60

    def __init__(self, name: str):
        self.name = name
        self.quotes: dict[str, BoardQuote] = {}
        self.index: dict[str, BoardIndex] = {}
        self.symbols: set[str] = set()
        self.status = "idle"            # idle | connecting | live | auth | error
        self.message: str | None = None
        self.last_tick: float | None = None
        self._subs: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._idle_since: float | None = None
        self._resubscribe = asyncio.Event()

    # ---------- người xem ----------

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        self._idle_since = None
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)
        if not self._subs:
            self._idle_since = time.monotonic()

    def _emit(self, event: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:   # người xem quá chậm: bỏ bớt tin cũ
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                q.put_nowait(event)

    def _status(self, status: str, message: str | None = None) -> None:
        if (status, message) != (self.status, self.message):
            self.status, self.message = status, message
            self._emit({"type": "status", "status": status, "message": message})

    def watch(self, symbols: set[str], seed: dict[str, BoardQuote]) -> None:
        for s, q in seed.items():
            self.quotes.setdefault(s, q)
        if not symbols <= self.symbols:
            self.symbols |= symbols
            self._resubscribe.set()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None
        self._status("idle")

    def _idle_expired(self) -> bool:
        return not self._subs and self._idle_since is not None and time.monotonic() - self._idle_since > self.IDLE_STOP_SECONDS

    async def _run(self) -> None:  # pragma: no cover - ghi đè ở lớp con
        raise NotImplementedError


class TcbsBoardHub(BoardHub):
    def __init__(self, token_provider: Callable[[], str | None], url: str = TCBS_WS,
                 connect: Callable[..., Awaitable[Any]] | None = None):
        super().__init__("tcbs")
        self._token = token_provider
        self._url = url
        self._connect = connect

    async def _run(self) -> None:
        import websockets

        connect = self._connect or (lambda url: websockets.connect(url, ping_interval=None, open_timeout=15,
                                                                   max_size=2**22))
        attempt = 0
        while not self._idle_expired():
            token = self._token()
            if not token:
                self._status("auth", "Token TCBS hết hạn, nhập iOTP ở trang Thiết lập để xem giá trực tiếp")
                await asyncio.sleep(5)
                continue
            self._status("connecting")
            ws = None
            try:
                ws = await connect(self._url)
                if True:
                    await ws.send("d|a|||" + base64.b64encode(token.encode()).decode())
                    ok = await self._await_auth(ws)
                    if not ok:
                        self._status("auth", "TCBS từ chối token, nhập lại iOTP ở trang Thiết lập")
                        await asyncio.sleep(10)
                        continue
                    attempt = 0
                    subscribed: set[str] = set()
                    await ws.send("d|s|si|rt|1")
                    hb = asyncio.create_task(self._heartbeat(ws))
                    try:
                        self._status("live")
                        while not self._idle_expired():
                            if self.symbols - subscribed:
                                new = sorted(self.symbols - subscribed)
                                await ws.send("d|s|tk|bp+bi+tm+mp+op+fe|" + ",".join(new))
                                subscribed |= set(new)
                                self._resubscribe.clear()
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            except asyncio.TimeoutError:
                                continue
                            changed = apply_message(self.quotes, self.index, raw if isinstance(raw, str) else raw.decode())
                            if changed:
                                self.last_tick = time.time()
                                kind, key = changed
                                if kind == "quote":
                                    self._emit({"type": "quote", "row": self.quotes[key].model_dump()})
                                else:
                                    self._emit({"type": "index", "index": self.index[key].model_dump()})
                    finally:
                        hb.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - mạng rớt: nối lại có giãn cách
                attempt += 1
                delay = min(2 ** attempt, 30)
                log.warning("TCBS stream lỗi (%s), nối lại sau %ss", e, delay)
                self._status("error", f"Mất kết nối giá trực tiếp, thử lại sau {delay} giây")
                await asyncio.sleep(delay)
            finally:
                if ws is not None:
                    with contextlib.suppress(Exception):
                        await ws.close()
        self._status("idle")

    @staticmethod
    async def _await_auth(ws) -> bool:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            raw = raw if isinstance(raw, str) else raw.decode()
            if raw.startswith("d|0|"):
                try:
                    return bool(json.loads(raw[4:]).get("success"))
                except json.JSONDecodeError:
                    return False
        return False

    @staticmethod
    async def _heartbeat(ws) -> None:
        while True:
            await asyncio.sleep(2)
            await ws.send("d|p|||")


class DemoBoardHub(BoardHub):
    """Nhịp giá giả để thử giao diện trực tiếp với dữ liệu mẫu."""

    def __init__(self, interval: float = 1.5):
        super().__init__("demo")
        self._interval = interval

    async def _run(self) -> None:
        self._status("live")
        rnd = random.Random(7)
        while not self._idle_expired():
            await asyncio.sleep(self._interval)
            if not self.quotes:
                continue
            sym = rnd.choice(sorted(self.quotes))
            q = self.quotes[sym]
            if not q.price or not q.ref:
                continue
            tick = 10.0 if q.price < 10_000 else 50.0 if q.price < 50_000 else 100.0
            price = max(q.floor or 0, min(q.ceil or 1e12, q.price + rnd.choice([-1, 0, 1]) * tick))
            qty = rnd.choice([100, 200, 500, 1000, 2000])
            self.quotes[sym] = q.model_copy(update=dict(
                price=price, match_qty=qty, change=price - q.ref, change_pct=(price / q.ref - 1) * 100,
                total_vol=(q.total_vol or 0) + qty, high=max(q.high or price, price), low=min(q.low or price, price),
                bid=[BookLevel(price=price - tick * i, qty=lvl.qty) for i, lvl in enumerate(q.bid, 1)],
                offer=[BookLevel(price=price + tick * i, qty=lvl.qty) for i, lvl in enumerate(q.offer, 1)]))
            self.last_tick = time.time()
            self._emit({"type": "quote", "row": self.quotes[sym].model_dump()})
        self._status("idle")


class StreamRegistry:
    """Một luồng cho mỗi nguồn giá (TCBS, demo). Sổ tổng dùng chung luồng của nguồn giá của nó."""

    def __init__(self, adapters: dict):
        self._adapters = adapters
        self._hubs: dict[str, BoardHub] = {}

    def source_for(self, broker: str):
        ad = self._adapters.get(broker)
        if ad is None:
            return None
        if broker == "ledger":
            return ad._price_source()  # type: ignore[attr-defined]
        return ad

    def hub_for(self, broker: str) -> BoardHub | None:
        src = self.source_for(broker)
        if src is None:
            return None
        if src.name in self._hubs:
            return self._hubs[src.name]
        if src.name == "tcbs":
            hub: BoardHub = TcbsBoardHub(src.stream_token)
        elif src.name == "demo":
            hub = DemoBoardHub()
        else:
            return None   # DNSE: chưa hỗ trợ luồng trực tiếp, giao diện tự làm mới định kỳ
        self._hubs[src.name] = hub
        return hub

    async def close(self) -> None:
        for h in self._hubs.values():
            await h.stop()
