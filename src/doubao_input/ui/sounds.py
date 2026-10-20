"""听写提示音 —— 对齐 Myna 的 `sounds` 开关。

Myna 自带 7 套音色(AGPL 资源),这里**不搬运**那些音频文件,而是播系统
freedesktop 事件音(`canberra-gtk-play`),所以:

  * 缺 libcanberra 就静默不响,不报错;
  * 音色跟系统走(换声音主题会跟着变);
  * Myna 的时机:按下即播 Start(不等模型 Ready),会话结束时播 Stop,
    严重错误必播 Error —— 这里同样。

**系统事件音被关掉时怎么办**(实测踩过的坑):
  GNOME 设置里「系统声音」(org.gnome.desktop.sound event-sounds)一旦是 false,
  libcanberra 会直接拒绝播放并报 `Failed to play sound: Sound disabled` ——
  工具明明在、事件音文件也明明在,就是一点声音都没有。
  所以:canberra 走不通时,退一步**直接放主题里的音频文件**(pw-play / paplay),
  让应用自己这个「提示音」开关说了算 —— 用户在应用里开了,就该听到。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from typing import Optional

logger = logging.getLogger(__name__)

TOOL = "canberra-gtk-play"

#: 直放兜底用的播放器(按优先级)
PLAYERS = ("pw-play", "paplay")

#: 时机 → freedesktop 事件音 id
EVENTS = {
    "start": "message-new-instant",
    "stop": "message",
    "error": "dialog-error",
}

#: 事件音 id → 可能用到的文件名(第一个存在的就用)
EVENT_FILES = {
    "message-new-instant": ("message-new-instant.oga", "message-new-instant.ogg"),
    "message": ("message.oga", "message.ogg"),
    "dialog-error": ("dialog-error.oga", "dialog-warning.oga", "dialog-error.ogg"),
}

#: 声音主题目录(桌面主题优先,最后兜底 freedesktop)
THEME_DIRS = (
    "/usr/share/sounds/gnome/stereo",
    "/usr/share/sounds/Yaru/stereo",
    "/usr/share/sounds/ubuntu/stereo",
    "/usr/share/sounds/freedesktop/stereo",
)

#: 系统事件音开关的缓存时间(秒):用户改了 GNOME 设置,一分钟内生效。
_EVENTS_CHECK_TTL = 60.0


class Sounds:
    """Play start/stop/error cues through the system sound theme."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = bool(enabled)
        self._tool: Optional[str] = shutil.which(TOOL)
        self._player: Optional[str] = self._find_player()
        self._events_ok: Optional[bool] = None
        self._events_checked_at = 0.0

    # ---- public ----

    @property
    def available(self) -> bool:
        """有没有任何办法出声(canberra 或直放播放器,有一个就行)。"""
        return self._tool is not None or self._player is not None

    def play(self, kind: str) -> None:
        if not self.enabled:
            return
        event = EVENTS.get(kind)
        if not event:
            return
        # 首选走系统主题(canberra):音色跟着系统走。
        if self._tool is not None and self._system_events_enabled():
            self._spawn([self._tool, "-i", event])
            return
        # 系统事件音被关掉了(canberra 会直接 "Sound disabled"),
        # 或者压根没有 canberra —— 直接放主题里的音频文件。
        path = self._event_file(event)
        if path and self._player is not None:
            self._spawn([self._player, path])
            return
        # 最后再试一次 canberra(系统设置可能刚被打开)。
        if self._tool is not None:
            self._spawn([self._tool, "-i", event])

    # ---- internals ----

    @staticmethod
    def _find_player() -> Optional[str]:
        for name in PLAYERS:
            path = shutil.which(name)
            if path:
                return path
        return None

    def _spawn(self, cmd: list[str]) -> None:
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:  # pragma: no cover
            logger.debug("sound %s failed: %s", cmd[0], e)

    def _system_events_enabled(self) -> bool:
        """GNOME 的「系统声音」开关。

        关掉时 libcanberra 直接拒绝播放(`Sound disabled`),这时候要绕开它。
        查不到这个键(非 GNOME 桌面)就按「开着」处理,交给 canberra 自己判断。
        """
        now = time.monotonic()
        if self._events_ok is not None and now - self._events_checked_at < _EVENTS_CHECK_TTL:
            return self._events_ok
        enabled = True
        if shutil.which("gsettings"):
            try:
                out = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.sound", "event-sounds"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                value = out.stdout.strip()
                if value in ("true", "false"):
                    enabled = value == "true"
                    if not enabled:
                        logger.info("系统事件音已关闭,提示音改为直接播放主题音频")
            except Exception as e:
                logger.debug("cannot read event-sounds: %s", e)
        self._events_ok = enabled
        self._events_checked_at = now
        return enabled

    @staticmethod
    def _event_file(event: str) -> Optional[str]:
        """在声音主题目录里找事件音文件。"""
        import os

        for name in EVENT_FILES.get(event, (f"{event}.oga",)):
            for directory in THEME_DIRS:
                path = os.path.join(directory, name)
                if os.path.exists(path):
                    return path
        return None
