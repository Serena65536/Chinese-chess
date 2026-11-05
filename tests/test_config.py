"""配置模块测试：默认值、版本迁移、原子保存、损坏文件兜底。"""

from __future__ import annotations

import json

import pytest

from client import config as appcfg


@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    monkeypatch.setenv("YQLXQ_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_defaults_are_current_schema(temp_config):
    cfg = appcfg.load()
    assert cfg["schemaVersion"] == appcfg.SCHEMA_VERSION
    assert cfg["server"]["port"] == 8765
    assert cfg["audio"]["sfx_enabled"] is True


def test_save_and_load_roundtrip(temp_config):
    cfg = appcfg.load()
    appcfg.set_value(cfg, "nickname", "老王")
    appcfg.set_value(cfg, "look.darken", 80)
    assert appcfg.save(cfg) is True

    again = appcfg.load()
    assert again["nickname"] == "老王"
    assert again["look"]["darken"] == 80


def test_migrates_v1_flat_config(temp_config):
    legacy = {"server_host": "192.168.1.20", "server_port": 9001, "nickname": "小张"}
    (temp_config / "config.json").write_text(json.dumps(legacy), encoding="utf-8")

    cfg = appcfg.load()
    assert cfg["schemaVersion"] == appcfg.SCHEMA_VERSION
    assert cfg["server"]["host"] == "192.168.1.20"
    assert cfg["server"]["port"] == 9001
    assert cfg["nickname"] == "小张"


def test_corrupted_file_falls_back_to_defaults(temp_config):
    (temp_config / "config.json").write_text("{not json", encoding="utf-8")
    cfg = appcfg.load()
    assert cfg["server"]["host"] == "127.0.0.1"


def test_missing_fields_are_filled(temp_config):
    (temp_config / "config.json").write_text('{"schemaVersion": 2, "nickname": "只有名字"}', encoding="utf-8")
    cfg = appcfg.load()
    assert cfg["nickname"] == "只有名字"
    assert cfg["audio"]["bgm_volume"] == 0.65


def test_get_and_set_dotted(temp_config):
    cfg = appcfg.load()
    appcfg.set_value(cfg, "window.width", 1280)
    assert appcfg.get(cfg, "window.width") == 1280
    assert appcfg.get(cfg, "nope.missing", "fallback") == "fallback"


def test_usable_accepts_writable_dir(tmp_path):
    assert appcfg._usable(tmp_path / "someone" / "nested") is True  # noqa: SLF001


def test_usable_rejects_path_blocked_by_file(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("x", encoding="utf-8")
    # 目标路径的某一段是个文件，mkdir 必然失败
    assert appcfg._usable(blocker / "avatars") is False  # noqa: SLF001


def test_env_override_wins_over_cache(temp_config, monkeypatch, tmp_path):
    """环境变量要每次调用都生效，否则测试之间会串目录。"""
    monkeypatch.setenv("YQLXQ_CONFIG_DIR", str(temp_config))
    assert appcfg.config_dir() == temp_config
    other = tmp_path / "another"
    monkeypatch.setenv("YQLXQ_CONFIG_DIR", str(other))
    assert appcfg.config_dir() == other
