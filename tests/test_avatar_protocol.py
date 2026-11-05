"""头像协议测试：上传 → 房间携带 → HTTP 取回。"""

from __future__ import annotations

import asyncio
import base64
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from aiohttp import ClientSession, WSMsgType, web
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage

from server.main import create_app


def png_bytes(size: int = 16, color: str = "#2d7a5f") -> bytes:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(QColor(color))
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


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


async def _with_server(coro, tmp_path):
    app = create_app(data_dir=str(tmp_path / "server_data"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
    try:
        return await coro(port)
    finally:
        await runner.cleanup()


def test_avatar_upload_and_fetch(tmp_path):
    async def flow(port: int) -> dict:
        url = f"http://127.0.0.1:{port}"
        data = png_bytes()
        async with ClientSession() as session:
            async with session.ws_connect(f"{url}/ws") as ws:
                await _send(ws, "avatar_upload", {"data": base64.b64encode(data).decode()})
                saved = await _recv(ws, "avatar_saved")
                avatar_id = saved["data"]["id"]
                assert saved["data"]["size"] == len(data)

                async with session.get(f"{url}/avatar/{avatar_id}") as response:
                    assert response.status == 200
                    assert response.headers["Content-Type"].startswith("image/png")
                    assert response.headers["X-Content-Type-Options"] == "nosniff"
                    assert await response.read() == data
            return {"id": avatar_id}

    result = asyncio.run(_with_server(flow, tmp_path))
    assert len(result["id"]) == 16


def test_room_carries_avatar_id(tmp_path):
    async def flow(port: int) -> dict:
        url = f"http://127.0.0.1:{port}/ws"
        data = png_bytes()
        async with ClientSession() as session:
            async with session.ws_connect(url) as host, session.ws_connect(url) as guest:
                await _send(host, "avatar_upload", {"data": base64.b64encode(data).decode()})
                avatar_id = (await _recv(host, "avatar_saved"))["data"]["id"]

                await _send(host, "create_room", {"name": "红方", "avatar": avatar_id})
                created = await _recv(host, "room_created")
                seats = created["data"]["room"]["seats"]
                assert seats[0]["avatar"] == avatar_id

                code = created["data"]["code"]
                await _send(guest, "join_room", {"code": code, "name": "黑方", "avatar": None})
                joined = await _recv(guest, "room_joined")
                assert joined["data"]["room"]["seats"][1]["avatar"] is None
                assert joined["data"]["room"]["seats"][0]["avatar"] == avatar_id
            return {"id": avatar_id}

    asyncio.run(_with_server(flow, tmp_path))


def test_rejects_bad_upload(tmp_path):
    async def flow(port: int) -> None:
        url = f"http://127.0.0.1:{port}/ws"
        async with ClientSession() as session:
            async with session.ws_connect(url) as ws:
                await _send(ws, "avatar_upload", {"data": "这不是 base64!!"})
                error = await _recv(ws, "error")
                assert "base64" in error["data"]["message"]

                await _send(ws, "avatar_upload", {"data": base64.b64encode(b"<html>x</html>").decode()})
                error = await _recv(ws, "error")
                assert "只支持" in error["data"]["message"]

    asyncio.run(_with_server(flow, tmp_path))


def test_unknown_avatar_returns_404(tmp_path):
    async def flow(port: int) -> int:
        async with ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/avatar/0123456789abcdef") as response:
                return response.status

    assert asyncio.run(_with_server(flow, tmp_path)) == 404


def test_upload_payload_larger_than_old_frame_limit(tmp_path):
    """回归：之前 WebSocket 单帧上限 64KB，base64 后超过就断连。

    这条用例的帧有 130KB 左右，正好落在旧上限之外——线上就是这么挂的。
    """

    async def flow(port: int) -> int:
        payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * (100 * 1024)
        async with ClientSession() as session:
            async with session.ws_connect(f"http://127.0.0.1:{port}/ws") as ws:
                await _send(ws, "avatar_upload", {"data": base64.b64encode(payload).decode()})
                saved = await _recv(ws, "avatar_saved")
                assert saved["data"]["size"] == len(payload)
                return saved["data"]["size"]

    assert asyncio.run(_with_server(flow, tmp_path)) == 100 * 1024 + 8


def test_upload_accepts_up_to_512kb(tmp_path):
    async def flow(port: int) -> int:
        payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * (500 * 1024)
        async with ClientSession() as session:
            async with session.ws_connect(f"http://127.0.0.1:{port}/ws") as ws:
                await _send(ws, "avatar_upload", {"data": base64.b64encode(payload).decode()})
                saved = await _recv(ws, "avatar_saved")
                return saved["data"]["size"]

    assert asyncio.run(_with_server(flow, tmp_path)) == 500 * 1024 + 8


def test_upload_rejects_over_512kb(tmp_path):
    async def flow(port: int) -> None:
        payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * (600 * 1024)
        async with ClientSession() as session:
            async with session.ws_connect(f"http://127.0.0.1:{port}/ws") as ws:
                await _send(ws, "avatar_upload", {"data": base64.b64encode(payload).decode()})
                error = await _recv(ws, "error")
                assert "太大" in error["data"]["message"]

    asyncio.run(_with_server(flow, tmp_path))
