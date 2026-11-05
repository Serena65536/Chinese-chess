"""服务器地址解析测试：局域网、Cloudflare 隧道、带域名的隧道都要认。"""

from __future__ import annotations

import pytest

from client.server_addr import parse_address


@pytest.mark.parametrize(
    "text,ws_url,http_base,secure",
    [
        ("192.168.1.20:8765", "ws://192.168.1.20:8765/ws", "http://192.168.1.20:8765", False),
        ("192.168.1.20", "ws://192.168.1.20:8765/ws", "http://192.168.1.20:8765", False),
        (" ws://192.168.1.20:9000 ", "ws://192.168.1.20:9000/ws", "http://192.168.1.20:9000", False),
        ("ws://192.168.1.20:9000/", "ws://192.168.1.20:9000/ws", "http://192.168.1.20:9000", False),
        ("wss://abc-def.trycloudflare.com", "wss://abc-def.trycloudflare.com/ws", "https://abc-def.trycloudflare.com", True),
        ("https://chess.example.com", "wss://chess.example.com/ws", "https://chess.example.com", True),
        ("wss://chess.example.com:8443", "wss://chess.example.com:8443/ws", "https://chess.example.com:8443", True),
        ("http://10.0.0.5:8765", "ws://10.0.0.5:8765/ws", "http://10.0.0.5:8765", False),
        ("[::1]:8765", "ws://[::1]:8765/ws", "http://[::1]:8765", False),
    ],
)
def test_parse_address(text, ws_url, http_base, secure):
    parsed = parse_address(text)
    assert parsed.ws_url == ws_url
    assert parsed.http_base == http_base
    assert parsed.secure is secure


@pytest.mark.parametrize("bad", ["", "   ", "host:abc", "ftp://example.com", "wss://", "a b:8765"])
def test_parse_address_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_address(bad)


def test_display_is_human_friendly():
    assert parse_address("192.168.1.20:8765").display == "192.168.1.20:8765"
    assert parse_address("wss://chess.example.com").display == "wss://chess.example.com"
    assert parse_address("wss://chess.example.com:8443").display == "wss://chess.example.com:8443"


def test_client_uses_parsed_urls():
    from PySide6.QtWidgets import QApplication

    from client.net import ChessClient

    _app = QApplication.instance() or QApplication([])
    client = ChessClient()
    try:
        client.connect("wss://abc.trycloudflare.com")
        assert client._url == "wss://abc.trycloudflare.com/ws"  # noqa: SLF001
        assert client.http_base == "https://abc.trycloudflare.com"
        assert client.secure is True
        assert client.port == 443
    finally:
        client.close()


def test_client_connect_to_legacy_wrapper():
    from PySide6.QtWidgets import QApplication

    from client.net import ChessClient

    _app = QApplication.instance() or QApplication([])
    client = ChessClient()
    try:
        client.connect_to("127.0.0.1", 8765)
        assert client._url == "ws://127.0.0.1:8765/ws"  # noqa: SLF001
        assert client.secure is False
    finally:
        client.close()
