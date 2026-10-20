"""桌面自定义快捷键 —— 与 Myna 同一套做法。

Myna 不自己监听按键,而是往桌面写一个"自定义快捷键",命令是
`gdbus call … com.canonical.Myna.Dictation.Toggle`。好处是:

  * `<Super>j`、`Ctrl+Alt+Space` 这类**组合键**也能用(evdev 只认得物理单键);
  * 按键由桌面托管,和别的应用冲突时由桌面负责让出;
  * 设置窗口里改键立刻生效,不需要重启本进程。

本项目的 D-Bus 发布端(`hud/publisher.py`)已经实现了 `Toggle`,所以这条路径
是现成的:桌面按下 → gdbus 调 Toggle → 本项目的 press/release。

GNOME 走 dconf(`org.gnome.settings-daemon.plugins.media-keys`),
Xfce 走 `xfconf-query`(best-effort)。
"""

from __future__ import annotations

import logging
import subprocess

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio  # type: ignore

from doubao_input.doubao.config import TOGGLE_COMMAND

logger = logging.getLogger(__name__)

GNOME_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
RELOCATABLE_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
GNOME_PATH = (
    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/doubao-input/"
)
ENTRY_NAME = "Doubao Dictation"

XFCE_CHANNEL = "xfce4-keyboard-shortcuts"

#: 桌面自带的快捷键 schema(GNOME)。Myna 同样检查这五个,并把以 `-static`
#: 结尾的键视为"桌面保留"(gsd 登录时抓取,不能让出)。
DESKTOP_SCHEMAS = [
    ("org.gnome.desktop.wm.keybindings", "窗口管理"),
    ("org.gnome.mutter.keybindings", "Mutter"),
    ("org.gnome.mutter.wayland.keybindings", "Mutter(Wayland)"),
    ("org.gnome.shell.keybindings", "Shell"),
    ("org.gnome.settings-daemon.plugins.media-keys", "媒体键"),
]


