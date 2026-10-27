"""系统托盘图标 —— 纯 Gio/D-Bus 实现的 StatusNotifierItem,不依赖 libayatana。

为什么不用 `AyatanaAppIndicator3`:

  * 它的 typelib 是 **GTK3** 版的(`gir1.2-ayatanaappindicator3-0.1`)。本应用
    是 GTK4 进程,`gi.require_version("AyatanaAppIndicator3", "0.1")` 会直接
    `ImportError: Requiring namespace 'Gtk' version '3.0', but '4.0' is already
    loaded`,连带把整个应用拖下水。Ubuntu 没有 GTK4 版的这个库。
  * 我们需要的只有两件事:导出一个 `org.kde.StatusNotifierItem` 对象,再向
    `org.kde.StatusNotifierWatcher` 报个到。这两件 `Gio` 原生就能做,还能顺带
    精确控制 IconName / 菜单项。

契约(GNOME 侧由 ubuntu-appindicators 扩展实现):

  * `org.kde.StatusNotifierItem` 在 `/StatusNotifierItem` 上导出;
  * `com.canonical.dbusmenu` 在 `/MenuBar` 上导出,面板通过 GetLayout /
    GetGroupProperties 拉菜单,通过 Event("clicked") 回调;
  * 注册方式用 **对象路径**(扩展会把它和调用方的 unique name 拼起来),
    这样我们不需要额外 own 一个 well-known bus name。

降级策略(照 CLAUDE.md 的要求,**任何一步失败都静默**):

  * 没有 StatusNotifierWatcher(没装 AppIndicator 扩展)→ 不注册,不报错;
  * D-Bus 不可用 / 导出的对象被拒 → `available()` 为 False,主流程照旧。

图标用 **Adwaita 自带的单色符号化图标**(`audio-input-microphone-symbolic`),
不用应用自己的彩色 logo:顶栏只有 16~24px,彩色图缩下去只会糊成一团,而且
不会跟随主题前景色(深色主题上白底logo很突兀)。录音中切 `media-record-symbolic`。
两者都是 Adwaita / Yaru / Yaru-dark 的标准图标;查不到时退回
`microphone-sensitivity-*-symbolic`,再不齐就交给面板的 generic fallback。
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # type: ignore

from doubao_input.i18n import _

logger = logging.getLogger(__name__)

#: SNI 对象路径(扩展的 DEFAULT_ITEM_OBJECT_PATH)
ITEM_PATH = "/StatusNotifierItem"

#: 菜单对象路径(名字随意,只要 Menu 属性指过来)
MENU_PATH = "/MenuBar"

WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"

#: 托盘图标 —— 用 Adwaita 自带的**单色符号化**图标,不用应用自己的彩色 logo。
#:
#: 顶栏只有 16~24px,彩色 logo 在这个尺寸下就是一团糊;而且面板上的
#: 图标一般都跟着主题前景色走,单色才不会在深色/浅色主题之间突兀。
#: `audio-input-microphone-symbolic` 是 Adwaita / Yaru / Yaru-dark 都有的
#: 标准麦克风字形(-symbolic 后缀让 GTK 按 currentColor 重着色)。
ICON_NAME = "audio-input-microphone-symbolic"

#: 录音中换成实心红点(同样是 Adwaita 自带)。
ATTENTION_ICON = "media-record-symbolic"

#: ICON_NAME 找不到时的候选(极简主题可能裁掉某些图标)。
_ICON_FALLBACKS = (
    "microphone-sensitivity-high-symbolic",
    "microphone-sensitivity-medium-symbolic",
    "audio-input-microphone",
)

STATUS_ACTIVE = "Active"
STATUS_ATTENTION = "NeedsAttention"

# --------------------------------------------------------------------------
# D-Bus 接口描述
# --------------------------------------------------------------------------

_SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconAccessibleDesc" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconAccessibleDesc" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconAccessibleDesc" type="s" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewStatus"><arg name="status" type="s" direction="out"/></signal>
  </interface>
</node>
"""

_MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id" type="i" direction="in"/>
      <arg name="name" type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg name="events" type="a(isvu)" direction="in"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="updatesNeeded" type="ai" direction="out"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg name="updatedProps" type="a(ia{sv})" direction="out"/>
      <arg name="removedProps" type="a(ias)" direction="out"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u" direction="out"/>
      <arg name="parent" type="i" direction="out"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg name="id" type="i" direction="out"/>
      <arg name="timestamp" type="u" direction="out"/>
    </signal>
  </interface>
