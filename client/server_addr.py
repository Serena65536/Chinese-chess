"""服务器地址解析：一个输入框，接受三种写法。

- ``192.168.1.20:8765``      局域网直连（ws://）
- ``wss://abc.trycloudflare.com``  Cloudflare 隧道（端口默认 443）
- ``https://chess.example.com``    带域名的隧道，自动换成 wss + https

输出两样东西：连对局用的 ``ws_url``，取头像用的 ``http_base``。
这样上层不用关心"用户到底填了什么形式"。
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_WS_PORT = 8765
DEFAULT_TLS_PORT = 443
DEFAULT_PLAIN_HTTP_PORT = 80


@dataclass(frozen=True)
class ServerAddress:
    ws_url: str
    http_base: str
    host: str
    port: int
    secure: bool

    @property
    def display(self) -> str:
        if self.secure:
            return f"wss://{self._authority()}"
        return f"{self.host}:{self.port}"

    def _authority(self) -> str:
        default = DEFAULT_TLS_PORT if self.secure else DEFAULT_PLAIN_HTTP_PORT
        host = _host_for_url(self.host)
        return host if self.port == default else f"{host}:{self.port}"


def _host_for_url(host: str) -> str:
    """IPv6 放进 URL 要加方括号。"""
    return f"[{host}]" if ":" in host else host


def _split_host_port(raw: str) -> tuple[str, int | None]:
    """``host`` / ``host:8765`` / ``[::1]:8765`` → (host, port|None)。"""
    raw = raw.strip()
    if not raw:
        raise ValueError("服务器地址不能为空")
    if raw.startswith("["):  # IPv6
        end = raw.find("]")
        if end < 0:
            raise ValueError("IPv6 地址缺少右括号")
        host = raw[1:end]
        rest = raw[end + 1 :]
        if rest.startswith(":"):
            return host, int(rest[1:])
        return host, None
    if raw.count(":") == 1:
        host, port_text = raw.split(":")
        if not port_text.isdigit():
            raise ValueError(f"端口不是数字：{port_text!r}")
        return host, int(port_text)
    if raw.count(":") > 1:  # 没加方括号的 IPv6，当作整段 host
        return raw, None
    return raw, None


def parse_address(text: str) -> ServerAddress:
    raw = (text or "").strip().rstrip("/")
    if not raw:
        raise ValueError("服务器地址不能为空")

    scheme = ""
    rest = raw
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
        scheme = scheme.lower()
        if "/" in rest:  # 允许带路径，但忽略（我们固定用 /ws）
            rest = rest.split("/", 1)[0]

    if scheme not in ("", "ws", "wss", "http", "https"):
        raise ValueError(f"不支持的协议：{scheme}://")
    secure = scheme in ("wss", "https")

    host, port = _split_host_port(rest)
    if not host:
        raise ValueError("服务器地址里没有主机名")
    if " " in host:
        raise ValueError("服务器地址里不能有空格")

    if port is None:
        port = DEFAULT_TLS_PORT if secure else DEFAULT_WS_PORT

    default = DEFAULT_TLS_PORT if secure else DEFAULT_PLAIN_HTTP_PORT
    host_in_url = _host_for_url(host)
    authority = host_in_url if port == default else f"{host_in_url}:{port}"
    ws_scheme = "wss" if secure else "ws"
    http_scheme = "https" if secure else "http"

    return ServerAddress(
        ws_url=f"{ws_scheme}://{authority}/ws",
        http_base=f"{http_scheme}://{authority}",
        host=host,
        port=port,
        secure=secure,
    )