class DesktopShortcut:
    """Read/write the desktop's custom keyboard shortcut for dictation."""

    # ---- capability ----

    @staticmethod
    def available() -> bool:
        """桌面是否支持我们写快捷键。"""
        try:
            Gio.Settings.new(GNOME_SCHEMA)
            return True
        except Exception:
            pass
        return DesktopShortcut._has("xfconf-query")

    # ---- read ----

    def binding(self) -> str:
        """当前绑定的 accelerator(GTK 语法,如 `<Super>j`);未绑定返回空串。"""
        try:
            settings = Gio.Settings.new(GNOME_SCHEMA)
            if GNOME_PATH not in settings.get_strv("custom-keybindings"):
                return ""
            entry = Gio.Settings.new_with_path(RELOCATABLE_SCHEMA, GNOME_PATH)
            return entry.get_string("binding") or ""
        except Exception:
            return self._xfce_binding()

    # ---- write ----

    def bind(self, accelerator: str) -> tuple[bool, str]:
        """绑定快捷键。返回 (ok, 说明/错误)。"""
        if not accelerator:
            return False, "空快捷键"
        errors = []
        ok = False

        if self._gnome_bind(accelerator):
            ok = True
        else:
            errors.append("GNOME dconf 不可用")

        if self._has("xfconf-query"):
            if self._xfce_bind(accelerator):
                ok = True
            else:
                errors.append("xfconf-query 写入失败")

        return ok, "" if ok else "、".join(errors)

    def conflicts(self, accelerator: str) -> list[tuple[str, bool]]:
        """谁已经占了 accelerator。

        返回 [(占用者说明, 是否桌面保留)]。桌面保留键不能让出(Myna 会直接
        提示"换一个");别的用户自定义快捷键可以让出(Myna 弹「替换?」)。
        """
        found: list[tuple[str, bool]] = []
        if not accelerator:
            return found

        for schema, label in DESKTOP_SCHEMAS:
            try:
                settings = Gio.Settings.new(schema)
            except Exception:
                continue
            for key in settings.list_keys():
                if self._key_uses(settings, key, accelerator):
                    found.append((f"{label} · {key}", key.endswith("-static")))

        # 其它自定义快捷键(不含我们自己那一条)
        try:
            settings = Gio.Settings.new(GNOME_SCHEMA)
            for path in settings.get_strv("custom-keybindings"):
                if path == GNOME_PATH:
                    continue
                try:
                    entry = Gio.Settings.new_with_path(RELOCATABLE_SCHEMA, path)
                except Exception:
                    continue
                if entry.get_string("binding") == accelerator:
                    found.append((entry.get_string("name") or path.rstrip("/").split("/")[-1], False))
        except Exception:
            pass
        return found

    @staticmethod
    def _key_uses(settings: "Gio.Settings", key: str, accelerator: str) -> bool:
        try:
            value = settings.get_value(key)
        except Exception:
            return False
        try:
            if value.get_type_string() == "as":
                return accelerator in value.unpack()
            if value.get_type_string() == "s":
                return value.unpack() == accelerator
        except Exception:
            return False
        return False

    def clear(self) -> None:
        try:
            settings = Gio.Settings.new(GNOME_SCHEMA)
            paths = [p for p in settings.get_strv("custom-keybindings") if p != GNOME_PATH]
            settings.set_strv("custom-keybindings", paths)
            entry = Gio.Settings.new_with_path(RELOCATABLE_SCHEMA, GNOME_PATH)
            entry.reset("name")
            entry.reset("command")
            entry.reset("binding")
        except Exception as e:
            logger.debug("clearing GNOME shortcut failed: %s", e)
        self._xfce_clear()

    # ---- GNOME / dconf ----

    def _gnome_bind(self, accelerator: str) -> bool:
        try:
            entry = Gio.Settings.new_with_path(RELOCATABLE_SCHEMA, GNOME_PATH)
            entry.set_string("name", ENTRY_NAME)
            entry.set_string("command", TOGGLE_COMMAND)
            entry.set_string("binding", accelerator)
            Gio.Settings.sync()

            settings = Gio.Settings.new(GNOME_SCHEMA)
            paths = list(settings.get_strv("custom-keybindings"))
            # 只追加自己的那一条,不动别人的(Myna 同样如此)。
            if GNOME_PATH not in paths:
                paths.append(GNOME_PATH)
                settings.set_strv("custom-keybindings", paths)
                Gio.Settings.sync()
            return True
        except Exception as e:
            logger.warning("GNOME shortcut bind failed: %s", e)
            return False

    # ---- Xfce / xfconf ----

    @staticmethod
    def _has(tool: str) -> bool:
        from shutil import which

        return which(tool) is not None

    def _xfce_property(self, accelerator: str) -> str:
        return f"/commands/custom/{accelerator}"

    def _xfce_bind(self, accelerator: str) -> bool:
        try:
            subprocess.run(
                [
                    "xfconf-query", "-c", XFCE_CHANNEL,
                    "-p", self._xfce_property(accelerator),
                    "-s", TOGGLE_COMMAND, "--create", "-t", "string",
                ],
                check=True, timeout=5,
            )
            return True
        except Exception as e:
            logger.debug("xfce bind failed: %s", e)
            return False

    def _xfce_clear(self) -> None:
        binding = self._xfce_binding()
        if not binding:
            return
        try:
            subprocess.run(
                ["xfconf-query", "-c", XFCE_CHANNEL,
                 "-p", self._xfce_property(binding), "-r"],
                check=False, timeout=5,
            )
        except Exception:
            pass

    def _xfce_binding(self) -> str:
        if not self._has("xfconf-query"):
            return ""
        try:
            out = subprocess.run(
                ["xfconf-query", "-c", XFCE_CHANNEL, "-l"],
                capture_output=True, text=True, timeout=5,
            ).stdout
        except Exception:
            return ""
        for line in out.splitlines():
            if line.startswith("/commands/custom/"):
                accel = line[len("/commands/custom/"):]
                try:
                    value = subprocess.run(
                        ["xfconf-query", "-c", XFCE_CHANNEL, "-p", line],
                        capture_output=True, text=True, timeout=5,
                    ).stdout.strip()
                except Exception:
                    continue
                if value == TOGGLE_COMMAND:
                    return accel
        return ""
