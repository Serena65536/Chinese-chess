"""客户端网络层的细节测试：代理必须显式关掉。

背景：Qt 默认会套用系统代理。连 127.0.0.1 时 Qt 自动绕过，所以本机测试都正常；
但连局域网/公网地址时会真的去走代理，遇到无效代理配置就报
"The proxy type is invalid for this operation"，表现为"怎么都连不上"。
这个文件守着这条不变量。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtNetwork import QNetworkProxy
from PySide6.QtWidgets import QApplication

from client.avatar_widget import AvatarLoader
from client.net import ChessClient

_APP = QApplication.instance() or QApplication([])


def test_websocket_disables_system_proxy():
    client = ChessClient()
    client.connect_to("192.0.2.10", 8765)  # TEST-NET-1，不可达，只为建 socket
    try:
        assert client.socket is not None
        assert client.socket.proxy().type() == QNetworkProxy.ProxyType.NoProxy
    finally:
        client.close()


def test_avatar_loader_disables_system_proxy():
    loader = AvatarLoader()
    assert loader._manager.proxy().type() == QNetworkProxy.ProxyType.NoProxy  # noqa: SLF001


def test_reconnect_rebuilds_socket_with_proxy_off():
    client = ChessClient()
    client.connect_to("192.0.2.11", 8765)
    first = client.socket
    client._open_socket()  # noqa: SLF001
    try:
        assert client.socket is not first, "重连必须换新的 socket"
        assert client.socket.proxy().type() == QNetworkProxy.ProxyType.NoProxy
    finally:
        client.close()