</node>
"""

#: 菜单项 id(0 是根,面板从根往下读)
_ROOT, _SHOW, _MIC, _SEPARATOR, _QUIT = 0, 1, 2, 3, 4


def _s(text: str) -> GLib.Variant:
    return GLib.Variant("s", text)


def _find_icon() -> str:
    """选一个面板真能查到的单色图标名。

    注意:托盘**不再**用应用图标(`doubao-input`)—— 那是张 256px 的彩色
    logo,缩到顶栏的 16~24px 只会糊成一团,也不会跟随主题前景色。
    """
    try:
        import gi as _gi

        _gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk  # noqa: PLC0415

        theme = Gtk.IconTheme.new()
        for candidate in (ICON_NAME, *_ICON_FALLBACKS):
            if theme.has_icon(candidate):
                return candidate
        logger.debug("tray: none of %s found in the icon theme", _ICON_FALLBACKS)
    except Exception as e:  # 没有 Gtk / 没有 display 都不该影响托盘
        logger.debug("tray: icon theme lookup skipped (%s)", e)

    # 查不到就照样用主名字:面板侧还有 generic fallback。
    return ICON_NAME


class Tray:
    """StatusNotifierItem 托盘。构造失败不抛异常,`available` 说明结果。

    回调都在 GTK 主线程上调用(面板的 D-Bus 方法调用由主循环派发)。
    """

    def __init__(
        self,
        on_show: Callable[[], None],
        on_check_mic: Callable[[], None],
        on_quit: Callable[[], None],
        on_registered: Optional[Callable[[bool], None]] = None,
    ) -> None:
        self._on_show = on_show
        self._on_check_mic = on_check_mic
        self._on_quit = on_quit
        self._on_registered = on_registered
        self._conn: Optional[Gio.DBusConnection] = None
        self._sni_ids: list[int] = []
        self._menu_ids: list[int] = []
        self._registered = False
        self._status = STATUS_ACTIVE
        self._revision = 1
        self._icon = _find_icon()
        self._title = _("Doubao Voice Input")
        self._build()

    # ---- public ----

    @property
    def available(self) -> bool:
        """对象导出成功(能不能真的显示,还取决于桌面有没有 SNI 宿主)。"""
        return self._registered

    def status(self) -> str:
        """给诊断页看的一句话。"""
        if self._registered:
            return _("shown in the system tray")
        return _("not available (the desktop has no StatusNotifierItem host)")

    def set_recording(self, recording: bool) -> None:
        """录音中把状态切到 NeedsAttention(面板会换 Attention 图标)。"""
        status = STATUS_ATTENTION if recording else STATUS_ACTIVE
        if status == self._status:
            return
        self._status = status
        self._emit(_SNI_XML_NAME, "NewStatus", GLib.Variant("(s)", (status,)))

    def retranslate(self) -> None:
        """界面语言变了 —— 重建菜单文案(面板会重新拉一次布局)。"""
        self._title = _("Doubao Voice Input")
        self._revision += 1
        self._emit(_SNI_XML_NAME, "NewTitle", None)
        self._emit(_MENU_XML_NAME, "LayoutUpdated",
                   GLib.Variant("(ui)", (self._revision, _ROOT)))

    def close(self) -> None:
        for object_id in self._menu_ids + self._sni_ids:
            try:
                self._conn.unregister_object(object_id)
            except Exception:
                pass
        self._menu_ids.clear()
        self._sni_ids.clear()
        self._registered = False
        self._conn = None

    # ---- 构建 ----

    def _build(self) -> None:
        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as e:
            logger.info("tray: no session bus (%s)", e)
            return

        sni_info = Gio.DBusNodeInfo.new_for_xml(_SNI_XML).interfaces[0]
        menu_info = Gio.DBusNodeInfo.new_for_xml(_MENU_XML).interfaces[0]

        try:
            self._sni_ids.append(self._conn.register_object(
                ITEM_PATH, sni_info, self._on_sni_call, self._on_sni_get, None
            ))
            self._menu_ids.append(self._conn.register_object(
                MENU_PATH, menu_info, self._on_menu_call, self._on_menu_get, None
            ))
        except Exception as e:
            logger.info("tray: cannot export D-Bus objects (%s)", e)
            return

        self._register_with_watcher()

    def _register_with_watcher(self) -> None:
        """向 StatusNotifierWatcher 报到。没有 watcher(没装扩展)就静默放弃。"""

        def done(connection, result, _user_data=None) -> None:
            try:
                connection.call_finish(result)
            except GLib.Error as e:
                logger.info(
                    "tray: no StatusNotifierItem host, staying hidden (%s)",
                    e.message,
                )
                self._notify_registered(False)
                return
            self._registered = True
            logger.info("tray: registered with StatusNotifierWatcher (icon=%s)", self._icon)
            self._notify_registered(True)

        try:
            self._conn.call(
                WATCHER_NAME,
                WATCHER_PATH,
                WATCHER_NAME,
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (ITEM_PATH,)),
                None,
                Gio.DBusCallFlags.NONE,
                3000,
                None,
                done,
                None,
            )
        except Exception as e:
            logger.info("tray: watcher call failed (%s)", e)
            self._notify_registered(False)

    def _notify_registered(self, registered: bool) -> None:
        """告诉主程序托盘到底能不能用(决定关窗是隐藏还是退出)。"""
        if self._on_registered is None:
            return
        try:
            self._on_registered(registered)
        except Exception:
            logger.exception("tray: on_registered callback failed")

    # ---- SNI:属性 / 方法 ----

    def _sni_props(self) -> dict[str, GLib.Variant]:
        return {
            "Category": _s("ApplicationStatus"),
            "Id": _s("doubao-input"),
            "Title": _s(self._title),
            "Status": _s(self._status),
            "WindowId": GLib.Variant("i", 0),
            "IconThemePath": _s(""),
            "IconName": _s(self._icon),
            "IconAccessibleDesc": _s(self._title),
            "OverlayIconName": _s(""),
            "OverlayIconAccessibleDesc": _s(""),
            "AttentionIconName": _s(ATTENTION_ICON),
            "AttentionIconAccessibleDesc": _s(_("Dictating")),
            "AttentionMovieName": _s(""),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
        }

    def _on_sni_get(self, _conn, _sender, _path, _iface, prop):
        return self._sni_props().get(prop)

    def _on_sni_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        try:
            if method == "Activate":
                self._on_show()
            elif method == "SecondaryActivate":
                self._on_show()
            elif method == "ContextMenu":
                self._on_show()
            # Scroll 忽略
        except Exception:
            logger.exception("tray: %s handler failed", method)
        finally:
            invocation.return_value(None)

    # ---- DBusMenu ----

    def _items(self) -> dict[int, dict[str, GLib.Variant]]:
        """每次现算:文案随语言变化,没必要缓存。"""
        return {
            _ROOT: {
                "children-display": _s("submenu"),
                "visible": GLib.Variant("b", True),
            },
            _SHOW: {
                "label": _s(_("Show Control Window")),
                "type": _s("standard"),
                "enabled": GLib.Variant("b", True),
                "visible": GLib.Variant("b", True),
            },
            _MIC: {
                "label": _s(_("Check Microphone")),
                "type": _s("standard"),
                "enabled": GLib.Variant("b", True),
                "visible": GLib.Variant("b", True),
            },
            _SEPARATOR: {
                "label": _s(""),
                "type": _s("separator"),
                "enabled": GLib.Variant("b", True),
                "visible": GLib.Variant("b", True),
            },
            _QUIT: {
                "label": _s(_("Quit")),
                "type": _s("standard"),
                "enabled": GLib.Variant("b", True),
                "visible": GLib.Variant("b", True),
            },
        }

    @staticmethod
    def _children(item_id: int) -> list[int]:
        return [_SHOW, _MIC, _SEPARATOR, _QUIT] if item_id == _ROOT else []

    def _layout(self, item_id: int = _ROOT, depth: int = -1) -> GLib.Variant:
        """拼一个 (ia{sv}av) —— 菜单项的递归结构。"""
        props = self._items().get(item_id, {})
        children = self._children(item_id)
        kids = []
        if depth != 0:
            kids = [self._layout(child, depth - 1) for child in children]
        return GLib.Variant("(ia{sv}av)", (item_id, props, kids))

    def _menu_props(self) -> dict[str, GLib.Variant]:
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": _s("ltr"),
            "Status": _s("normal"),
            "IconThemePath": GLib.Variant("as", []),
        }

    def _on_menu_get(self, _conn, _sender, _path, _iface, prop):
        return self._menu_props().get(prop)

    def _on_menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        try:
            args = params.unpack()
            if method == "GetLayout":
                invocation.return_value(GLib.Variant.new_tuple(
                    GLib.Variant("u", self._revision), self._layout()
                ))
                return
            if method == "GetGroupProperties":
                ids = args[0] if args else []
                items = self._items()
                out = [(i, items[i]) for i in ids if i in items]
                invocation.return_value(GLib.Variant("(a(ia{sv}))", (out,)))
                return
            if method == "GetProperty":
                item_id, name = args[0], args[1]
                value = self._items().get(item_id, {}).get(name, _s(""))
                invocation.return_value(GLib.Variant("(v)", (value,)))
                return
            if method == "AboutToShow":
                invocation.return_value(GLib.Variant("(b)", (False,)))
                return
            if method == "Event":
                self._on_menu_event(args[0], args[1])
                invocation.return_value(None)
                return
            if method == "EventGroup":
                invocation.return_value(GLib.Variant("(ai)", ([],)))
                return
            if method == "AboutToShowGroup":
                invocation.return_value(GLib.Variant("(aiai)", ([], [])))
                return
            invocation.return_value(None)
        except Exception:
            logger.exception("tray: menu method %s failed", method)
            try:
                invocation.return_value(None)
            except Exception:
                pass

    def _on_menu_event(self, item_id: int, event_id: str) -> None:
        if event_id != "clicked":
            return
        if item_id == _SHOW:
            self._on_show()
        elif item_id == _MIC:
            self._on_check_mic()
        elif item_id == _QUIT:
            self._on_quit()

    # ---- 信号 ----

    def _emit(self, interface: str, signal: str, parameters) -> None:
        """通过 Properties 自省让面板刷新;没有 connection 就静默。"""
        if self._conn is None:
            return
        try:
            self._conn.emit_signal(None, ITEM_PATH if interface == _SNI_XML_NAME
                                   else MENU_PATH, interface, signal, parameters)
        except Exception as e:
            logger.debug("tray: emit %s failed (%s)", signal, e)


#: 接口名常量(emit_signal 用)
_SNI_XML_NAME = "org.kde.StatusNotifierItem"
_MENU_XML_NAME = "com.canonical.dbusmenu"
