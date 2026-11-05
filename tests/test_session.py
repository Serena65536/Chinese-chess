"""房间会话测试：建房、就绪、权威判棋、超时、掉线暂停、重连、再来一局。"""

from __future__ import annotations

import pytest

from server.clock import ClockConfig
from server.session import GRACE_MS, ProtocolError, Session
from xiangqi_core import Color, Move


def make_session(base_ms: int = 60_000, byo_ms: int = 5_000) -> tuple[Session, object, object]:
    session = Session(code="123456", config=ClockConfig(base_ms=base_ms, byo_ms=byo_ms))
    host = session.add_seat("红方")
    guest = session.add_seat("黑方")
    return session, host, guest


def started(base_ms: int = 60_000, byo_ms: int = 5_000):
    session, host, guest = make_session(base_ms, byo_ms)
    session.mark_ready(host, 0.0)
    payload = session.mark_ready(guest, 0.0)
    assert payload is not None
    return session, host, guest, payload


# ---------- 房间 ----------


def test_add_seat_limits_two_players():
    session, host, guest = make_session()
    with pytest.raises(ProtocolError):
        session.add_seat("第三人")


def test_single_ready_does_not_start():
    session, host, guest = make_session()
    assert session.mark_ready(host, 0.0) is None
    assert session.phase == "waiting"


def test_both_ready_starts_game():
    session, host, guest, payload = started()
    assert session.phase == "playing"
    assert payload["fen"].startswith("rheakaehr")
    assert payload["redSeat"] == 0
    assert payload["clock"]["redMs"] == 60_000


# ---------- 权威判棋 ----------


def test_move_by_wrong_seat_rejected():
    session, host, guest, _ = started()
    with pytest.raises(ProtocolError):
        session.apply_move(guest, Move((1, 7), (4, 7)), 1.0)


def test_illegal_move_rejected():
    session, host, guest, _ = started()
    with pytest.raises(ProtocolError):
        session.apply_move(host, Move((1, 7), (1, 9)), 1.0)


def test_move_applies_and_switches_turn():
    session, host, guest, _ = started()
    payload = session.apply_move(host, Move((1, 7), (4, 7)), 2.0)
    assert payload["seq"] == 1
    assert payload["seat"] == 0
    assert session.turn_color() is Color.BLACK
    assert session.turn_seat() == 1
    assert payload["clock"]["redMs"] == 58_000
    assert len(payload["record"]) == 1


def test_move_rejected_when_clock_paused():
    session, host, guest, _ = started()
    session.disconnect(guest, 1.0)
    with pytest.raises(ProtocolError):
        session.apply_move(host, Move((1, 7), (4, 7)), 2.0)


# ---------- 超时 ----------


def test_timeout_on_tick():
    session, host, guest, _ = started(base_ms=1_000, byo_ms=500)
    assert session.tick(1.3) is None  # 保留用完但读秒还剩 200ms
    finished = session.tick(1.7)
    assert finished is not None
    assert finished["winner"] == 1  # 红方超时，黑方（座位 1）胜
    assert session.phase == "finished"


def test_timeout_from_move_is_game_over():
    session, host, guest, _ = started(base_ms=1_000, byo_ms=500)
    payload = session.apply_move(host, Move((1, 7), (4, 7)), 2.0)
    assert payload["timedOut"] is True
    assert payload["winner"] == 1
    assert session.phase == "finished"


# ---------- 掉线与重连 ----------


def test_disconnect_pauses_clock_and_blocks_timeout():
    session, host, guest, _ = started()
    session.disconnect(guest, 1.0)
    assert session.clock.paused is True
    assert session.tick(40.0) is None  # 暂停中，不判超时


def test_grace_expiry_loses_game():
    session, host, guest, _ = started()
    session.disconnect(guest, 1.0)
    finished = session.tick(1.0 + GRACE_MS / 1000 + 1)
    assert finished is not None
    assert finished["winner"] == 0  # 黑方掉线，红方胜


def test_reconnect_resumes_without_burning_paused_time():
    session, host, guest, _ = started()
    session.disconnect(host, 5.0)
    session.reconnect(host, 25.0)  # 暂停了 20 秒
    assert session.clock.paused is False
    # 只该扣掉暂停前的那 5 秒
    assert session.clock.remaining_ms(25.5) == 54_500


def test_reconnect_payload_has_game_state():
    session, host, guest, _ = started()
    session.apply_move(host, Move((1, 7), (4, 7)), 1.0)
    payload = session.reconnect(guest, 2.0)
    assert payload["phase"] == "playing"
    assert payload["game"]["fen"].startswith("rheakaehr/9/1c5c1")
    assert payload["game"]["record"] == ["1. 炮 b2-e2"]


# ---------- 人工结局与再来一局 ----------


def test_resign():
    session, host, guest, _ = started()
    payload = session.resign(guest, 3.0)
    assert payload["winner"] == 0
    assert "认输" in payload["reason"]
    assert session.phase == "finished"


def test_draw_offer_and_accept():
    session, host, guest, _ = started()
    session.offer_draw(host)
    assert session.answer_draw(guest, True, 2.0)["text"].startswith("和棋")


def test_draw_declined_keeps_playing():
    session, host, guest, _ = started()
    session.offer_draw(host)
    assert session.answer_draw(guest, False, 2.0) is None
    assert session.phase == "playing"


def test_rematch_swaps_colors():
    session, host, guest, _ = started()
    session.resign(guest, 2.0)
    assert session.rematch(host, 3.0) is None  # 只投一票
    payload = session.rematch(guest, 3.0)
    assert payload is not None
    assert payload["redSeat"] == 1  # 换先手
    assert session.phase == "playing"


# ---------- 时钟广播 ----------


def test_clock_payload_has_turn_seat():
    session, host, guest, _ = started()
    payload = session.clock_payload(1.0)
    assert payload["turnSeat"] == 0
    assert payload["seq"] == 0
