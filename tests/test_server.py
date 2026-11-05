"""服务端网络层测试（v2 协议）：建房、开局、权威判棋、超时、重连、认输。"""

from __future__ import annotations

import asyncio
import json

from aiohttp import ClientSession, WSMsgType, web

from server.clock import ClockConfig
from server.main import create_app


async def _recv(ws, kind: str, timeout: float = 4.0) -> dict:
    async def loop() -> dict:
        while True:
            message = await ws.receive()
            if message.type is WSMsgType.TEXT:
                data = json.loads(message.data)
                if data.get("type") == kind:
                    return data

    return await asyncio.wait_for(loop(), timeout)


async def _send(ws, kind: str, data: dict | None = None) -> None:
    await ws.send_str(json.dumps({"type": kind, "data": data or {}}))


async def _with_server(coro, config: ClockConfig | None = None):
    app = create_app(config)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
    try:
        return await coro(port)
    finally:
        await runner.cleanup()


async def _pair(session: ClientSession, port: int):
    url = f"http://127.0.0.1:{port}/ws"
    a = await session.ws_connect(url)
    b = await session.ws_connect(url)
    await _send(a, "create_room", {"name": "红方"})
    created = await _recv(a, "room_created")
    code = created["data"]["code"]
    await _send(b, "join_room", {"code": code, "name": "黑方"})
    joined = await _recv(b, "room_joined")
    return a, b, code, created["data"], joined["data"]


def test_full_flow_create_ready_move():
    async def flow(port: int) -> dict:
        async with ClientSession() as session:
            a, b, code, created, joined = await _pair(session, port)
            assert len(code) == 6 and code.isdigit()
            assert created["seat"] == 0 and joined["seat"] == 1
            assert joined["token"]

            await _send(a, "ready")
            await _send(b, "ready")
            start_a = await _recv(a, "game_start")
            start_b = await _recv(b, "game_start")
            assert start_a["data"]["fen"].startswith("rheakaehr")
            assert start_a["data"]["redSeat"] == 0
            assert start_a["data"]["clock"]["redMs"] > 29 * 60 * 1000
            assert start_b["data"]["redSeat"] == 0

            await _send(a, "move", {"move": {"from": [1, 7], "to": [4, 7]}})
            applied = await _recv(b, "move_applied")
            echo = await _recv(a, "move_applied")
            assert applied["data"]["seq"] == 1
            assert echo["data"]["seq"] == 1
            assert applied["data"]["record"] == ["1. 炮 b2-e2"]

            # 轮到黑方，红方再走应被拒绝
            await _send(a, "move", {"move": {"from": [7, 0], "to": [6, 2]}})
            err = await _recv(a, "error")
            assert "还没轮到你" in err["data"]["message"]

            await a.close()
            await b.close()
            return {"code": code}

    assert asyncio.run(_with_server(flow))["code"]


def test_illegal_move_rejected():
    async def flow(port: int) -> None:
        async with ClientSession() as session:
            a, b, *_ = await _pair(session, port)
            await _send(a, "ready")
            await _send(b, "ready")
            await _recv(a, "game_start")
            await _recv(b, "game_start")

            await _send(a, "move", {"move": {"from": [1, 7], "to": [1, 9]}})  # 炮压自己的马
            err = await _recv(a, "error")
            assert "非法着法" in err["data"]["message"]

            await a.close()
            await b.close()

    asyncio.run(_with_server(flow))


def test_join_unknown_room_and_full_room():
    async def flow(port: int) -> None:
        async with ClientSession() as session:
            a, b, code, *_ = await _pair(session, port)
            c = await session.ws_connect(f"http://127.0.0.1:{port}/ws")

            await _send(c, "join_room", {"code": code, "name": "第三人"})
            assert "满" in (await _recv(c, "error"))["data"]["message"]

            await _send(c, "join_room", {"code": "000000", "name": "路人"})
            assert "不存在" in (await _recv(c, "error"))["data"]["message"]

            for ws in (a, b, c):
                await ws.close()

    asyncio.run(_with_server(flow))


def test_clock_timeout_ends_game():
    async def flow(port: int) -> None:
        async with ClientSession() as session:
            a, b, *_ = await _pair(session, port)
            await _send(a, "ready")
            await _send(b, "ready")
            await _recv(a, "game_start")
            await _recv(b, "game_start")

            over = await _recv(a, "game_over", timeout=6.0)
            assert over["data"]["winner"] == 1
            assert "超时" in over["data"]["reason"]
            await a.close()
            await b.close()

    asyncio.run(_with_server(flow, ClockConfig(base_ms=600, byo_ms=300)))


def test_reconnect_restores_game():
    async def flow(port: int) -> None:
        async with ClientSession() as session:
            a, b, code, _, joined = await _pair(session, port)
            token = joined["token"]
            await _send(a, "ready")
            await _send(b, "ready")
            await _recv(a, "game_start")
            await _recv(b, "game_start")
            await _send(a, "move", {"move": {"from": [1, 7], "to": [4, 7]}})
            await _recv(b, "move_applied")

            b2 = await session.ws_connect(f"http://127.0.0.1:{port}/ws")
            await _send(b2, "reconnect", {"code": code, "token": token})
            resync = await _recv(b2, "resync")
            assert resync["data"]["phase"] == "playing"
            game = resync["data"]["game"]
            assert game["fen"].startswith("rheakaehr/9/1c5c1")
            assert game["record"] == ["1. 炮 b2-e2"]
            assert game["clock"]["paused"] is False

            await a.close()
            await b.close()
            await b2.close()

    asyncio.run(_with_server(flow))


def test_resign_broadcasts_game_over():
    async def flow(port: int) -> None:
        async with ClientSession() as session:
            a, b, *_ = await _pair(session, port)
            await _send(a, "ready")
            await _send(b, "ready")
            await _recv(a, "game_start")
            await _recv(b, "game_start")

            await _send(b, "resign")
            over_a = await _recv(a, "game_over")
            over_b = await _recv(b, "game_over")
            assert over_a["data"]["winner"] == 0
            assert over_a["data"]["text"] == over_b["data"]["text"]

            await a.close()
            await b.close()

    asyncio.run(_with_server(flow))


def test_health_endpoint():
    async def flow(port: int) -> dict:
        async with ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/") as response:
                return await response.json()

    payload = asyncio.run(_with_server(flow))
    assert payload["ok"] is True
    assert payload["protocol"] == 2
    assert payload["clock"]["baseMs"] == 30 * 60 * 1000
