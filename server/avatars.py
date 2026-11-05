"""头像存储：校验、落盘、按 id 读取。

安全口径：
- 只接受 PNG / JPEG / WebP 三种真实格式（看文件头，不看扩展名）
- 上限 512KB（客户端会自动压到 96KB 以内，这个上限是防手搓客户端）
- 文件名是内容哈希，天然防路径穿越；读取时再用正则卡一遍 id
- 读取时强制 `X-Content-Type-Options: nosniff`，浏览器不会把图片当脚本执行
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

MAX_BYTES = 512 * 1024
_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
)


class AvatarError(ValueError):
    """头像不合法（会以 error 消息回给客户端）。"""


def detect_image(data: bytes) -> Optional[tuple[str, str]]:
    """返回 (扩展名, MIME)；不认识的格式返回 None。"""
    for magic, ext, mime in _MAGIC:
        if data.startswith(magic):
            return ext, mime
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


class AvatarStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes) -> str:
        if not data:
            raise AvatarError("头像是空的")
        if len(data) > MAX_BYTES:
            raise AvatarError(f"头像太大（上限 {MAX_BYTES // 1024}KB）")
        info = detect_image(data)
        if info is None:
            raise AvatarError("只支持 PNG / JPEG / WebP 格式的图片")
        ext, _mime = info
        avatar_id = hashlib.sha256(data).hexdigest()[:16]
        path = self.root / f"{avatar_id}.{ext}"
        if not path.exists():
            path.write_bytes(data)
        return avatar_id

    def read(self, avatar_id: str) -> Optional[tuple[bytes, str]]:
        if not _ID_PATTERN.match(avatar_id or ""):
            return None
        for suffix, mime in ((".png", "image/png"), (".jpg", "image/jpeg"), (".webp", "image/webp")):
            path = self.root / f"{avatar_id}{suffix}"
            if path.exists():
                return path.read_bytes(), mime
        return None

    def exists(self, avatar_id: str) -> bool:
        return self.read(avatar_id) is not None
