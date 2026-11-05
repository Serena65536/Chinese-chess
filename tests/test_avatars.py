"""头像存储测试：格式校验、大小上限、哈希命名、路径穿越防护。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage

from server.avatars import MAX_BYTES, AvatarError, AvatarStore, detect_image


def png_bytes(size: int = 16, color: str = "#c0392b") -> bytes:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(QColor(color))
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


@pytest.fixture()
def store(tmp_path):
    return AvatarStore(tmp_path / "avatars")


def test_detect_png_and_jpeg():
    assert detect_image(png_bytes())[0] == "png"
    assert detect_image(b"\xff\xd8\xff\xe0" + b"0" * 32)[0] == "jpg"
    assert detect_image(b"not an image at all") is None


def test_save_returns_stable_hash(store):
    data = png_bytes()
    first = store.save(data)
    second = store.save(data)
    assert first == second
    assert len(first) == 16
    assert all(ch in "0123456789abcdef" for ch in first)


def test_read_returns_bytes_and_mime(store):
    data = png_bytes()
    avatar_id = store.save(data)
    found = store.read(avatar_id)
    assert found is not None
    body, mime = found
    assert body == data
    assert mime == "image/png"


def test_rejects_non_image(store):
    with pytest.raises(AvatarError):
        store.save(b"<html>hello</html>" * 10)


def test_rejects_oversize(store):
    with pytest.raises(AvatarError):
        store.save(png_bytes() + b"\x00" * (MAX_BYTES + 1))


def test_rejects_empty(store):
    with pytest.raises(AvatarError):
        store.save(b"")


@pytest.mark.parametrize("bad", ["../../etc/passwd", "abc", "0123456789abcdef0", ""])
def test_read_rejects_bad_ids(store, bad):
    assert store.read(bad) is None


def test_unknown_id_returns_none(store):
    assert store.read("0123456789abcdef") is None
