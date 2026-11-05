"""M1 取证脚本：跑一局脚本化的对局，抓关键画面。

产物：docs/m1/shots/*.png + docs/m1/report.json
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("YQLXQ_SFX_DIR", str(pathlib.Path(__file__).resolve().parents[1] / "build" / "sfx"))

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from client.app import MainWindow  # noqa: E402
from xiangqi_core import Board, Color, Game, Move, Status  # noqa: E402

SHOTS = ROOT / "docs" / "m1" / "shots"

# 一段中炮开局（每一步都过合法性校验），用来展示记谱、最后一步标记
OPENING = [
    ((1, 7), (4, 7)),   # 红：炮二平五
    ((7, 0), (6, 2)),   # 黑：马８进７
    ((1, 9), (2, 7)),   # 红：马二进三
    ((7, 2), (7, 4)),   # 黑：炮８进２
    ((0, 9), (0, 7)),   # 红：车一进二
    ((0, 3), (0, 4)),   # 黑：卒１进１
]


def grab(window: MainWindow, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(SHOTS / f"{name}.png"))


def main() -> int:
    app = QApplication(sys.argv)
    SHOTS.mkdir(parents=True, exist_ok=True)

    window = MainWindow()
    window.show_result_dialogs = False
    window.resize(1100, 920)
    window.show()
    app.processEvents()
    window.view.fit()
    app.processEvents()

    report: dict = {"opening": [], "checks": {}}

    # 1) 走完开局，抓主界面
    for src, dst in OPENING:
        window.view.animate_moves = False  # 截图要稳定，先关动画
        ok = window.play_move(Move(src, dst))
        report["opening"].append({"move": f"{src}->{dst}", "ok": ok})
        assert ok, f"着法被拒绝: {src}->{dst}"
    app.processEvents()
    grab(window, "01-midgame")
    report["record_lines"] = window.game.record_lines()
    report["turn"] = window.game.turn.label

    # 2) 将军画面：黑方走成被将，红方套红环
    window.load_game(
        Game(
            Board.from_fen(
                "3k5/9/9/9/9/4R4/9/9/9/5K3 w - - 0 1"
            )
        )
    )
    window.view.animate_moves = False
    window.play_move(Move((4, 5), (3, 5)))  # 车平到 3 路将军
    app.processEvents()
    grab(window, "02-check")
    report["checks"]["status"] = window.game.outcome.status.name
    report["checks"]["info_label"] = window.info_label.text()
    report["checks"]["check_square"] = window.view.check_square

    # 3) 动画中间帧：开动画、走一步、80ms 后抓
    window.load_game(Game())
    window.view.animate_moves = True
    window.play_move(Move((1, 7), (4, 7)))

    def mid_animation() -> None:
        grab(window, "03-animation")
        report["animation"] = {
            "is_animating": window.view.is_animating,
            "t": round(window.view._anim_t, 3),  # noqa: SLF001
        }
        finish()

    QTimer.singleShot(70, mid_animation)

    def finish() -> None:
        # 4) 终局：认输 → 侧栏显示结果
        window.load_game(
            Game(Board.from_fen("4k4/R2R5/9/9/9/9/9/9/9/5K3 w - - 0 1"))
        )
        window.view.animate_moves = False
        window.play_move(Move((0, 1), (0, 0)))  # 底线将死
        app.processEvents()
        grab(window, "04-checkmate")
        report["terminal"] = {
            "status": window.game.outcome.status.name,
            "text": window.game.outcome.text,
            "turn_label": window.turn_label.text(),
            "info_label": window.info_label.text(),
            "buttons_enabled": [window.resign_button.isEnabled(), window.draw_button.isEnabled()],
            "view_locked": window.view.locked,
        }

            # 5) 吃子路径（不截图，只验证"被吃的子"确实记录了）
        window.load_game(
            Game(Board.from_fen("3k5/9/9/9/3h5/9/9/3R5/9/5K3 w - - 0 1"))
        )
        ok_capture = window.play_move(Move((3, 7), (3, 4)))
        entry = window.game.entries[-1] if window.game.entries else None
        report["capture"] = {
            "ok": ok_capture,
            "captured": entry.captured.glyph if entry and entry.captured else None,
        }

        # 6) 音效文件与加载状态
        directory = window.sounds.directory
        report["sfx"] = {
            "directory": str(directory) if directory else None,
            "files": sorted(p.name for p in directory.glob("*.wav")) if directory else [],
            "status": window.sounds.status(),
        }

        out = ROOT / "docs" / "m1" / "report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report -> {out}")
        print("terminal status:", report["terminal"]["status"])
        print("animation capturing:", report["animation"]["is_animating"])
        app.quit()

    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
