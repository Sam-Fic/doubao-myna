"""按键捕获 —— 设置窗口和首次运行向导共用。

规则与 Myna 的 `shortcut_ui.rs` 一致:

  * **Escape**(不带修饰键)= 取消,什么都不改;
  * 只有 **Ctrl/Alt/Super + 另一个键**,或单独的 **F1–F35 / XF86 媒体键** 才被采纳;
  * **裸字母一律忽略** —— 否则会把打字键抢走。

界面走 libadwaita 的默认样式:Adw.Window + ToolbarView + HeaderBar,
内容用 Adw.StatusPage(大图标 + 提示 + 说明)。取消靠标题栏右上角的 X 或 Esc。
没有 libadwaita 的老系统上退回纯 GTK4 窗口(那边没有 X,保留「取消」按钮)。
"""

from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk  # type: ignore

from doubao_input.i18n import _
from doubao_input.ui.adw_compat import (
    HAS_ADW as _HAS_ADW,
    Adw,
    window_title as _window_title,
)

PROMPT = "Press a new shortcut…"
HINT = "Use Ctrl / Alt / Super plus another key, or a function key on its own. Esc cancels."


def start_capture(
    parent: Optional[Gtk.Window],
    on_result: Callable[[str], None],
    prompt: Optional[str] = None,
    hint: Optional[str] = None,
) -> None:
    """弹一个模态小窗等用户按键;`on_result(accelerator)` 或什么都不调(取消)。"""
    # 默认文案在这里翻译,不在模块级翻译 —— 常量在 import 时就固化,
    # 那时 i18n.init() 还没跑。
    prompt = _(PROMPT) if prompt is None else prompt
    hint = _(HINT) if hint is None else hint
    if _HAS_ADW:
        win = _adw_window(parent, prompt, hint, on_result)
    else:
        win = _gtk_window(parent, prompt, hint, on_result)

    controller = Gtk.EventControllerKey()
    controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    controller.connect("key-pressed", _on_key, win, on_result)
    win.add_controller(controller)
    win.present()


def _adw_window(
    parent: Optional[Gtk.Window],
    prompt: str,
    hint: str,
    on_result: Callable[[str], None],
) -> Gtk.Window:
    win = Adw.Window()
    if parent is not None:
        win.set_transient_for(parent)
    win.set_modal(True)
    win.set_title(_("Set Shortcut"))
    win.set_default_size(420, 320)

    toolbar = Adw.ToolbarView()

    header = Adw.HeaderBar()
    header.set_title_widget(_window_title(_("Set Shortcut")))
    # 右上角本来就有 X(关闭),不再放「取消」按钮;Esc 也能取消。
    toolbar.add_top_bar(header)

    page = Adw.StatusPage()
    page.set_icon_name("input-keyboard-symbolic")
    page.set_title(prompt)
    page.set_description(hint)
    toolbar.set_content(page)

    win.set_content(toolbar)
    return win


def _gtk_window(
    parent: Optional[Gtk.Window],
    prompt: str,
    hint: str,
    on_result: Callable[[str], None],
) -> Gtk.Window:
    win = Gtk.Window()
    if parent is not None:
        win.set_transient_for(parent)
    win.set_modal(True)
    win.set_title(_("Set Shortcut"))
    win.set_default_size(420, 170)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(24)
    box.set_margin_bottom(24)
    box.set_margin_start(24)
    box.set_margin_end(24)

    box.append(Gtk.Label(label=prompt))
    hint_label = Gtk.Label(label=hint)
    hint_label.add_css_class("dim-label")
    hint_label.set_wrap(True)
    box.append(hint_label)
    cancel = Gtk.Button(label=_("Cancel"))
    cancel.connect("clicked", lambda *_: win.close())
    box.append(cancel)
    win.set_child(box)
    return win


def _on_key(_controller, keyval: int, _keycode: int, state, win, on_result) -> bool:
    mods = state & (
        Gdk.ModifierType.CONTROL_MASK
        | Gdk.ModifierType.ALT_MASK
        | Gdk.ModifierType.SUPER_MASK
    )
    if keyval == Gdk.KEY_Escape and not mods:
        win.close()
        return True
    if not mods and not _is_function_key(keyval):
        return True  # 裸字母不收

    accelerator = Gtk.accelerator_name(keyval, mods)
    win.close()
    if on_result is not None:
        on_result(accelerator)
    return True


def _is_function_key(keyval: int) -> bool:
    if Gdk.KEY_F1 <= keyval <= Gdk.KEY_F35:
        return True
    return 0x1008FF00 <= keyval <= 0x1008FFFF  # XF86 媒体键
