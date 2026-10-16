"""Bảng giá thời gian thực: đọc giao thức TCBS, luồng WebSocket, và SSE xuống trình duyệt."""
from __future__ import annotations

import asyncio
import base64
import json

import pytest
import websockets
from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import BoardQuote
from app.streaming.board_stream import DemoBoardHub, TcbsBoardHub, apply_message


def test_parser_merges_each_channel():
    quotes, index = {"PDR": BoardQuote(symbol="PDR", price=11200)}, {}
    assert apply_message(quotes, index, 's|4|{"symbol":"PDR","ceilPrice":12050,"floorPrice":10550,"refPrice":11300}') == ("quote", "PDR")
    apply_message(quotes, index, 's|6|{"symbol":"PDR","matchPrice":"11350","matchQtty":"500","change":50.0,"changePercent":0.44,"totalVolume":"1650000","totalValue":"1"}')
    apply_message(quotes, index, 's|1|{"symbol":"PDR","bidPrice01":"11300","bidPrice02":"11250","bidPrice03":"","bidQtty01":"1000","bidQtty02":"2000","bidQtty03":""}')
    apply_message(quotes, index, 's|3|{"symbol":"PDR","buyForeignQtty":"100","sellForeignQtty":"89300","room":"5"}')
    q = quotes["PDR"]
    assert (q.ceil, q.floor, q.ref, q.price, q.match_qty, q.total_vol) == (12050, 10550, 11300, 11350, 500, 1_650_000)
    assert [b.price for b in q.bid] == [11300, 11250] and q.foreign_sell == 89300
    assert apply_message(quotes, index, 's|8|{"indexNumber":1,"index":1701.3,"change":-4.2,"changePercent":-0.25}') == ("index", "VNINDEX")
    assert index["VNINDEX"].value == pytest.approx(1701.3)


@pytest.mark.parametrize("raw", ["d|p|||", "d|34|1", "s|6|không phải json", "s|99|{}", 's|6|{"matchPrice":"1"}'])
def test_parser_ignores_noise(raw):
    assert apply_message({}, {}, raw) is None


async def test_tcbs_hub_against_protocol_compatible_server():
    """Máy chủ giả lập giao thức TCBS: kiểm tra xác thực, đăng ký, nhịp tim và nhận giá."""
    seen: list[str] = []

    async def handler(ws):
        auth = await ws.recv()
        seen.append(auth)
        await ws.send("d|33|15")
        await ws.send('d|0|{"success":true,"error":null}')
        async for msg in ws:
            seen.append(msg)
            if msg.startswith("d|s|tk|"):
                await ws.send("d|34|1")
                await ws.send('s|6|{"symbol":"PDR","matchPrice":"11400","matchQtty":"300","change":100.0,"changePercent":0.88,"totalVolume":"10","totalValue":"1"}')

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        hub = TcbsBoardHub(lambda: "my-jwt", url=f"ws://127.0.0.1:{port}")
        q = hub.subscribe()
        hub.watch({"PDR"}, {"PDR": BoardQuote(symbol="PDR", price=11200, ref=11300)})
        events = []
        while not any(e["type"] == "quote" for e in events):
            events.append(await asyncio.wait_for(q.get(), timeout=5))
        await asyncio.sleep(2.3)                                  # đủ để gửi một nhịp tim
        await hub.stop()
    assert seen[0] == "d|a|||" + base64.b64encode(b"my-jwt").decode()
    assert "d|s|si|rt|1" in seen and "d|s|tk|bp+bi+tm+mp+op+fe|PDR" in seen and "d|p|||" in seen
    row = next(e for e in events if e["type"] == "quote")["row"]
    assert row["price"] == 11400 and row["ref"] == 11300               # giữ trường từ ảnh chụp ban đầu
    assert any(e.get("status") == "live" for e in events)


async def test_tcbs_hub_reports_auth_needed_without_token():
    hub = TcbsBoardHub(lambda: None, url="ws://127.0.0.1:9")
    q = hub.subscribe()
    hub.watch({"PDR"}, {})
    ev = await asyncio.wait_for(q.get(), timeout=3)
    await hub.stop()
    assert ev["status"] == "auth"


async def test_tcbs_hub_rejected_token():
    async def handler(ws):
        await ws.recv()
        await ws.send('d|0|{"success":false,"error":{"code":"211110","message":"Invalid JWT"}}')
        await asyncio.sleep(1)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        hub = TcbsBoardHub(lambda: "bad", url=f"ws://127.0.0.1:{port}")
        q = hub.subscribe()
        hub.watch({"PDR"}, {})
        statuses = []
        while "auth" not in statuses:
            statuses.append((await asyncio.wait_for(q.get(), timeout=5)).get("status"))
        await hub.stop()


async def test_demo_hub_ticks():
    hub = DemoBoardHub(interval=0.05)
    q = hub.subscribe()
    hub.watch({"FPT"}, {"FPT": BoardQuote(symbol="FPT", price=126500, ref=126400, ceil=135100, floor=117600)})
    ev = None
    while not ev or ev["type"] != "quote":
        ev = await asyncio.wait_for(q.get(), timeout=3)
    await hub.stop()
    assert 117600 <= ev["row"]["price"] <= 135100


import contextlib
import socket
import threading
import time

import httpx
import uvicorn


@contextlib.contextmanager
def live_server(tmp_path, monkeypatch, token=None):
    """Chạy app thật bằng uvicorn trong luồng riêng: kiểm tra được việc ngắt kết nối của SSE."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path)); monkeypatch.setenv("BROKERS", "demo")
    if token:
        monkeypatch.setenv("APP_ACCESS_TOKEN", token)
    else:
        monkeypatch.delenv("APP_ACCESS_TOKEN", raising=False)
    get_settings.cache_clear()
    from app.main import create_app
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True); th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        th.join(timeout=10)
        get_settings.cache_clear()
        assert not th.is_alive(), "máy chủ không tắt được: luồng SSE không kết thúc khi client ngắt"


def read_events(url, params=None, until="quote", limit=50):
    events, ev = [], None
    with httpx.Client(timeout=10) as c, c.stream("GET", url, params=params) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: ") and ev:
                events.append((ev, json.loads(line[6:])))
                if ev == until or len(events) >= limit:
                    break
    return events


def test_sse_endpoint_streams_snapshot_then_quotes(tmp_path, monkeypatch):
    with live_server(tmp_path, monkeypatch) as base:
        events = read_events(f"{base}/api/board/stream")
        assert events[0][0] == "snapshot" and events[0][1]["live"] is True and len(events[0][1]["rows"]) == 5
        assert events[-1][0] == "quote" and events[-1][1]["row"]["symbol"] in {"FPT", "HPG", "MWG", "SSI", "VND"}
        # mở lại lần hai: luồng dùng chung vẫn chạy, người xem mới nhận ngay ảnh chụp
        again = read_events(f"{base}/api/board/stream", until="snapshot")
        assert again[0][0] == "snapshot"


def test_sse_accepts_token_in_query(tmp_path, monkeypatch):
    with live_server(tmp_path, monkeypatch, token="s3cret") as base:
        assert httpx.get(f"{base}/api/board/stream", timeout=5).status_code == 401
        events = read_events(f"{base}/api/board/stream", params={"app_token": "s3cret"}, until="snapshot")
        assert events[0][0] == "snapshot"
