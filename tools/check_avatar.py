"""头像自查工具：拿一张图，把"能不能设成头像"的每一步都试一遍并打印出来。

用法：
    .venv\\Scripts\\python.exe tools\\check_avatar.py "D:\\图片\\微信图片.jpg"

它会依次报：读文件 → 解码 → 裁剪 → 压缩 → 落盘，哪一步挂了、报什么错，一眼能看到。
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from client import config as appcfg  # noqa: E402
from client.avatar import (  # noqa: E402
    AVATAR_SIZE,
    AVATAR_TARGET_BYTES,
    compress_avatar,
    load_source_image,
    log_path,
    store_avatar,
)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法: python tools/check_avatar.py <图片路径>")
        return 2

    path = Path(argv[1])
    print("=" * 60)
    print(f"文件: {path}")
    print(f"存在: {path.exists()}")
    if not path.exists():
        print("结论: 文件不存在，路径写错了？")
        return 1
    size = path.stat().st_size
    print(f"大小: {size / 1024:.1f} KB ({size} 字节)")

    app = QApplication([])
    app.setApplicationName("一起来下棋")

    print(f"配置目录: {appcfg.config_dir()}")

    image, error = load_source_image(str(path))
    if image is None:
        print(f"解码: 失败 —— {error}")
        print("结论: 这张图 Qt 解不开（可能是 CMYK/HEIC 等特殊格式），先转成普通 JPG/PNG")
        return 1
    print(f"解码: 成功 {image.width()}×{image.height()}  格式={image.format().name}")

    from PySide6.QtCore import QPointF

    from client.avatar import square_crop

    cropped = square_crop(image, QPointF(image.width() / 2, image.height() / 2), 1.0, AVATAR_SIZE)
    print(f"裁剪: 成功 {cropped.width()}×{cropped.height()}")

    data, suffix = compress_avatar(cropped)
    if not data:
        print("压缩: 失败 —— 编码结果为空")
        return 1
    print(f"压缩: 成功 {len(data) / 1024:.1f} KB ({suffix})，上限 {AVATAR_TARGET_BYTES // 1024} KB")

    folder = appcfg.config_dir() / "avatars"
    try:
        stored = store_avatar(data, suffix, folder)
        print(f"落盘: 成功 {stored} ({stored.stat().st_size} 字节)")
    except OSError as exc:
        print(f"落盘: 失败 —— {exc}")
        print(f"      目录: {folder}")
        print("      原因通常是这个目录不可写，或是被杀毒软件锁住了")
        return 1
    except Exception:  # noqa: BLE001
        print("落盘: 异常")
        traceback.print_exc()
        return 1

    print("=" * 60)
    print("结论: 这张图可以正常设成头像（上面的字节数就是上传给对手的大小）")
    print(f"日志: {log_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
