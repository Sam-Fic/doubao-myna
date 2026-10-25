"""焦点窗口探测(best-effort)—— 用于「焦点离开就结束」这个可选开关。

Myna 靠 IBus 通道天然知道目标字段还在不在;本项目走剪贴板,没有这条通道,
所以只能问桌面。**能力因会话而异**:

  * GNOME:试 `org.gnome.Shell.Eval`(多数发行版默认关闭 → 拿不到);
  * X11(Unity / Xfce / GNOME-on-X11):`xdotool getwindowfocus`,
    退回 `xprop -root _NET_ACTIVE_WINDOW`;
  * Wayland(GNOME/Mutter):第三方进程**无法**读取别的窗口的焦点,
    除非装扩展 —— 这时开关会置灰,并显示原因。

拿不到焦点时按 Myna 的政策处理:`Support::Unknown` 也**照样工作**
(不因为探测不到就阻止录音),只是这个功能不生效。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gio  # type: ignore

from doubao_input.i18n import _

logger = logging.getLogger(__name__)

_EVAL_SCRIPT = (
    "const w = global.display.focus_window;"
    "w ? (String(w.get_wm_class()) + '|' + String(w.title)) : ''"
)

_backend_cache: str | None = None


def backend() -> str:
    """当前可用的探测方式:"gnome-eval" / "x11-xdotool" / "x11-xprop" / ""(无)。"""
    global _backend_cache
    if _backend_cache is None:
        _backend_cache = _detect_backend()
    return _backend_cache


def supported() -> bool:
    return bool(backend())


def reason() -> str:
    """给用户看的一句话说明(尤其是不支持时)。"""
    if supported():
        return ""
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("XDG_SESSION_TYPE") == "x11":
        return _(
            "On Wayland another process cannot read the focus of other windows "
            "(needs an X11 session or a GNOME Shell extension)"
        )
    return _("Neither xdotool nor xprop found, and GNOME Shell's Eval interface is unavailable")


def focused_identity() -> str | None:
    """当前焦点窗口的标识;探测不到返回 None。"""
    which = backend()
    if which == "gnome-eval":
        return _gnome_focus()
    if which == "x11-xdotool":
        out = _run(["xdotool", "getwindowfocus"])
        return f"x11:{out}" if out else None
    if which == "x11-xprop":
        out = _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
        if not out:
            return None
        # 形如: _NET_ACTIVE_WINDOW(WINDOW): window id # 0x4a00007
        token = out.split("#")[-1].strip() if "#" in out else out.strip()
        return f"x11:{token}" if token else None
    return None


# ---- internals ----

def _detect_backend() -> str:
    if _gnome_focus() is not None:
        return "gnome-eval"
    if not os.environ.get("DISPLAY"):
        return ""
    if shutil.which("xdotool"):
        return "x11-xdotool"
    if shutil.which("xprop"):
        return "x11-xprop"
    return ""


def _gnome_focus() -> str | None:
    try:
        proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.gnome.Shell",
            "/org/gnome/Shell",
            "org.gnome.Shell",
            None,
        )
        result = proxy.call_sync(
            "Eval",
            GLib.Variant("(s)", (_EVAL_SCRIPT,)),
            Gio.DBusCallFlags.NONE,
            300,
            None,
        )
        ok, value = result.unpack()
        if ok and value:
            return value
    except Exception as e:
        logger.debug("gnome shell Eval unavailable: %s", e)
    return None


def _run(argv: list[str]) -> str:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=2).stdout
        return out.strip()
    except Exception as e:
        logger.debug("%s failed: %s", " ".join(argv), e)
        return ""
