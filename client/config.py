"""客户端配置：统一读写 + 版本迁移。

设计原则：
- 只用一个 JSON 文件，字段有 schemaVersion，读到老版本自动升级
- 任何一项读失败都退回默认值，绝不因为配置损坏而打不开程序
- 保存用"临时文件 + 替换"，避免写一半断电把配置写坏
"""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths

SCHEMA_VERSION = 2

DEFAULTS: dict[str, Any] = {
    "schemaVersion": SCHEMA_VERSION,
    "nickname": "玩家",
    "server": {"address": "127.0.0.1:8765", "host": "127.0.0.1", "port": 8765},
    "avatar": {"id": None, "file": None},
    "look": {"background": None, "darken": 55},
    "audio": {"bgm_volume": 0.65, "sfx_volume": 0.7, "sfx_enabled": True},
    "window": {"width": 1120, "height": 920},
}


_resolved_dir: Path | None = None


def _candidates() -> list[Path]:
    dirs: list[Path] = []
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if base:
        dirs.append(Path(base))
    dirs.append(Path.home() / ".一起来下棋")
    dirs.append(Path(tempfile.gettempdir()) / "一起来下棋")
    return dirs


def _usable(path: Path) -> bool:
    """真的写一笔试试——只看权限位不可靠（沙箱、杀软、网络盘都会骗人）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def config_dir() -> Path:
    """返回一个**确实可写**的配置目录；首选 APPDATA，写不了就逐级回退到临时目录。

    环境变量 `YQLXQ_CONFIG_DIR` 永远优先（每次调用都看，方便测试和绿色版）。
    """
    global _resolved_dir
    override = os.environ.get("YQLXQ_CONFIG_DIR")
    if override:
        return Path(override)
    if _resolved_dir is not None:
        return _resolved_dir
    for candidate in _candidates():
        if _usable(candidate):
            _resolved_dir = candidate
            return candidate
    _resolved_dir = Path(tempfile.gettempdir())
    return _resolved_dir


def reset_cache() -> None:
    """测试用：清掉已解析的目录。"""
    global _resolved_dir
    _resolved_dir = None


def config_file() -> Path:
    return config_dir() / "config.json"


def _merge(base: dict, incoming: dict) -> dict:
    """递归合并：以 DEFAULTS 为骨架，避免缺字段导致 KeyError。"""
    result = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _migrate(raw: dict) -> dict:
    """把 M1/M2 时代的老配置（顶层 server_host/server_port）升级到 v2。"""
    if raw.get("schemaVersion") == SCHEMA_VERSION:
        return raw

    migrated = deepcopy(raw)
    if "server_host" in migrated or "server_port" in migrated:
        migrated.setdefault("server", {})
        migrated["server"]["host"] = migrated.pop("server_host", DEFAULTS["server"]["host"])
        migrated["server"]["port"] = migrated.pop("server_port", DEFAULTS["server"]["port"])
    migrated["schemaVersion"] = SCHEMA_VERSION
    return migrated


def load() -> dict:
    path = config_file()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return deepcopy(DEFAULTS)
    except (OSError, json.JSONDecodeError):
        return deepcopy(DEFAULTS)
    return _merge(DEFAULTS, _migrate(raw))


def save(config: dict) -> bool:
    """原子写：先写 .tmp 再 os.replace，写失败返回 False（不抛）。"""
    config = dict(config)
    config["schemaVersion"] = SCHEMA_VERSION
    path = config_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def get(config: dict, dotted: str, default: Any = None) -> Any:
    """``get(cfg, "audio.sfx_volume")`` 这种取值方式，省掉层层 try。"""
    node: Any = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def set_value(config: dict, dotted: str, value: Any) -> dict:
    parts = dotted.split(".")
    node = config
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
    return config
