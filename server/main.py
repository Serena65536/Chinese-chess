"""联机服务端（aiohttp）：把 WebSocket 消息翻译成 Session 上的动作。

职责边界：
- 本文件只做传输（连接、路由、广播、心跳、时钟推送）
- 棋规与胜负判定全在 ``session.Session`` 里，它复用客户端那同一份 ``xiangqi_core``，
  所以客户端改代码也改不了棋局结果
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import logging.handlers
import time
from pathlib import Path
from typing import Optional

from aiohttp import WSMsgType, web

from xiangqi_core import Move

from .avatars import AvatarError, AvatarStore
from .clock import ClockConfig
from .session import ProtocolError, RoomRegistry, Session

PROTOCOL_VERSION = 2
CLOCK_PUSH_INTERVAL_S = 1.0
TICK_INTERVAL_S = 0.2


def _now() -> float:
    return time.monotonic()


def setup_logging(data_dir: str) -> None:
    """服务端日志：<data-dir>/logs/server.log，512KB 滚动。"""
    folder = Path(data_dir) / "logs"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            folder / "server.log", maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        # aiohttp 的访问日志太吵，只留警告；房间/对局日志自己打
        logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    except OSError:
        pass


class Peer:
    """一条 WebSocket 连接与它对应的座位。"""

    def __init__(self, ws: web.WebSocketResponse) -> None:
        self.ws = ws
        self.session: Optional[Session] = None
        self.seat_index: Optional[int] = None


class ChessServer:
    def __init__(self, config: Optional[ClockConfig] = None, data_dir: Optional[str] = None) -> None:
        self.config = config or ClockConfig()
        self.registry = RoomRegistry()
        root = Path(data_dir) if data_dir else Path.cwd() / "server_data"
        self.avatars = AvatarStore(root / "avatars")

    async def avatar_route(self, request: web.Request) -> web.Response:
        found = self.avatars.read(request.match_info.get("avatar_id", ""))
        if found is None:
            raise web.HTTPNotFound()
        data, mime = found
        return web.Response(
            body=data,
            content_type=mime,
            headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"},
        )

    async def health(self, request: web.Request) -> web.Response:  # noqa: ARG002
        return web.json_response(
            {
                "app": "一起来下棋",
                "protocol": PROTOCOL_VERSION,
                "rooms": len(self.registry.rooms),
                "clock": self.config.as_payload(),
                "ok": True,
            }
        )

    async def _send(self, peer: Peer, kind: str, data: Optional[dict] = None) -> None:
        if peer.ws.closed:
            return
        try:
            await peer.ws.send_json({"type": kind, "data": data or {}})
        except (ConnectionResetError, RuntimeError):
            pass

    async def _broadcast(self, session: Session, kind: str, data: dict, *, skip: Optional[Peer] = None) -> None:
        for seat in session.seats:
            peer = getattr(seat, "peer", None)
            if peer is None or peer is skip:
                continue
            await self._send(peer, kind, data)

    # ---------- WebSocket ----------

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=15.0, max_msg_size=4 * 1024 * 1024)
        await ws.prepare(request)
        peer = Peer(ws)

        try:
            async for message in ws:
                if message.type is not WSMsgType.TEXT:
                    if message.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                        break
                    continue
                try:
                    payload = json.loads(message.data)
                except json.JSONDecodeError:
                    await self._send(peer, "error", {"message": "消息不是合法 JSON"})
                    continue
                kind = payload.get("type")
                data = payload.get("data") or {}
                try:
                    await self._dispatch(peer, str(kind), data)
                except ProtocolError as exc:
                    await self._send(peer, "error", {"message": str(exc), "for": kind})
        finally:
            await self._cleanup(peer)
        return ws

    async def _cleanup(self, peer: Peer) -> None:
        if peer.session is None or peer.seat_index is None:
            return
        seat = peer.session.seat(peer.seat_index)
        if seat is None:
            return
        # 重连后座位已经绑到新连接上，旧连接的清理不能再把玩家标成掉线
        if getattr(seat, "peer", None) is not peer:
            return
        info = peer.session.disconnect(seat, _now())
        await self._broadcast(peer.session, "opponent_offline", info)

    # ---------- 路由 ----------

    async def _dispatch(self, peer: Peer, kind: str, data: dict) -> None:
        if kind == "ping":
            await self._send(peer, "pong", {"t": data.get("t"), "serverTime": time.time()})
            return

        if kind == "avatar_upload":
            raw = str(data.get("data") or "")
            try:
                payload = base64.b64decode(raw, validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                raise ProtocolError("头像数据不是合法 base64") from exc
            try:
                avatar_id = self.avatars.save(payload)
            except AvatarError as exc:
                raise ProtocolError(str(exc)) from exc
            await self._send(peer, "avatar_saved", {"id": avatar_id, "size": len(payload)})
            return

        if kind == "create_room":
            session = self.registry.create(self.config)
            seat = session.add_seat(str(data.get("name") or "房主"), data.get("avatar"))
            self._bind(peer, session, seat)
            logging.getLogger("room").info("建房 %s 房主=%s", session.code, seat.name)
            await self._send(
                peer,
                "room_created",
                {"code": session.code, "seat": seat.index, "token": seat.token, "room": session.room_payload()},
            )
            return

        if kind == "join_room":
            code = str(data.get("code", "")).strip()
            session = self.registry.get(code)
            if session is None:
                raise ProtocolError("房间不存在")
            if session.full:
                raise ProtocolError("房间已满")
            seat = session.add_seat(str(data.get("name") or "挑战者"), data.get("avatar"))
            self._bind(peer, session, seat)
            logging.getLogger("room").info("%s 加入房间 %s", seat.name, session.code)
            await self._send(
                peer,
                "room_joined",
                {"code": session.code, "seat": seat.index, "token": seat.token, "room": session.room_payload()},
            )
            await self._broadcast(session, "room_state", session.room_payload(), skip=peer)
            return

        if kind == "reconnect":
            code = str(data.get("code", "")).strip()
            token = str(data.get("token", ""))
            session = self.registry.get(code)
            if session is None:
                raise ProtocolError("房间不存在")
            seat = session.seat_by_token(token)
            if seat is None:
                raise ProtocolError("身份已失效，请重新进房")
            self._bind(peer, session, seat)
            payload = session.reconnect(seat, _now())
            await self._send(peer, "resync", payload)
            await self._broadcast(session, "opponent_online", {"seat": seat.index}, skip=peer)
            return

        session, seat = self._require(peer)

        if kind == "ready":
            started = session.mark_ready(seat, _now())
            if started is not None:
                logging.getLogger("game").info("房间 %s 开局", session.code)
                await self._broadcast(session, "game_start", started)
            else:
                await self._broadcast(session, "room_state", session.room_payload())
            return

        if kind == "move":
            raw = data.get("move") or data
            try:
                move = Move(tuple(raw["from"]), tuple(raw["to"]))
            except (KeyError, TypeError) as exc:
                raise ProtocolError("着法格式不对") from exc
            payload = session.apply_move(seat, move, _now())
            if session.phase == "finished":
                logging.getLogger("game").info(
                    "房间 %s 结束：%s", session.code, payload.get("text")
                )
                last = payload.get("lastMove")
                if last:
                    await self._broadcast(session, "move_applied", last)
                await self._broadcast(session, "game_over", payload)
            else:
                await self._broadcast(session, "move_applied", payload)
            return

        if kind == "resign":
            await self._broadcast(session, "game_over", session.resign(seat, _now()))
            return

        if kind == "offer_draw":
            session.offer_draw(seat)
            await self._broadcast(session, "draw_offered", {"seat": seat.index}, skip=peer)
            return

        if kind == "answer_draw":
            payload = session.answer_draw(seat, bool(data.get("accept")), _now())
            if payload is None:
                await self._broadcast(session, "draw_declined", {"seat": seat.index}, skip=peer)
            else:
                await self._broadcast(session, "game_over", payload)
            return

        if kind == "rematch":
            started = session.rematch(seat, _now())
            if started is None:
                await self._broadcast(session, "rematch_offered", {"seat": seat.index}, skip=peer)
            else:
                await self._broadcast(session, "game_start", started)
            return

        if kind == "leave_room":
            session.seats.remove(seat)
            peer.session = None
            peer.seat_index = None
            await self._broadcast(session, "room_state", session.room_payload())
            return

        raise ProtocolError(f"未知消息类型: {kind!r}")

    def _bind(self, peer: Peer, session: Session, seat) -> None:  # noqa: ANN001
        peer.session = session
        peer.seat_index = seat.index
        seat.ws = peer.ws
        seat.connected = True
        seat.disconnected_at = None
        setattr(seat, "peer", peer)

    def _require(self, peer: Peer) -> tuple[Session, object]:
        if peer.session is None or peer.seat_index is None:
            raise ProtocolError("还没进房间")
        seat = peer.session.seat(peer.seat_index)
        if seat is None:
            raise ProtocolError("座位不存在")
        return peer.session, seat

    # ---------- 后台循环 ----------

    async def ticker(self) -> None:
        while True:
            await asyncio.sleep(TICK_INTERVAL_S)
            now = _now()
            for session in list(self.registry.rooms.values()):
                try:
                    finished = session.tick(now)
                except Exception:  # noqa: BLE001 - 单个房间出错不能拖垮服务
                    continue
                if finished is not None:
                    await self._broadcast(session, "game_over", finished)
            self.registry.gc(now)

    async def clock_pusher(self) -> None:
        while True:
            await asyncio.sleep(CLOCK_PUSH_INTERVAL_S)
            now = _now()
            for session in self.registry.rooms.values():
                if session.phase != "playing" or session.clock is None:
                    continue
                await self._broadcast(session, "clock", session.clock_payload(now))


SERVER_KEY = web.AppKey("server", ChessServer)
TASKS_KEY = web.AppKey("tasks", list)


async def _start_background(app: web.Application) -> None:
    server: ChessServer = app[SERVER_KEY]
    app[TASKS_KEY] = [
        asyncio.create_task(server.ticker()),
        asyncio.create_task(server.clock_pusher()),
    ]


async def _stop_background(app: web.Application) -> None:
    for task in app.get(TASKS_KEY, []):
        task.cancel()


def create_app(config: Optional[ClockConfig] = None, data_dir: Optional[str] = None) -> web.Application:
    server = ChessServer(config, data_dir)
    app = web.Application()
    app[SERVER_KEY] = server
    app.router.add_get("/", server.health)
    app.router.add_get("/ws", server.websocket)
    app.router.add_get("/avatar/{avatar_id}", server.avatar_route)
    app.on_startup.append(_start_background)
    app.on_cleanup.append(_stop_background)
    return app


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="一起来下棋 · 联机服务端")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--base-minutes", type=float, default=30.0, help="保留时间（分钟）")
    parser.add_argument("--byo-seconds", type=float, default=30.0, help="读秒（秒/步）")
    parser.add_argument("--data-dir", default="server_data", help="头像等数据的存放目录")
    args = parser.parse_args(argv)

    config = ClockConfig(
        base_ms=int(args.base_minutes * 60 * 1000),
        byo_ms=int(args.byo_seconds * 1000),
    )
    print("=" * 56)
    print(" 一起来下棋 · 联机服务端 (M2)")
    print(f" 监听   http://{args.host}:{args.port}")
    print(f" 计时   {args.base_minutes:g} 分钟保留 + 每步 {args.byo_seconds:g} 秒读秒")
    print(" 局域网内的朋友把服务器地址填成：")
    for ip in lan_addresses():
        print(f"     {ip}:{args.port}")
    print(f" 自己这台机器填：127.0.0.1:{args.port}")
    print(" 首次运行如果 Windows 弹防火墙提示，选「允许访问」。")
    print("=" * 56)

    setup_logging(args.data_dir)
    web.run_app(create_app(config, args.data_dir), host=args.host, port=args.port, print=_quiet_print)
    return 0


def lan_addresses() -> list[str]:
    """猜本机的局域网 IP，省得让用户自己去 ipconfig 里翻。"""
    import socket

    found: set[str] = set()
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))  # UDP 不会真的发包
            found.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    try:
        found.add(socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    return sorted(ip for ip in found if not ip.startswith("127."))


def _quiet_print(*args, **kwargs) -> None:  # noqa: ARG001
    return


if __name__ == "__main__":
    raise SystemExit(main())
