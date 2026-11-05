"""一起来下棋 · 客户端主窗口。

两种模式共用同一套棋盘：
- 本地：自己跟自己下（M1 的调试台，也是没有服务器时的默认状态）
- 联机：服务端是唯一裁判，客户端只把结果画出来（M2）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QImage, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from xiangqi_core import Board, Color, Game, Move, Status

from . import config as appcfg
from . import logging_setup
from .fonts import ensure_fonts
from .onboarding import OnboardingDialog
from .version import __app_name__, __version__
from .avatar import encode_avatar, load_avatar_file, store_avatar
from .avatar_widget import AvatarBadge, AvatarLoader
from .board_view import BoardView, MOVE_ANIM_MS
from .clock_bar import ClockBar
from .media import BgmPlayer
from .net import ChessClient
from .server_addr import parse_address
from .settings_dialog import SettingsDialog
from .sfx import SoundBank

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__}")

        self.game = Game()
        self.view = BoardView(self.game.board)
        self.view.legal_provider = self.game.legal_targets
        self.view.moveRequested.connect(self._on_move)

        self.bgm = BgmPlayer(self)
        self.bgm.errorRaised.connect(lambda msg: self.statusBar().showMessage(msg, 5000))
        self.sounds = SoundBank(parent=self)
        self._background_path: Path | None = None
        self.show_result_dialogs = True

        # 联机状态
        self.client: Optional[ChessClient] = None
        self.online = False
        self.my_seat: Optional[int] = None
        self.red_seat = 0
        self.room_code: Optional[str] = None
        self.nickname = "玩家"
        self.server_address = f"{DEFAULT_HOST}:{DEFAULT_PORT}"
        self._record_lines: list[str] = []
        self._pending_action: Optional[tuple] = None

        self.cfg = appcfg.load()
        saved = appcfg.get(self.cfg, "server.address")
        if not saved:
            saved = f"{appcfg.get(self.cfg, 'server.host', DEFAULT_HOST)}:{appcfg.get(self.cfg, 'server.port', DEFAULT_PORT)}"
        self.server_address = str(saved)
        self.nickname = str(appcfg.get(self.cfg, "nickname", "玩家"))
        avatar_file = appcfg.get(self.cfg, "avatar.file")
        self._avatar_image = load_avatar_file(avatar_file)
        self._avatar_file_bytes = Path(avatar_file).read_bytes() if avatar_file and Path(avatar_file).exists() else None
        self._avatar_bytes: Optional[bytes] = self._avatar_file_bytes
        self._avatar_id: Optional[str] = None
        self._avatar_uploaded = False
        self.avatar_loader = AvatarLoader(self)

        self._build_ui()
        self._build_menus()
        self._build_status_bar()
        self._apply_config()
        self._sync_all()
        self.setMinimumSize(880, 700)
        width = int(appcfg.get(self.cfg, "window.width", 1120))
        height = int(appcfg.get(self.cfg, "window.height", 920))
        self.resize(width, height)

    # ---------- 界面 ----------

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(14)
        layout.addWidget(self.view, 1)
        layout.addWidget(self._build_side_panel())
        self.setCentralWidget(central)

    def _build_side_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFixedWidth(250)
        panel.setObjectName("sidePanel")
        panel.setStyleSheet(
            "#sidePanel { background: #241b14; border-radius: 10px; }"
            "QLabel { color: #e8dcc8; }"
            "QLabel#turnLabel { font-size: 20px; font-weight: 700; }"
            "QLabel#infoLabel { color: #c9a86a; font-size: 13px; padding-top: 2px; }"
            "QLabel#hintLabel { color: #e0a040; font-size: 12px; }"
            "QLabel#connLabel { color: #8fa08a; font-size: 12px; }"
            "QListWidget { background: #1b140f; color: #d8c9b0; border: 1px solid #3a2c20;"
            "  border-radius: 6px; font-family: Consolas, 'Microsoft YaHei'; font-size: 12px; }"
            "QPushButton { background: #3a2c20; color: #f0e6d2; border: 1px solid #55402c;"
            "  border-radius: 6px; padding: 7px 10px; font-size: 13px; }"
            "QPushButton:hover { background: #4a382a; }"
            "QPushButton:disabled { color: #7a6a58; background: #2b2118; }"
        )

        box = QVBoxLayout(panel)
        box.setContentsMargins(14, 14, 14, 14)
        box.setSpacing(9)

        players = QHBoxLayout()
        players.setSpacing(6)
        mine = QVBoxLayout()
        mine.setSpacing(3)
        self.my_badge = AvatarBadge(46)
        self.my_name_label = QLabel("我")
        self.my_name_label.setAlignment(Qt.AlignCenter)
        self.my_name_label.setStyleSheet("font-size:12px; color:#d8c9b0;")
        mine.addWidget(self.my_badge, 0, Qt.AlignHCenter)
        mine.addWidget(self.my_name_label)
        theirs = QVBoxLayout()
        theirs.setSpacing(3)
        self.opponent_badge = AvatarBadge(46)
        self.opponent_name_label = QLabel("对手")
        self.opponent_name_label.setAlignment(Qt.AlignCenter)
        self.opponent_name_label.setStyleSheet("font-size:12px; color:#d8c9b0;")
        theirs.addWidget(self.opponent_badge, 0, Qt.AlignHCenter)
        theirs.addWidget(self.opponent_name_label)
        players.addLayout(mine, 1)
        players.addLayout(theirs, 1)
        self.players_box = QWidget()
        self.players_box.setLayout(players)
        self.players_box.setVisible(False)
        box.addWidget(self.players_box)

        self.clock_bar = ClockBar()
        self.clock_bar.setVisible(False)
        box.addWidget(self.clock_bar)

        self.turn_label = QLabel("轮到 · 红方")
        self.turn_label.setObjectName("turnLabel")
        self.info_label = QLabel("")
        self.info_label.setObjectName("infoLabel")
        self.move_count_label = QLabel("第 0 手")
        self.move_count_label.setObjectName("infoLabel")

        box.addWidget(self.turn_label)
        box.addWidget(self.move_count_label)
        box.addWidget(self.info_label)
        box.addSpacing(6)

        self.conn_label = QLabel("未联机 · 本地对局")
        self.conn_label.setObjectName("connLabel")
        self.conn_label.setWordWrap(True)
        box.addWidget(self.conn_label)

        list_title = QLabel("记谱")
        list_title.setObjectName("infoLabel")
        box.addWidget(list_title)
        self.move_list = QListWidget()
        self.move_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        box.addWidget(self.move_list, 1)

        self.hint_label = QLabel("")
        self.hint_label.setObjectName("hintLabel")
        self.hint_label.setWordWrap(True)
        box.addWidget(self.hint_label)

        self.online_row = QHBoxLayout()
        self.online_row.setSpacing(6)
        self.create_button = QPushButton("创建房间")
        self.create_button.clicked.connect(self._create_room)
        self.join_button = QPushButton("加入房间")
        self.join_button.clicked.connect(self._join_room)
        self.ready_button = QPushButton("准备")
        self.ready_button.setEnabled(False)
        self.ready_button.clicked.connect(self._ready)
        self.online_row.addWidget(self.create_button)
        self.online_row.addWidget(self.join_button)
        self.online_row.addWidget(self.ready_button)
        box.addLayout(self.online_row)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.resign_button = QPushButton("认输")
        self.resign_button.clicked.connect(self._resign)
        self.draw_button = QPushButton("求和")
        self.draw_button.clicked.connect(self._offer_draw)
        buttons.addWidget(self.resign_button)
        buttons.addWidget(self.draw_button)
        box.addLayout(buttons)

        self.restart_button = QPushButton("重新开始")
        self.restart_button.clicked.connect(self._restart)
        box.addWidget(self.restart_button)

        return panel

    def _build_menus(self) -> None:
        game_menu = self.menuBar().addMenu("对局(&G)")
        restart = QAction("重新开始", self)
        restart.setShortcut(QKeySequence("Ctrl+N"))
        restart.triggered.connect(self._restart)
        game_menu.addAction(restart)

        flip = QAction("翻转棋盘", self)
        flip.setShortcut(QKeySequence("Ctrl+F"))
        flip.triggered.connect(lambda: self.view.set_flipped(not self.view.flipped))
        game_menu.addAction(flip)

        game_menu.addSeparator()
        resign = QAction("认输", self)
        resign.triggered.connect(self._resign)
        game_menu.addAction(resign)
        draw = QAction("求和", self)
        draw.triggered.connect(self._offer_draw)
        game_menu.addAction(draw)

        game_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        game_menu.addAction(quit_action)

        online_menu = self.menuBar().addMenu("联机(&L)")
        server = QAction("服务器地址…", self)
        server.triggered.connect(self._ask_server)
        online_menu.addAction(server)
        online_menu.addSeparator()
        create = QAction("创建房间…", self)
        create.triggered.connect(self._create_room)
        online_menu.addAction(create)
        join = QAction("加入房间…", self)
        join.triggered.connect(self._join_room)
        online_menu.addAction(join)
        online_menu.addSeparator()
        disconnect = QAction("断开连接", self)
        disconnect.triggered.connect(self._disconnect)
        online_menu.addAction(disconnect)

        look_menu = self.menuBar().addMenu("外观(&V)")
        pick_bg = QAction("选择背景图…", self)
        pick_bg.triggered.connect(self._pick_background)
        look_menu.addAction(pick_bg)
        clear_bg = QAction("清除背景图", self)
        clear_bg.triggered.connect(self._clear_background)
        look_menu.addAction(clear_bg)
        look_menu.addSeparator()
        darken_more = QAction("背景更暗 (+10)", self)
        darken_more.triggered.connect(lambda: self._nudge_darken(10))
        look_menu.addAction(darken_more)
        darken_less = QAction("背景更亮 (-10)", self)
        darken_less.triggered.connect(lambda: self._nudge_darken(-10))
        look_menu.addAction(darken_less)

        music_menu = self.menuBar().addMenu("音乐(&M)")
        pick_music = QAction("选择背景音乐…", self)
        pick_music.triggered.connect(self._pick_music)
        music_menu.addAction(pick_music)
        play = QAction("播放", self)
        play.triggered.connect(lambda: self.bgm.play(fade_in_ms=2000))
        music_menu.addAction(play)
        pause = QAction("暂停", self)
        pause.triggered.connect(self.bgm.pause)
        music_menu.addAction(pause)
        stop = QAction("停止", self)
        stop.triggered.connect(self.bgm.stop)
        music_menu.addAction(stop)

        sound_menu = self.menuBar().addMenu("音效(&S)")
        self.sound_action = QAction("开启音效", self, checkable=True)
        self.sound_action.setChecked(True)
        self.sound_action.toggled.connect(self._toggle_sound)
        sound_menu.addAction(self.sound_action)

        self.menuBar().addAction(self._settings_action())

        help_menu = self.menuBar().addMenu("帮助(&H)")
        open_folder = QAction("打开配置目录", self)
        open_folder.triggered.connect(self._open_config_folder)
        help_menu.addAction(open_folder)
        open_logs = QAction("打开日志目录", self)
        open_logs.triggered.connect(self._open_log_folder)
        help_menu.addAction(open_logs)
        about = QAction("关于", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    def _build_status_bar(self) -> None:
        self.statusBar().showMessage("点自己的棋子看可走位置，再点落点走子", 8000)

    # ---------- 状态同步 ----------

    def _my_color(self) -> Optional[Color]:
        if not self.online or self.my_seat is None:
            return None
        return Color.RED if self.my_seat == self.red_seat else Color.BLACK

    def _my_turn(self) -> bool:
        return self.online and self.game.turn is self._my_color()

    def _sync_all(self) -> None:
        turn = self.game.turn
        self.turn_label.setText(f"轮到 · {turn.label}")
        self.turn_label.setStyleSheet("color: #ff6b5e;" if turn is Color.RED else "color: #d8d0c0;")
        self.move_count_label.setText(f"第 {len(self._record_lines)} 手")

        outcome = self.game.outcome
        if outcome.status is Status.CHECK:
            self.info_label.setText("将军！")
        elif outcome.finished:
            self.info_label.setText(outcome.text)
        else:
            self.info_label.setText("")

        self._sync_moves()

        check_square = None
        if outcome.status in (Status.CHECK, Status.CHECKMATE):
            check_square = self.game.board.find_king(self.game.turn)
        self.view.set_check(check_square)

        over = self.game.is_over
        self.resign_button.setEnabled(not over)
        self.draw_button.setEnabled(not over)

        if self.online:
            self.view.set_locked(over or not self._my_turn())
            self.restart_button.setText("再来一局" if over else "对局中…")
            self.restart_button.setEnabled(over)
        else:
            self.view.set_locked(over)
            self.restart_button.setText("重新开始")
            self.restart_button.setEnabled(True)

        self._update_conn_label()

    def _sync_moves(self) -> None:
        if self.move_list.count() != len(self._record_lines):
            self.move_list.clear()
            self.move_list.addItems(self._record_lines)
            self.move_list.scrollToBottom()

    def _update_conn_label(self) -> None:
        if not self.online:
            self.conn_label.setText("未联机 · 本地对局")
            return
        color = self._my_color()
        # 注意别写成 `if color`：Color.RED 的值是 0，布尔判断为假，会把红方显示成"观战"
        who = color.label if color is not None else "观战"
        self.conn_label.setText(f"房间 {self.room_code or '—'} · 你是{who}")

    def _toast(self, message: str) -> None:
        self.statusBar().showMessage(message, 4000)

    # ---------- 本地 / 联机共用的落子流程 ----------

    def play_move(self, move: Move) -> bool:
        """本地模式走一步（界面点击与脚本演示共用）。"""
        if self.game.is_over:
            return False
        piece = self.game.board.piece_at(*move.src)
        if piece is None:
            return False
        try:
            outcome = self.game.play(move)
        except ValueError as exc:
            self._toast(str(exc))
            self.view.set_selection(None, [])
            return False

        captured = self.game.entries[-1].captured
        self._record_lines = self.game.record_lines()
        self.view.animate_move(move, piece)
        self._sync_all()
        self._play_sound(outcome, captured)
        if outcome.finished:
            QTimer.singleShot(MOVE_ANIM_MS + 60, lambda: self._show_result(outcome))
        if outcome.hint:
            self.hint_label.setText(outcome.hint)
        return True

    def _play_sound(self, outcome, captured=None) -> None:  # noqa: ANN001
        if outcome.finished:
            self.sounds.play("win")
        elif outcome.status is Status.CHECK:
            self.sounds.play("check")
            self._toast("将军！")
        elif captured is not None:
            self.sounds.play("capture")
        else:
            self.sounds.play("move")

    def _on_move(self, move: Move) -> None:
        if self.online:
            if not self._my_turn():
                self._toast("还没轮到你走")
                self.view.set_selection(None, [])
                return
            if self.client is not None:
                self.client.move(move.src, move.dst)
                self.view.set_selection(None, [])
            return
        self.play_move(move)

    def _show_result(self, outcome) -> None:  # noqa: ANN001
        if not self.show_result_dialogs:
            return
        box = QMessageBox(self)
        box.setWindowTitle("对局结束")
        box.setText(outcome.text)
        if outcome.hint:
            box.setInformativeText(outcome.hint)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()

    # ---------- 本地按钮 ----------

    def _restart(self) -> None:
        if self.online:
            if self.client is not None:
                self.client.rematch()
                self._toast("已提出再来一局，等对手同意")
            return
        self.game.reset()
        self._record_lines = []
        self.view.set_board(self.game.board)
        self.move_list.clear()
        self.hint_label.setText("")
        self._sync_all()
        self._toast("新的一局，红先")

    def load_game(self, game: Game) -> None:
        self.game = game
        self.view.legal_provider = game.legal_targets
        self.view.set_board(game.board)
        self.move_list.clear()
        self._record_lines = game.record_lines()
        self.hint_label.setText("")
        self._sync_all()

    def _resign(self) -> None:
        if self.game.is_over:
            return
        side = self.game.turn if not self.online else self._my_color()
        if side is None:
            return
        if QMessageBox.question(
            self, "认输", f"确认{side.label}认输？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        if self.online:
            if self.client is not None:
                self.client.resign()
            return
        outcome = self.game.resign(side)
        self._record_lines = self.game.record_lines()
        self._sync_all()
        self.sounds.play("win")
        QTimer.singleShot(120, lambda: self._show_result(outcome))

    def _offer_draw(self) -> None:
        if self.game.is_over:
            return
        if self.online:
            if self.client is not None:
                self.client.offer_draw()
                self._toast("已提出和棋")
            return
        if QMessageBox.question(
            self, "求和", "对手是否同意和棋？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        outcome = self.game.agree_draw()
        self._sync_all()
        QTimer.singleShot(120, lambda: self._show_result(outcome))

    # ---------- 联机 ----------

    def _ensure_client(self) -> ChessClient:
        if self.client is not None:
            return self.client
        client = ChessClient(self)
        client.statusChanged.connect(self._on_net_status)
        client.errorRaised.connect(self._on_net_error)
        client.socketConnected.connect(self._on_socket_ready)
        client.avatarSaved.connect(self._on_avatar_saved)
        client.roomUpdated.connect(self._on_room_updated)
        client.gameStarted.connect(self._on_game_start)
        client.moveApplied.connect(self._on_move_applied)
        client.clockSync.connect(self._on_clock)
        client.gameOver.connect(self._on_game_over)
        client.resynced.connect(self._on_resync)
        client.opponentOffline.connect(self._on_opponent_offline)
        client.opponentOnline.connect(lambda _data: self._toast("对手已回到房间"))
        client.drawOffered.connect(self._on_draw_offered)
        client.drawDeclined.connect(lambda _data: self._toast("对手拒绝了和棋"))
        client.rematchOffered.connect(self._on_rematch_offered)
        self.client = client
        client.host = self.server_host
        client.port = self.server_port
        return client

    def _ask_server(self) -> None:
        text, ok = QInputDialog.getText(
            self,
            "服务器地址",
            "填 host:port（局域网）或 wss://xxx.trycloudflare.com（公网隧道）：",
            text=self.server_address,
        )
        if not ok or not text.strip():
            return
        try:
            parsed = parse_address(text)
        except ValueError as exc:
            QMessageBox.warning(self, "地址不对", str(exc))
            return
        self.server_address = text.strip()
        self._persist("server", {"address": self.server_address, "host": parsed.host, "port": parsed.port})
        self._toast(f"服务器：{parsed.display}")

    def _connect_if_needed(self) -> None:
        client = self._ensure_client()
        if not client.connected:
            try:
                client.connect(self.server_address)
            except ValueError as exc:
                self._toast(f"服务器地址不对：{exc}")
                QMessageBox.warning(self, "服务器地址", f"{exc}\n\n例子：192.168.1.20:8765 或 wss://abc.trycloudflare.com")
                return
            return
        self._run_pending()

    def _run_pending(self) -> None:
        action = self._pending_action
        if action is None or self.client is None:
            return
        self._pending_action = None
        if action[0] == "create":
            self.client.create_room(action[1], self._avatar_id)
        elif action[0] == "join":
            self.client.join_room(action[1], action[2], self._avatar_id)

    def _create_room(self) -> None:
        name, ok = QInputDialog.getText(self, "创建房间", "你的昵称：", text=self.nickname)
        if not ok or not name.strip():
            return
        self.nickname = name.strip()
        self._persist("nickname", self.nickname)
        self._pending_action = ("create", self.nickname)
        self._connect_if_needed()

    def _join_room(self) -> None:
        code, ok = QInputDialog.getText(self, "加入房间", "6 位房间码：")
        if not ok or not code.strip():
            return
        name, ok2 = QInputDialog.getText(self, "加入房间", "你的昵称：", text=self.nickname)
        if not ok2 or not name.strip():
            return
        self.nickname = name.strip()
        self._persist("nickname", self.nickname)
        self._pending_action = ("join", code.strip(), self.nickname)
        self._connect_if_needed()

    def _ready(self) -> None:
        if self.client is not None:
            self.client.ready()
            self.ready_button.setEnabled(False)
            self._toast("已准备，等待对手")

    def _disconnect(self) -> None:
        if self.client is not None:
            self.client.leave_room()
            self.client.close()
        self.online = False
        self.my_seat = None
        self.room_code = None
        self.clock_bar.setVisible(False)
        self.ready_button.setEnabled(False)
        self._sync_all()
        self._toast("已断开联机")

    # ---------- 网络事件 ----------

    def _on_net_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)
        if not self.online:
            self.conn_label.setText(message)

    def _on_net_error(self, message: str) -> None:
        self._toast(message)
        QMessageBox.warning(self, "联机提示", message)

    def _on_room_updated(self, data: dict) -> None:
        self.room_code = data.get("code", self.room_code)
        if "seat" in data:
            self.my_seat = data["seat"]
        room = data.get("room") or data
        seats = room.get("seats") or data.get("seats") or []
        self.red_seat = int(room.get("redSeat", self.red_seat))
        if len(seats) == 2:
            self.ready_button.setEnabled(True)
            self._apply_names(seats)
            self._set_players(seats)
            self.conn_label.setText(
                f"房间 {self.room_code} · {seats[0]['name']} vs {seats[1]['name']} · 点「准备」开局"
            )
        else:
            self.conn_label.setText(f"房间 {self.room_code} · 等待对手加入…")
        self._toast(f"已进入房间 {self.room_code}")

    def _apply_names(self, seats: list[dict]) -> None:
        if not seats:
            return
        names = {seat["seat"]: seat["name"] for seat in seats}
        red_name = names.get(self.red_seat, "红方")
        black_name = names.get(1 - self.red_seat, "黑方")
        self.clock_bar.set_names(red_name, black_name)
        self.turn_label.setToolTip(f"{red_name} vs {black_name}")

    def _on_game_start(self, data: dict) -> None:
        self.online = True
        self.red_seat = int(data.get("redSeat", 0))
        if self.my_seat is None and self.client is not None:
            self.my_seat = self.client.seat
        fen = data.get("fen")
        if fen:
            self.game = Game(Board.from_fen(fen))
            self.view.legal_provider = self.game.legal_targets
            self.view.set_board(self.game.board)
        self._record_lines = list(data.get("record") or [])
        self.move_list.clear()
        self.hint_label.setText("")
        self.clock_bar.setVisible(True)
        self._apply_names(data.get("seats") or [])
        self._set_players(data.get("seats") or [])
        self._on_clock(data.get("clock") or {})
        self.view.set_flipped(self._my_color() is Color.BLACK)
        self._sync_all()
        self._toast("对局开始！")

    def _on_move_applied(self, data: dict) -> None:
        if not self.online:
            return
        move = Move(tuple(data["move"]["from"]), tuple(data["move"]["to"]))
        piece = self.game.board.piece_at(*move.src)
        try:
            self.game.play(move)
        except ValueError:
            fen = data.get("fen")
            if fen:
                self.game = Game(Board.from_fen(fen))
                self.view.legal_provider = self.game.legal_targets
                self.view.set_board(self.game.board)
            piece = None

        if piece is not None:
            self.view.animate_move(move, piece)
        else:
            self.view.last_move = move
            self.view._refresh()  # noqa: SLF001

        self._record_lines = list(data.get("record") or self.game.record_lines())
        status = data.get("status") or {}
        captured = self.game.entries[-1].captured if self.game.entries else None
        self._apply_clock(data.get("clock") or {})
        self._sync_all()

        if status.get("finished"):
            self.sounds.play("win")
        elif status.get("check"):
            self.sounds.play("check")
        elif captured is not None:
            self.sounds.play("capture")
        else:
            self.sounds.play("move")

    def _apply_clock(self, snapshot: dict) -> None:
        if snapshot:
            self.clock_bar.apply(snapshot)
        turn = self.game.turn
        self.turn_label.setText(f"轮到 · {turn.label}")
        self.turn_label.setStyleSheet("color: #ff6b5e;" if turn is Color.RED else "color: #d8d0c0;")

    def _on_clock(self, data: dict) -> None:
        if not self.online or not data:
            return
        self.clock_bar.apply(data)

    def _on_game_over(self, data: dict) -> None:
        self.online = True
        self._apply_clock(data.get("clock") or {})
        winner_seat = data.get("winner")
        winner = None
        if winner_seat is not None:
            winner = Color.RED if int(winner_seat) == self.red_seat else Color.BLACK
        self.game.set_outcome(
            data.get("status") or "ongoing", winner=winner, reason=data.get("reason", "")
        )
        self._sync_all()
        text = data.get("text") or "对局结束"
        self.info_label.setText(text)
        self.view.set_locked(True)
        self.resign_button.setEnabled(False)
        self.draw_button.setEnabled(False)
        self.restart_button.setText("再来一局")
        self.conn_label.setText(f"房间 {self.room_code} · {text}")
        self.sounds.play("win")
        if self.show_result_dialogs:
            box = QMessageBox(self)
            box.setWindowTitle("对局结束")
            box.setText(text)
            box.setInformativeText("点「再来一局」可立刻再战（先手会轮换）")
            box.exec()

    def _on_resync(self, data: dict) -> None:
        self.my_seat = data.get("seat", self.my_seat)
        room = data.get("room") or {}
        self.room_code = room.get("code", self.room_code)
        self.red_seat = int(room.get("redSeat", self.red_seat))
        self._apply_names(room.get("seats") or [])
        self._toast("已重新连接，局面已同步")

    def _on_opponent_offline(self, data: dict) -> None:
        seconds = int(data.get("graceMs", 90000)) // 1000
        self._toast(f"对手掉线，时钟已暂停（{seconds} 秒内回来可继续）")

    def _on_draw_offered(self, data: dict) -> None:  # noqa: ARG002
        accepted = (
            QMessageBox.question(
                self, "对方求和", "对手提出和棋，同意吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            == QMessageBox.Yes
        )
        if self.client is not None:
            self.client.answer_draw(accepted)

    def _on_rematch_offered(self, data: dict) -> None:  # noqa: ARG002
        if QMessageBox.question(
            self, "再来一局", "对手想再来一局，同意吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        ) == QMessageBox.Yes:
            if self.client is not None:
                self.client.rematch()

    # ---------- 个性化 ----------

    def _nudge_darken(self, delta: int) -> None:
        self.view.set_background(self.view.background_image, self.view.background_darken + delta)
        self._toast(f"背景暗化：{self.view.background_darken}%")

    def _pick_background(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择对局背景图", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "打不开", "这张图读不出来，换一张试试。")
            return
        self._background_path = Path(path)
        self.view.set_background(image)
        self._toast(f"背景已换成：{Path(path).name}")

    def _clear_background(self) -> None:
        self._background_path = None
        self.view.set_background(None)

    def _pick_music(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择背景音乐", "", "音频 (*.mp3 *.ogg *.wav *.flac)"
        )
        if not paths:
            return
        self.bgm.set_playlist(paths)
        self.bgm.play(fade_in_ms=2000)
        self._toast(f"已载入 {len(paths)} 首，开始播放")

    def _toggle_sound(self, enabled: bool) -> None:
        self.sounds.set_enabled(enabled)
        self._toast("音效已开启" if enabled else "音效已关闭")

    # ---------- 配置与设置 ----------

    def _persist(self, dotted: str, value) -> None:  # noqa: ANN001
        appcfg.set_value(self.cfg, dotted, value)
        appcfg.save(self.cfg)

    def _settings_action(self) -> QAction:
        action = QAction("设置…", self)
        action.setShortcut(QKeySequence("Ctrl+,"))
        action.triggered.connect(self._open_settings)
        return action

    def _open_log_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        folder = logging_setup.log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        self._toast(f"日志目录：{folder}")

    def _open_config_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        folder = appcfg.config_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        self._toast(f"配置目录：{folder}")

    def _avatar_folder(self) -> Path:
        return appcfg.config_dir() / "avatars"

    def _apply_config(self) -> None:
        self._apply_look(appcfg.get(self.cfg, "look", {}) or {})
        self._apply_audio(appcfg.get(self.cfg, "audio", {}) or {})
        if self._avatar_image is not None:
            self.my_badge.set_image(self._avatar_image)
        self.my_badge.set_name(self.nickname)
        self.my_name_label.setText(self.nickname)

    def _apply_look(self, look: dict) -> None:
        path = look.get("background")
        image = QImage(str(path)) if path else None
        self.view.set_background(
            None if image is None or image.isNull() else image,
            int(look.get("darken", 55)),
        )

    def _apply_audio(self, audio: dict) -> None:
        self.bgm.set_volume(float(audio.get("bgm_volume", 0.65)))
        self.sounds.set_volume(float(audio.get("sfx_volume", 0.7)))
        enabled = bool(audio.get("sfx_enabled", True))
        self.sounds.set_enabled(enabled)
        self.sound_action.blockSignals(True)
        self.sound_action.setChecked(enabled)
        self.sound_action.blockSignals(False)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            self.cfg,
            self._avatar_image,
            self._avatar_folder(),
            lambda: self.sounds.play("move"),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self._apply_settings(dialog.values())

    def _apply_settings(self, values: dict) -> None:
        self.nickname = values["nickname"]
        self.server_address = values["server"]["address"]
        appcfg.set_value(self.cfg, "nickname", self.nickname)
        appcfg.set_value(self.cfg, "server", values["server"])  # 含 address/host/port
        appcfg.set_value(self.cfg, "look", values["look"])
        appcfg.set_value(self.cfg, "audio", values["audio"])

        if values["avatar_bytes"]:
            # 裁剪对话框那一步已经落过盘了，这里不再重复写；万一当时没写成功，
            # 也照样把图用在本次会话里，只是重启后要重选。
            self._avatar_bytes = values["avatar_bytes"]
            self._avatar_image = values["avatar_image"]
            self._avatar_id = None
            self._avatar_uploaded = False
            appcfg.set_value(
                self.cfg,
                "avatar",
                {"id": None, "file": values.get("avatar_file") or appcfg.get(self.cfg, "avatar.file")},
            )
            self.my_badge.set_image(self._avatar_image)
        appcfg.save(self.cfg)

        self._apply_look(values["look"])
        self._apply_audio(values["audio"])
        self.my_name_label.setText(self.nickname)
        self.my_badge.set_name(self.nickname)
        if self.client is not None and self.client.connected:
            self._upload_avatar_if_needed()
        self._toast("设置已保存")

    # ---------- 头像 ----------

    def _on_socket_ready(self) -> None:
        # 用"实际连上的地址"而不是配置里的地址：手动 connect_to 时两者可能不同
        base = self.client.http_base if self.client is not None else "http://127.0.0.1:8765"
        self.avatar_loader.set_base_url(base)
        self._upload_avatar_if_needed()

    def _upload_avatar_if_needed(self) -> None:
        if self.client is None or not self.client.connected:
            return
        if self._avatar_bytes and not self._avatar_uploaded:
            self.client.upload_avatar(self._avatar_bytes)
            return
        self._run_pending()

    def _on_avatar_saved(self, data: dict) -> None:
        self._avatar_id = data.get("id")
        self._avatar_uploaded = True
        self._persist("avatar.id", self._avatar_id)
        self._run_pending()

    def _set_players(self, seats: list[dict]) -> None:
        if not seats or len(seats) < 2:
            self.players_box.setVisible(False)
            return
        self.players_box.setVisible(True)
        by_seat = {int(seat["seat"]): seat for seat in seats}
        mine_seat = self.my_seat if self.my_seat is not None else 0
        mine = by_seat.get(mine_seat, {})
        theirs = by_seat.get(1 - mine_seat, {})
        self.my_name_label.setText(str(mine.get("name", "我")))
        self.opponent_name_label.setText(str(theirs.get("name", "对手")))
        self.my_badge.set_name(str(mine.get("name", "我")))
        self.opponent_badge.set_name(str(theirs.get("name", "对手")))
        if mine.get("avatar"):
            self.avatar_loader.subscribe(str(mine["avatar"]), self.my_badge.set_image)
        if theirs.get("avatar"):
            self.avatar_loader.subscribe(str(theirs["avatar"]), self.opponent_badge.set_image)

    def _about(self) -> None:
        QMessageBox.information(
            self,
            "关于 一起来下棋",
            f"{__app_name__} v{__version__}\n\n"
            "Python 3 + PySide6(Qt6)\n"
            "服务端与客户端共用同一份棋规内核，服务端权威判棋\n\n"
            "已支持：联机房间（6 位码）、30 分钟保留 + 每步 30 秒读秒、\n"
            "断线 90 秒内自动重连、认输/求和/再来一局、将死/困毙/循环判罚。",
        )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName(__app_name__)
    ensure_fonts()
    logging_setup.configure("client")

    # 首次启动（还没有配置文件）才弹欢迎页，老用户升级不会被打扰
    first_run = not appcfg.config_file().exists()
    window = MainWindow()
    window.show()
    if first_run:
        OnboardingDialog(window).exec()
        appcfg.set_value(window.cfg, "onboarded", True)
        appcfg.save(window.cfg)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
