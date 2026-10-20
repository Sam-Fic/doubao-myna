"""`myna-hud` 渲染器进程的启动与看护(不经 snap)。

`myna-hud` 是 ~/Desktop/myna/client 里的一个 Rust crate,直接
`cargo build -p myna-hud` 就能得到可执行文件(见 scripts/build-myna-hud.sh)。
它自己是 GTK4 单实例应用,启动后只是静静地等 D-Bus 上的状态,所以
这里要做的只有:找到它、拉起来、崩了再拉起来。

定位顺序:
  1. $MYNA_HUD
  2. ~/.local/bin/myna-hud
  3. $PATH 里的 myna-hud
  4. $MYNA_SOURCE_DIR(默认 ~/Desktop/myna)的 target/{release,debug}/myna-hud
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib  # type: ignore

logger = logging.getLogger(__name__)

# 崩溃后重启的退避:短命进程才算"崩了",连续崩够多次就放弃。
MIN_UPTIME_S = 3.0
MAX_RAPID_RESTARTS = 4
RESTART_DELAY_MS = 1000
TERM_GRACE_MS = 2000


class HudLauncher:
    """Start/supervise the `myna-hud` renderer process."""

    def __init__(self, binary: Optional[str] = None,
                 on_failed: Optional[Callable[[str], None]] = None) -> None:
        self._binary = binary
        self._on_failed = on_failed
        self._process: Optional[Gio.Subprocess] = None
        self._started_at = 0.0
        self._rapid_restarts = 0
        self._restart_source = 0
        self._stopping = False

    # ---- public ----

    @property
    def running(self) -> bool:
        return self._process is not None

    @property
    def binary(self) -> Optional[str]:
        return self._binary or self.resolve_binary()

    def start(self) -> bool:
        """Spawn the renderer. False when it cannot be found or cannot start."""
        if self.running or self._restart_source:
            return True
        binary = self._binary or self.resolve_binary()
        if not binary:
            logger.warning(
                "myna-hud not found; set $MYNA_HUD or run scripts/build-myna-hud.sh"
            )
            return False
        self._binary = binary
        argv = [binary] + session_args()
        try:
            self._process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
        except Exception as e:
            logger.warning("failed to spawn %s: %s", " ".join(argv), e)
            return False
        self._started_at = time.monotonic()
        self._process.wait_async(None, self._on_exited)
        logger.info("myna-hud started: %s", " ".join(argv))
        return True

    def stop(self) -> None:
        self._stopping = True
        if self._restart_source:
            GLib.source_remove(self._restart_source)
            self._restart_source = 0
        if self._process is None:
            return
        proc, self._process = self._process, None
        proc.send_signal(15)  # SIGTERM
        GLib.timeout_add(TERM_GRACE_MS, self._force_exit, proc)

    # ---- discovery ----

    @staticmethod
    def resolve_binary() -> Optional[str]:
        env = os.environ.get("MYNA_HUD")
        if env:
            return env if os.access(env, os.X_OK) else None

        candidates = [Path.home() / ".local" / "bin" / "myna-hud"]
        which = shutil.which("myna-hud")
        if which:
            candidates.append(Path(which))

        source_dir = os.environ.get("MYNA_SOURCE_DIR", str(Path.home() / "Desktop" / "myna"))
        for profile in ("release", "debug"):
            candidates.append(Path(source_dir) / "client" / "target" / profile / "myna-hud")

        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        return None

    # ---- supervision ----

    def _on_exited(self, proc: Gio.Subprocess, _result) -> None:
        try:
            proc.wait_finish(_result)
        except Exception:
            pass
        # 被信号杀死时 get_exit_status() 会触发 GLib 断言,先问是不是信号。
        detail = (
            f"signal {proc.get_term_sig()}"
            if proc.get_if_signaled()
            else f"status {proc.get_exit_status()}"
        )
        uptime = time.monotonic() - self._started_at
        self._process = None
        if self._stopping:
            return
        logger.warning("myna-hud exited (%s, uptime=%.1fs)", detail, uptime)

        if uptime < MIN_UPTIME_S:
            self._rapid_restarts += 1
            if self._rapid_restarts >= MAX_RAPID_RESTARTS:
                message = f"myna-hud keeps dying within {MIN_UPTIME_S}s; giving up"
                logger.error(message)
                if self._on_failed:
                    self._on_failed(message)
                return
        else:
            self._rapid_restarts = 0

        self._restart_source = GLib.timeout_add(RESTART_DELAY_MS, self._restart)

    def _restart(self) -> bool:
        self._restart_source = 0
        if self._stopping:
            return GLib.SOURCE_REMOVE
        if not self.start():
            if self._on_failed:
                self._on_failed("myna-hud could not be restarted")
        return GLib.SOURCE_REMOVE

    def _force_exit(self, proc: Gio.Subprocess) -> bool:
        try:
            proc.force_exit()  # SIGKILL;已经退出的进程上是空操作
        except Exception:
            pass
        return GLib.SOURCE_REMOVE


EXTENSION_UUID = "myna-shell@canonical.com"
EXTENSION_SETTINGS_SCHEMA = "org.gnome.shell"
EXTENSION_SETTINGS_KEY = "enabled-extensions"


def extension_enabled() -> bool:
    """GNOME 的 myna-shell 扩展是否已启用。

    启用时由扩展负责拉起并摆放渲染器(它能用 Meta.WaylandClient 把窗口
    定位到屏幕底部、避开 dock),我们就不要自己再拉一个进程了 —— 否则
    myna-hud 的单实例会把第二个实例转发回第一个,扩展的重启逻辑会打转。
    """
    try:
        settings = Gio.Settings.new(EXTENSION_SETTINGS_SCHEMA)
        return EXTENSION_UUID in settings.get_strv(EXTENSION_SETTINGS_KEY)
    except Exception:
        return False


def session_args() -> list[str]:
    """Extra `myna-hud` arguments for the running session.

    Wayland 下由桌面(或 GNOME 的 myna-shell 扩展)负责摆放窗口,X11 下
    myna-hud 可以自己托管窗口(`--host x11`)。
    """
    if not os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY"):
        return ["--host", "x11"]
    return []
