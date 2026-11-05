"""客户端网络层：QWebSocket 连接 + 消息分发 + 自动重连。

设计：这里只管"连接与消息"，不碰棋盘，界面订阅信号即可。

重连策略：每次重连都**新建一个 QWebSocket**（旧对象 abort + deleteLater）。
复用同一个 socket 在"连上又立刻断"的情况下会卡在 ConnectingState，导致后面
所有重试都只是空转——这是踩过的坑，别再改回去。
"""

from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket, QNetworkProxy
from PySide6.QtWebSockets import QWebSocket

from .server_addr import ServerAddress, parse_address

RECONNECT_INTERVAL_MS = 2000
RECONNECT_MAX_ATTEMPTS = 15


class ChessClient(QObject):
    statusChanged = Signal(str)
    errorRaised = Signal(str)
    socketConnected = Signal()
    avatarSaved = Signal(dict)

    roomUpdated = Signal(dict)  # room_created / room_joined / room_state
    gameStarted = Signal(dict)  # game_start（含再来一局、重连后的 resync）
    moveApplied = Signal(dict)
    clockSync = Signal(dict)
    gameOver = Signal(dict)
    resynced = Signal(dict)
    opponentOffline = Signal(dict)
    opponentOnline = Signal(dict)
    drawOffered = Signal(dict)
    drawDeclined = Signal(dict)
    rematchOffered = Signal(dict)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.socket: Optional[QWebSocket] = None
        self.host = "127.0.0.1"
        self.port = 8765
        self.secure = False
        self.http_base = "http://127.0.0.1:8765"
        self.room_code: Optional[str] = None
        self.seat: Optional[int] = None
        self.token: Optional[str] = None
        self.auto_reconnect = True

        self._url = ""
        self._closing = False
        self._swapping = False
        self._attempts = 0
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(RECONNECT_INTERVAL_MS)
        self._retry_timer.timeout.connect(self._try_reconnect)

    # ---------- 连接 ----------

    @property
    def connected(self) -> bool:
        if self.socket is None:
            return False
        return self.socket.state() == QAbstractSocket.SocketState.ConnectedState

    def connect(self, address: str) -> None:
        """``address`` 可以是 host:port，也可以是 wss://域名（Cloudflare 隧道）。"""
        parsed: ServerAddress = parse_address(address)
        self.host = parsed.host
        self.port = parsed.port
        self.secure = parsed.secure
        self.http_base = parsed.http_base
        self._url = parsed.ws_url
        self._closing = False
        self._attempts = 0
        self._retry_timer.stop()
        self.statusChanged.emit(f"正在连接 {parsed.display} …")
        self._open_socket()

    def connect_to(self, host: str, port: int) -> None:
        """老接口，保留给测试和局域网直连。"""
        self.connect(f"{host}:{port}")

    def close(self) -> None:
        self._closing = True
        self._retry_timer.stop()
        if self.socket is not None:
            self._swapping = True
            try:
                self.socket.abort()
            except RuntimeError:
                pass
            self._swapping = False
            self.socket.deleteLater()
            self.socket = None
        self.room_code = None
        self.seat = None
        self.token = None
        self.statusChanged.emit("已断开")

    def _open_socket(self) -> None:
        """新建一条连接（旧的一定先废掉，避免卡在 ConnectingState）。"""
        if self.socket is not None:
            self._swapping = True
            try:
                self.socket.abort()
                self.socket.deleteLater()
            except RuntimeError:
                pass
            self._swapping = False
            self.socket = None

        socket = QWebSocket()
        # 关键：显式禁用系统代理。
        # 不设的话，Qt 会拿系统代理配置去连局域网/公网 IP，遇到"代理类型无效"
        # 就直接连不上（127.0.0.1 会被 Qt 自动绕过，所以本机测试发现不了）。
        socket.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        socket.textMessageReceived.connect(self._on_text)
        socket.connected.connect(self._on_connected)
        socket.disconnected.connect(self._on_disconnected)
        socket.errorOccurred.connect(self._on_socket_error)
        self.socket = socket
        if self._url:
            socket.open(QUrl(self._url))

    def _on_connected(self) -> None:
        self._attempts = 0
        self._retry_timer.stop()
        self.statusChanged.emit("已连接服务器")
        self.socketConnected.emit()
        if self.room_code and self.token:
            self.send("reconnect", {"code": self.room_code, "token": self.token})

    def _on_disconnected(self) -> None:
        if self._closing or self._swapping:
            return
        self.statusChanged.emit("连接断开，正在重连…")
        if self.auto_reconnect and self.room_code and self.token:
            self._retry_timer.start()
        else:
            self.statusChanged.emit("已断开")

    def _on_socket_error(self, error) -> None:  # noqa: ANN001
        if self._closing or self._swapping:
            return
        self.statusChanged.emit(f"连接出错：{self.socket.errorString() if self.socket else error}")

    def _try_reconnect(self) -> None:
        self._attempts += 1
        if self._attempts > RECONNECT_MAX_ATTEMPTS:
            self._retry_timer.stop()
            self.statusChanged.emit("重连失败")
            self.errorRaised.emit("与服务器的连接已断开，请重新加入房间")
            return
        self.statusChanged.emit(f"正在重连（第 {self._attempts} 次）…")
        self._open_socket()

    # ---------- 收发 ----------

    def send(self, kind: str, data: Optional[dict] = None) -> None:
        if not self.connected or self.socket is None:
            return
        self.socket.sendTextMessage(json.dumps({"type": kind, "data": data or {}}, ensure_ascii=False))

    def _on_text(self, text: str) -> None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return
        kind = payload.get("type")
        data = payload.get("data") or {}

        if kind == "pong":
            return
        if kind == "error":
            self.errorRaised.emit(str(data.get("message", "服务端返回错误")))
            return
        if kind in ("room_created", "room_joined"):
            self.room_code = data.get("code", self.room_code)
            self.seat = data.get("seat", self.seat)
            self.token = data.get("token", self.token)
            self.roomUpdated.emit(data)
            return
        if kind == "room_state":
            self.roomUpdated.emit(data)
            return
        if kind == "game_start":
            self.gameStarted.emit(data)
            return
        if kind == "move_applied":
            self.moveApplied.emit(data)
            return
        if kind == "clock":
            self.clockSync.emit(data)
            return
        if kind == "game_over":
            self.gameOver.emit(data)
            return
        if kind == "resync":
            self.seat = data.get("seat", self.seat)
            self.resynced.emit(data)
            if data.get("phase") == "playing" and "game" in data:
                self.gameStarted.emit(data["game"])
            return
        if kind == "avatar_saved":
            self.avatarSaved.emit(data)
            return
        if kind == "opponent_offline":
            self.opponentOffline.emit(data)
            return
        if kind == "opponent_online":
            self.opponentOnline.emit(data)
            return
        if kind == "draw_offered":
            self.drawOffered.emit(data)
            return
        if kind == "draw_declined":
            self.drawDeclined.emit(data)
            return
        if kind == "rematch_offered":
            self.rematchOffered.emit(data)
            return

    # ---------- 语义化快捷方法 ----------

    def create_room(self, name: str, avatar: Optional[str] = None) -> None:
        self.send("create_room", {"name": name, "avatar": avatar})

    def join_room(self, code: str, name: str, avatar: Optional[str] = None) -> None:
        self.send("join_room", {"code": code.strip(), "name": name, "avatar": avatar})

    def upload_avatar(self, data: bytes) -> None:
        import base64

        self.send("avatar_upload", {"data": base64.b64encode(data).decode("ascii")})

    def ready(self) -> None:
        self.send("ready")

    def move(self, src: tuple[int, int], dst: tuple[int, int]) -> None:
        self.send("move", {"move": {"from": list(src), "to": list(dst)}})

    def resign(self) -> None:
        self.send("resign")

    def offer_draw(self) -> None:
        self.send("offer_draw")

    def answer_draw(self, accept: bool) -> None:
        self.send("answer_draw", {"accept": accept})

    def rematch(self) -> None:
        self.send("rematch")

    def leave_room(self) -> None:
        self.send("leave_room")
        self.room_code = None
        self.seat = None
        self.token = None
