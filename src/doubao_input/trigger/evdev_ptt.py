"""Global PTT trigger via evdev.

Listens for right-Ctrl key-down / key-up on every accessible keyboard
device under /dev/input/event*. Forwards both edges to the GTK main
thread via GLib.idle_add() so that downstream state-machine code
runs on the correct thread.

We do NOT grab the keyboard (EVIOCGRAB), so the right-Ctrl event is
still passed to the foreground application — that is acceptable
because right-Ctrl alone is harmless in nearly every app.

Multi-keyboard and hot-plug: device list is re-scanned periodically
(once per second) so that swapping a keyboard while running does not
leave us listening on a stale fd.
"""
from __future__ import annotations

import logging
import os
import select
import struct
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

EV_KEY = 0x01
KEY_RIGHTCTRL = 97  # linux/input-event-codes.h
# struct input_event = struct timeval + u16 type + u16 code + s32 value。
# timeval 的大小跟平台有关(64 位是两个 long = 16 字节,32 位是 8 字节),
# 所以布局和单事件大小都按运行平台推导,不能写死。
_TIME_SIZE = struct.calcsize("l")  # tv_sec 和 tv_usec 各一个 long
_EVENT_SIZE = _TIME_SIZE * 2 + 2 + 2 + 4
_EVENT_FORMAT = ("ll" if _TIME_SIZE == 8 else "ii") + "HHi"


def resolve_key_code(name: str) -> int:
    """evdev 键名(KEY_RIGHTCTRL / KEY_F13 / …)→ 键码;查不到就退回右 Ctrl。"""
    try:
        import evdev  # type: ignore

        codes = getattr(evdev.ecodes, "KEY", {})
        code = codes.get(name)
        if isinstance(code, int):
            return code
        # 有些版本 KEY_* 直接挂在 ecodes 上
        code = getattr(evdev.ecodes, name, None)
        if isinstance(code, int):
            return code
    except Exception as e:
        logger.warning("cannot resolve evdev key %r (%s), using KEY_RIGHTCTRL", name, e)
    logger.warning("unknown evdev key %r, using KEY_RIGHTCTRL", name)
    return KEY_RIGHTCTRL


class EvdevPtt:
    """Physical-key push-to-talk listener(键可配,默认右 Ctrl)。

    Callbacks (all invoked on the GTK main thread):
      on_press():   the configured key went down
      on_release(): the configured key went up
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        on_error: Callable[[str], None] | None = None,
        key_name: str = "KEY_RIGHTCTRL",
        cancel_key_name: str = "",
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._on_error = on_error
        self._key_name = key_name
        self._key_code = resolve_key_code(key_name)
        self._cancel_key_name = cancel_key_name
        self._on_cancel = on_cancel
        self._cancel_code = resolve_key_code(cancel_key_name) if cancel_key_name else None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._fds: list[int] = []
        self._paths: list[str] = []
        self._rescan_interval = 1.0
        self._last_rescan = 0.0

    # ---- public ----

    def start(self) -> bool:
        """Start the listener thread. Returns False if no accessible devices."""
        if not self._scan():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="evdev-ptt", daemon=True
        )
        self._thread.start()
        logger.info("EvdevPtt started on %d device(s)", len(self._fds))
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._close_fds()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- internals ----

    def _scan(self) -> bool:
        """Open every /dev/input/event* that we can read AND that has our key."""
        import evdev  # type: ignore

        self._close_fds()
        fds: list[int] = []
        paths: list[str] = []
        # evdev.list_devices() returns paths the process can actually open.
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()
                if EV_KEY in caps and self._key_code in caps[EV_KEY]:
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                    fds.append(fd)
                    paths.append(path)
            except (PermissionError, FileNotFoundError, OSError) as e:
                logger.debug("Skip %s: %s", path, e)
                continue
            except Exception as e:
                logger.debug("Skip %s: %s", path, e)
                continue
        self._fds = fds
        self._paths = paths
        return bool(fds)

    def _close_fds(self) -> None:
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds = []
        self._paths = []

    def _run(self) -> None:
        from gi.repository import GLib  # type: ignore

        buf = b""
        try:
            while not self._stop.is_set():
                # periodic rescan for hot-plug
                now = time.monotonic()
                if now - self._last_rescan > self._rescan_interval:
                    self._last_rescan = now
                    if not self._fds:
                        if not self._scan():
                            self._notify_error("无可访问的 /dev/input/event* 设备")
                            time.sleep(2.0)
                            continue

                if not self._fds:
                    time.sleep(0.2)
                    continue

                try:
                    rlist, _, _ = select.select(self._fds, [], [], 0.5)
                except (OSError, ValueError):
                    # Some fd was closed by the kernel (device unplugged). Re-scan.
                    self._close_fds()
                    continue
                for fd in rlist:
                    try:
                        data = os.read(fd, _EVENT_SIZE * 16)
                    except OSError:
                        continue
                    # read 可能刚好把最后一个事件切成两半:留下的半截
                    # 要接在下一轮 read 前面,不能整段覆盖丢弃。
                    buf += data
                    cut = len(buf) - (len(buf) % _EVENT_SIZE)
                    if cut <= 0:
                        continue
                    self._dispatch(buf[:cut], GLib.idle_add)
                    buf = buf[cut:]
        except Exception as e:  # pragma: no cover
            logger.exception("EvdevPtt crashed: %s", e)
            self._notify_error(f"evdev 监听崩溃: {e}")

    def _dispatch(self, data: bytes, idle_add) -> None:
        i = 0
        n = len(data)
        # Cache right-ctrl down state per "logical session" (across all fds).
        # We treat the down edge simply as "any fd just got a press",
        # because the kernel delivers only one of them to userspace readers
        # per real keypress.
        while i + _EVENT_SIZE <= n:
            tv_sec, tv_usec, ev_type, ev_code, ev_value = struct.unpack(
                _EVENT_FORMAT, data[i : i + _EVENT_SIZE]
            )
            i += _EVENT_SIZE
            if ev_type != EV_KEY:
                continue
            if self._cancel_code is not None and ev_code == self._cancel_code:
                # 取消键只要按下边沿(不做按键重复)。
                if ev_value == 1 and self._on_cancel is not None:
                    try:
                        idle_add(self._on_cancel)
                    except Exception:
                        pass
                continue
            if ev_code != self._key_code:
                continue
            if ev_value == 1:  # press
                try:
                    idle_add(self._on_press)
                except Exception:
                    pass
            elif ev_value == 0:  # release
                try:
                    idle_add(self._on_release)
                except Exception:
                    pass
            # ev_value == 2 (autorepeat) is intentionally ignored

    def _notify_error(self, msg: str) -> None:
        logger.warning(msg)
        if self._on_error:
            try:
                from gi.repository import GLib  # type: ignore
                GLib.idle_add(self._on_error, msg)
            except Exception:
                pass
