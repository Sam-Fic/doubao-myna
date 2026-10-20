"""`com.canonical.Myna.Dictation` 发布端(PyGObject/Gio,零新增依赖)。

只发布"状态 + 电平",不发布识别文本(契约 C3),界面像素全部归 `myna-hud`。

为什么用 PropertiesChanged 而不是自定义信号:契约 §Confinement 说明
被 snap 严格限制的服务只能广播标准 Properties 信号;这里同样遵守,
于是同一个渲染器既能接 Myna 自己的守护进程,也能接本项目的 Python 端。

线程规则:所有 D-Bus 调用必须在 GTK 主线程发生(本项目由 bridge 保证;
电平值本身可以从音频线程写入,见 bridge.push_level)。
"""

from __future__ import annotations

import logging
import warnings
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gio  # type: ignore

from doubao_input.hud.wire import (
    BUS_NAME,
    INTROSPECTION_XML,
    INTERFACE,
    OBJECT_PATH,
    PROPERTIES_INTERFACE,
    IDLE,
)

logger = logging.getLogger(__name__)


class DictationPublisher:
    """拥有 `com.canonical.Myna.Dictation` 名字并推送属性变化。"""

    def __init__(
        self,
        on_start: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        on_toggle: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_toggle = on_toggle
        self._connection: Optional[Gio.DBusConnection] = None
        self._owner_id = 0
        self._registration_ids: list[int] = []
        self._clients: set[str] = set()
        # 属性缓存:渲染器每次 PropertiesChanged 都会回读 GetAll,
        # 因此这里就是它看到的全貌。
        self._properties = {
            "State": GLib.Variant("s", IDLE),
            "StatusMessage": GLib.Variant("s", ""),
            "AudioRms": GLib.Variant("d", 0.0),
            "AudioPeak": GLib.Variant("d", 0.0),
            "HudStyle": GLib.Variant("s", ""),
        }

    # ---- lifecycle ----

    @property
    def started(self) -> bool:
        return self._owner_id != 0

    @property
    def client_count(self) -> int:
        """已注册的渲染器数量(myna-hud 起来后会 RegisterClient)。"""
        return len(self._clients)

    def start(self) -> bool:
        if self.started:
            return True
        try:
            self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as e:  # 没有会话总线就降级,不致命
            logger.warning("D-Bus session bus unavailable: %s", e)
            return False

        node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        for info in node.interfaces:
            # register_object 的旧签名被标记 deprecated,但
            # register_object_with_closures 需要手工构造 GObject.Closure,
            # 在 PyGObject 下不可靠;这里显式屏蔽该告警即可。
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                rid = self._connection.register_object(
                    OBJECT_PATH, info, self._on_method_call, None, None
                )
            self._registration_ids.append(rid)

        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            None,
            self._on_name_acquired,
            self._on_name_lost,
        )
        logger.info("publishing %s (owner=%d)", BUS_NAME, self._owner_id)
        return True

    def stop(self) -> None:
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0
        if self._connection is not None:
            for rid in self._registration_ids:
                self._connection.unregister_object(rid)
            self._registration_ids = []
        self._connection = None
        self._clients.clear()

    # ---- publishing ----

    def set_state(self, state: str, status_message: str) -> None:
        """发布一次状态迁移。相同取值不重复广播(契约 C2 的去重)。"""
        changed: dict[str, GLib.Variant] = {}
        if self._properties["State"].get_string() != state:
            changed["State"] = GLib.Variant("s", state)
        if self._properties["StatusMessage"].get_string() != status_message:
            changed["StatusMessage"] = GLib.Variant("s", status_message)
        if not changed:
            return
        self._properties.update(changed)
        self._emit(changed)

    def push_level(self, rms: float, peak: float) -> None:
        """发布一次电平。**从不去重**:渲染器靠到达时间判断流是否停滞(R16a)。"""
        self._properties["AudioRms"] = GLib.Variant("d", _clamp(rms))
        self._properties["AudioPeak"] = GLib.Variant("d", _clamp(peak))
        self._emit(
            {
                "AudioRms": self._properties["AudioRms"],
                "AudioPeak": self._properties["AudioPeak"],
            }
        )

    def set_hud_style(self, nick: str) -> None:
        if self._properties["HudStyle"].get_string() == nick:
            return
        self._properties["HudStyle"] = GLib.Variant("s", nick)
        self._emit({"HudStyle": self._properties["HudStyle"]})

    def _emit(self, changed: dict[str, GLib.Variant]) -> None:
        if self._connection is None:
            return
        self._connection.emit_signal(
            None,
            OBJECT_PATH,
            PROPERTIES_INTERFACE,
            "PropertiesChanged",
            GLib.Variant("(sa{sv}as)", (INTERFACE, changed, [])),
        )

    # ---- D-Bus server ----

    def _on_name_acquired(self, _connection, name: str) -> None:
        logger.info("owned D-Bus name %s", name)

    def _on_name_lost(self, _connection, name: str) -> None:
        # 另一个发布端(比如真的 myna-desktop)先占了名字。
        if self._owner_id:
            logger.warning("lost D-Bus name %s; another publisher owns it", name)
            self._owner_id = 0

    def _on_method_call(
        self,
        _connection,
        sender: str,
        _object_path: str,
        interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation,
    ) -> None:
        if interface_name == PROPERTIES_INTERFACE:
            self._on_properties_call(method_name, parameters, invocation)
            return
        if interface_name != INTERFACE:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownInterface", interface_name
            )
            return

        if method_name == "Start":
            ok, reason = self._start_session()
            invocation.return_value(GLib.Variant("(bs)", (ok, reason)))
        elif method_name == "Stop":
            if self._on_stop:
                self._on_stop()
            invocation.return_value(None)
        elif method_name == "Toggle":
            if self._on_toggle:
                self._on_toggle()
            invocation.return_value(None)
        elif method_name == "RegisterClient":
            self._clients.add(sender)
            logger.info("HUD client registered (%d total)", len(self._clients))
            invocation.return_value(GLib.Variant("(u)", (len(self._clients),)))
        elif method_name == "UnregisterClient":
            self._clients.discard(sender)
            invocation.return_value(GLib.Variant("(u)", (len(self._clients),)))
        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod", method_name
            )

    def _on_properties_call(self, method_name, parameters, invocation) -> None:
        if method_name == "Get":
            iface, name = parameters.unpack()
            value = self._properties.get(name) if iface == INTERFACE else None
            if value is None:
                invocation.return_dbus_error(
                    "org.freedesktop.DBus.Error.InvalidArgs", f"{iface}.{name}"
                )
                return
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method_name == "GetAll":
            (iface,) = parameters.unpack()
            props = self._properties if iface == INTERFACE else {}
            invocation.return_value(GLib.Variant("(a{sv})", (props,)))
        elif method_name == "Set":
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.PropertyReadOnly", "read-only"
            )
        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod", method_name
            )

    def _start_session(self) -> tuple[bool, str]:
        if self._on_start is None:
            return False, "no trigger attached"
        self._on_start()
        return True, ""


def _clamp(value: float) -> float:
    """契约 E2:电平取值域是 [0.0, 1.0]。"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if value != value:  # NaN
        return 0.0
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value
