"""libadwaita 的通用小工具 —— 让界面各处统一用 Adw 的默认组件。

老系统上的 libadwaita 可能缺新组件:

  * ``Adw.ButtonContent``(1.6+)—— 按钮里的「图标 + 文字」;
  * ``Adw.ShortcutLabel``(1.8+)—— 键帽;
  * ``Adw.WindowTitle``(1.6+)—— 标题栏里的标题/副标题。

这里统一做降级(拿不到就用最接近的 GTK 组件),调用方不必到处写 hasattr。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # type: ignore

logger = logging.getLogger(__name__)

try:
    gi.require_version("Adw", "1")
    from gi.repository import Adw  # type: ignore

    Adw.init()
    HAS_ADW = True
except Exception as e:  # pragma: no cover - 只在缺 libadwaita 时发生
    Adw = None  # type: ignore
    HAS_ADW = False
    logger.info("libadwaita unavailable (%s); using the plain GTK widgets", e)


def adw_has(name: str) -> bool:
    """当前 libadwaita 是否提供某个类。"""
    return HAS_ADW and hasattr(Adw, name)


def shortcut_widget(accelerator: str, empty_text: str = "未设置") -> Gtk.Widget:
    """键帽展示(Adw.ShortcutLabel;老 libadwaita 回落到自带 .keycap 样式)。"""
    if adw_has("ShortcutLabel"):
        widget = Adw.ShortcutLabel()
        widget.set_accelerator(accelerator or "")
        widget.set_disabled_text(empty_text)
        return widget
    label = Gtk.Label(label=accelerator or empty_text)
    label.add_css_class("keycap")
    return label


def accelerator_label(accelerator: str) -> str:
    """把 GTK accelerator 字符串(<Super>j)转成人类可读标签(Super+J 之类)。

    注意:`Gtk.accelerator_parse()` 的返回元素个数跟 PyGObject 版本有关 ——
    新版是 `(ok, keyval, mods)` 三元组,老版只有 `(keyval, mods)`。
    所以按「取最后两个」来解包,两种都能用;解析失败就原样返回。
    """
    if not accelerator:
        return ""
    try:
        parsed = Gtk.accelerator_parse(accelerator)
        keyval, mods = parsed[-2], parsed[-1]
    except Exception:
        return accelerator
    if not keyval and not mods:
        return accelerator
    return Gtk.accelerator_get_label(keyval, mods)


def set_shortcut_text(
    widget: Optional[Gtk.Widget], accelerator: str, empty_text: str = "未设置"
) -> None:
    """更新键帽显示。"""
    if widget is None:
        return
    if isinstance(widget, Gtk.Label):
        widget.set_text(accelerator or empty_text)
        return
    try:
        widget.set_accelerator(accelerator or "")
        widget.set_disabled_text(empty_text)
    except Exception:
        pass


def set_subtitle(row: Any, text: str) -> None:
    """写行的副标题。

    副标题按纯文本处理(内部转义),这样状态文案里出现 < > 也不会破坏排版。
    """
    if row is None:
        return
    try:
        row.set_use_markup(True)
    except Exception:
        pass
    row.set_subtitle(GLib.markup_escape_text(text))


def window_title(title: str, subtitle: str = "") -> Gtk.Widget:
    """标题栏里的标题(Adw.WindowTitle;旧版退回一个带 title 样式的标签)。"""
    if adw_has("WindowTitle"):
        widget = Adw.WindowTitle()
        widget.set_title(title)
        if subtitle:
            widget.set_subtitle(subtitle)
        return widget
    label = Gtk.Label(label=title)
    label.add_css_class("title")
    return label


def copy_text(text: str) -> bool:
    """把文本写进剪贴板(wayland / x11 都走 Gdk 的通用接口)。"""
    try:
        from gi.repository import Gdk  # type: ignore

        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(Gdk.ContentProvider.new_for_value(text))
        return True
    except Exception as e:
        logger.warning("clipboard write failed: %s", e)
        return False


def icon_name(*candidates: str) -> str:
    """挑一个当前图标主题里真实存在的图标名。

    主题收录的图标并不一致:``emblem-ok-symbolic`` / ``emblem-synchronizing-symbolic``
    只有 Yaru 有,Adwaita 没有。图标名查不到时 GTK 会画 ``image-missing``
    占位图(一个白方块),所以这里按顺序取第一个主题里存在的。
    """
    if not candidates:
        return ""
    try:
        from gi.repository import Gdk  # type: ignore

        display = Gdk.Display.get_default()
        if display is not None:
            theme = Gtk.IconTheme.get_for_display(display)
            for name in candidates:
                if theme.has_icon(name):
                    return name
    except Exception as e:
        logger.debug("icon lookup failed: %s", e)
    return candidates[0]
