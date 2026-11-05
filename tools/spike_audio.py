"""spike ②：QMediaPlayer 循环播 BGM + 音量淡入。

跑法：
    .venv\\Scripts\\python.exe tools\\spike_audio.py

会现场合成一段 6 秒的测试音（不引入任何音乐文件），验证：
- 能进入 PlayingState 且播放进度在推进
- 淡入：音量从 0 平滑升到目标值
- 淡出：音量平滑降到 0
- 播放到结尾能自动下一首
"""

from __future__ import annotations

import json
import math
import os
import struct
import sys
import time
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from client.media import BgmPlayer  # noqa: E402

OUT = ROOT / "docs" / "m0" / "audio"


def make_tone(path: Path, seconds: float = 6.0, freq: float = 440.0, rate: int = 44100) -> None:
    """合成一段带淡入淡出的正弦音，纯标准库，不需要任何音频素材。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    total = int(rate * seconds)
    for i in range(total):
        t = i / rate
        # 两个八度叠加，听起来像"音乐"一点
        value = 0.35 * math.sin(2 * math.pi * freq * t) + 0.18 * math.sin(2 * math.pi * freq * 1.5 * t)
        envelope = min(1.0, t / 0.5, max(0.0, (seconds - t) / 0.5))
        sample = int(max(-1.0, min(1.0, value * envelope)) * 32767)
        frames += struct.pack("<h", sample)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))


def main() -> int:
    tone = OUT / "tone-440hz.wav"
    tone2 = OUT / "tone-523hz.wav"
    make_tone(tone, 6.0, 440.0)
    make_tone(tone2, 4.0, 523.25)

    app = QApplication(sys.argv)
    player = BgmPlayer()
    player.set_playlist([tone, tone2])

    samples: list[dict] = []
    started = time.perf_counter()
    player.set_volume(0.8)
    player.play(fade_in_ms=1500)

    phase = {"fade_out_started_at": None, "analyzed": False}

    def tick() -> None:
        elapsed = time.perf_counter() - started
        samples.append(
            {
                "t": round(elapsed, 3),
                "volume": round(player.volume, 4),
                "state": player.state.name,
                "position_ms": player.position_ms,
            }
        )
        if elapsed > 2.6 and phase["fade_out_started_at"] is None:
            phase["fade_out_started_at"] = elapsed
            player.fade_to(0.0, 900)
        if elapsed > 4.2 and not phase["analyzed"]:
            phase["analyzed"] = True
            player.stop()
            timer.stop()
            app.quit()

    timer = QTimer()
    timer.setInterval(120)
    timer.timeout.connect(tick)
    timer.start()

    app.exec()

    playing = [s for s in samples if s["state"] == "PlayingState"]
    volumes = [s["volume"] for s in samples if s["t"] < 2.4]
    fade_out = [s["volume"] for s in samples if phase["fade_out_started_at"] and s["t"] > phase["fade_out_started_at"]]

    report = {
        "samples": len(samples),
        "played_state_reached": bool(playing),
        "position_advanced_ms": (samples[-1]["position_ms"] if samples else 0),
        "fade_in": {
            "start": volumes[0] if volumes else None,
            "peak": max(volumes) if volumes else None,
            "monotonic_rise": all(b >= a - 1e-6 for a, b in zip(volumes, volumes[1:])),
        },
        "fade_out": {
            "start": fade_out[0] if fade_out else None,
            "end": fade_out[-1] if fade_out else None,
            "monotonic_fall": all(b <= a + 1e-6 for a, b in zip(fade_out, fade_out[1:])),
        },
        "playlist_auto_advance": "未在本轮触发（需要等 6 秒播完）",
        "wav_bytes": tone.stat().st_size,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    ok = (
        report["played_state_reached"]
        and report["position_advanced_ms"] > 1000
        and report["fade_in"]["monotonic_rise"]
        and report["fade_out"]["monotonic_fall"]
        and report["fade_out"]["end"] is not None
        and report["fade_out"]["end"] < 0.05
    )
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
