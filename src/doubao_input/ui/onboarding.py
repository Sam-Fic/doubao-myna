"""首次运行向导 —— 对齐 Myna 的 onboarding(Welcome → 组件 → 快捷键)。

后端不同,步骤也相应调整:

  1. **欢迎** —— 说明"按住右 Ctrl 说话、松开就粘贴",以及"凭证只存本地"。
  2. **登录豆包** —— 没登录不让继续(WebKit 登录窗口由 app 提供)。
  3. **快捷键** —— 桌面快捷键(共用 control_window 的捕获逻辑)+ 物理键说明。
  4. **Myna 胶囊(可选)** —— 显示当前状态;没装就给一行安装命令和复制按钮。

组件同样交给 libadwaita 的默认值:
Adw.Window + ToolbarView + HeaderBar(上一步 / 下一步放标题栏),
欢迎页用 Adw.StatusPage,提示用 Adw.Toast,键帽用 Adw.ShortcutLabel。

向导只出现一次(`settings.json` 的 `onboarding_done`),之后可以从设置窗口的
主菜单「运行设置向导…」再打开。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
try:
    gi.require_version("Adw", "1")
    from gi.repository import Adw  # type: ignore

    Adw.init()
    _HAS_ADW = True
except Exception:  # pragma: no cover
    Adw = None  # type: ignore
    _HAS_ADW = False

from gi.repository import GLib, Gtk  # type: ignore

from doubao_input.doubao.app_state import AppState, LoginStatus
from doubao_input.ui.shortcut_capture import start_capture

logger = logging.getLogger(__name__)

#: hicolor 主题里的图标名(与设置窗口一致)。
_ICON_NAME = "doubao-input"


def available() -> bool:
    """libadwaita 是否可用(不可用时向导静默跳过)。"""
    return _HAS_ADW


BUILD_HINT = "bash scripts/build-myna-hud.sh"


# ---- libadwaita 小工具 ----


def _adw_has(name: str) -> bool:
    return _HAS_ADW and hasattr(Adw, name)


def _button_content(icon_name: str, label: str) -> Gtk.Widget:
    """按钮内容:图标 + 文字(Adw.ButtonContent,libadwaita ≥ 1.6)。"""
    if _adw_has("ButtonContent"):
        content = Adw.ButtonContent()
        content.set_icon_name(icon_name)
        content.set_label(label)
        return content
    return Gtk.Label(label=label)


def _set_button_content_label(content: Optional[Gtk.Widget], label: str) -> None:
    if content is None:
        return
    if _adw_has("ButtonContent") and isinstance(content, Adw.ButtonContent):
        content.set_label(label)
    elif isinstance(content, Gtk.Label):
        content.set_text(label)


def _shortcut_widget(accelerator: str, empty_text: str = "未设置") -> Gtk.Widget:
    """键帽展示(Adw.ShortcutLabel;老 libadwaita 回落到自带 .keycap 样式)。"""
    if _adw_has("ShortcutLabel"):
        widget = Adw.ShortcutLabel()
        widget.set_accelerator(accelerator or "")
        widget.set_disabled_text(empty_text)
        return widget
    label = Gtk.Label(label=accelerator or empty_text)
    label.add_css_class("keycap")
    return label


def _set_shortcut_text(
    widget: Optional[Gtk.Widget], accelerator: str, empty_text: str = "未设置"
) -> None:
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


def _set_subtitle(row: Any, text: str) -> None:
    """写行的副标题(按纯文本处理,内部转义)。"""
    if row is None:
        return
    try:
        row.set_use_markup(True)
    except Exception:
        pass
    row.set_subtitle(GLib.markup_escape_text(text))


class OnboardingWindow:
    """4 步首次运行向导(Adw)。"""

    def __init__(
        self,
        app_state: AppState,
        on_login: Callable[[], None],
        on_shortcut_set: Callable[[str], tuple[bool, str]],
        on_shortcut_conflicts: Optional[Callable[[str], Any]] = None,
        desktop_shortcut: Optional[Callable[[], str]] = None,
        hud_status: Optional[Callable[[], str]] = None,
        hud_enabled: bool = False,
        on_finish: Optional[Callable[[], None]] = None,
        parent: Optional[Gtk.Window] = None,
    ) -> None:
        self._app_state = app_state
        self._on_login = on_login
        self._on_shortcut_set = on_shortcut_set
        self._on_shortcut_conflicts = on_shortcut_conflicts
        self._desktop_shortcut = desktop_shortcut or (lambda: "")
        self._hud_status = hud_status or (lambda: "未启用")
        self._hud_enabled = hud_enabled
        self._on_finish = on_finish
        self._window: Optional[Gtk.Window] = None
        self._stack: Optional[Gtk.Stack] = None
        self._back_button: Optional[Gtk.Button] = None
        self._next_button: Optional[Gtk.Button] = None
        self._next_button_content: Optional[Gtk.Widget] = None
        self._shortcut_widget: Optional[Gtk.Widget] = None
        self._clear_button: Optional[Gtk.Button] = None
        self._login_row = None
        self._login_button: Optional[Gtk.Button] = None
        self._login_button_content: Optional[Gtk.Widget] = None
        self._hud_status_row = None
        self._toast_overlay = None
        self._parent = parent

    # ---- public ----

    def show(self) -> None:
        if not _HAS_ADW:
            logger.info("libadwaita 不可用,跳过向导")
            return
        self._ensure_window()
        if self._window is not None:
            self._window.present()
        self.refresh()

    def refresh(self) -> None:
        """登录态 / 胶囊状态变化后刷新当前页。"""
        if self._shortcut_widget is not None:
            _set_shortcut_text(self._shortcut_widget, self._desktop_shortcut() or "")
        if self._clear_button is not None:
            self._clear_button.set_sensitive(bool(self._desktop_shortcut()))
        self._refresh_login_row()
        if self._hud_status_row is not None:
            _set_subtitle(self._hud_status_row, self._hud_status())
        self._update_buttons()

    # ---- internals ----

    def _ensure_window(self) -> None:
        if self._window is not None:
            return
        win = Adw.Window()
        if self._parent is not None:
            win.set_transient_for(self._parent)
        win.set_title("设置豆包语音输入法")
        win.set_default_size(560, 560)

        toolbar = Adw.ToolbarView()

        header = Adw.HeaderBar()
        header.set_title("设置豆包语音输入法")
        self._back_button = Gtk.Button()
        self._back_button.add_css_class("flat")
        self._back_button.set_child(_button_content("go-previous-symbolic", "上一步"))
        self._back_button.connect("clicked", lambda *_: self._go(-1))
        header.pack_start(self._back_button)
        self._next_button = Gtk.Button()
        self._next_button.add_css_class("suggested-action")
        self._next_button_content = _button_content("go-next-symbolic", "下一步")
        self._next_button.set_child(self._next_button_content)
        self._next_button.connect("clicked", lambda *_: self._go(1))
        header.pack_end(self._next_button)
        toolbar.add_top_bar(header)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.add_named(self._build_welcome(), "welcome")
        self._stack.add_named(self._build_login(), "login")
        self._stack.add_named(self._build_shortcut(), "shortcut")
        self._stack.add_named(self._build_hud(), "hud")

        # Toast:操作结果(快捷键设好了没)不该只写在日志里。
        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._stack)
        toolbar.set_content(self._toast_overlay)

        win.set_content(toolbar)

        self._stack.connect("notify::visible-child", lambda *_: self._update_buttons())
        self._app_state.connect("login-status-changed", lambda *_: self.refresh())
        self._window = win
        self._update_buttons()

    # ---- pages ----

    def _build_welcome(self) -> Gtk.Widget:
        """欢迎页:Adw.StatusPage(Adw 自带的「大图标 + 标题 + 说明」)。"""
        page = Adw.StatusPage()
        page.set_icon_name(_ICON_NAME)
        page.set_title("欢迎使用豆包语音输入法")
        page.set_description(
            "在任意输入框聚焦，<b>按住右 Ctrl</b> 说话，松开就把识别结果粘贴进去。\n"
            "识别由豆包的网页服务完成；登录凭证只保存在本机，不会发给第三方。"
        )
        return page

    def _build_login(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="登录豆包",
            description="第一次使用需要登录一次，之后凭证会复用。"
            "点「登录豆包」会打开一个网页窗口，在里面正常登录即可。",
        )
        page.add(group)

        self._login_row = Adw.ActionRow(title="登录状态", subtitle="检测中…")
        self._login_button = Gtk.Button()
        self._login_button.set_valign(Gtk.Align.CENTER)
        self._login_button.add_css_class("suggested-action")
        self._login_button_content = _button_content("system-users-symbolic", "登录豆包")
        self._login_button.set_child(self._login_button_content)
        self._login_button.connect("clicked", lambda *_: self._on_login())
        self._login_row.add_suffix(self._login_button)
        self._login_row.set_activatable_widget(self._login_button)
        group.add(self._login_row)
        return page

    def _build_shortcut(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="快捷键",
            # 注意 < > 在 Adw 的 description 里是 Pango 标记，必须转义。
            description="桌面快捷键支持 &lt;Super&gt;j 这类组合键；物理键则由 evdev 直接监听。",
        )
        page.add(group)

        row = Adw.ActionRow(
            title="桌面快捷键",
            subtitle="写进桌面的自定义快捷键，命令是 D-Bus Toggle",
        )
        self._shortcut_widget = _shortcut_widget(self._desktop_shortcut() or "")
        self._shortcut_widget.set_valign(Gtk.Align.CENTER)
        button = Gtk.Button()
        button.set_valign(Gtk.Align.CENTER)
        button.set_child(_button_content("preferences-desktop-keyboard-shortcuts-symbolic", "设置"))
        button.connect("clicked", lambda *_: self._capture())
        self._clear_button = Gtk.Button()
        self._clear_button.set_valign(Gtk.Align.CENTER)
        self._clear_button.add_css_class("flat")
        self._clear_button.set_child(_button_content("edit-clear-all-symbolic", "清除"))
        self._clear_button.set_sensitive(bool(self._desktop_shortcut()))
        self._clear_button.connect("clicked", lambda *_: self._clear_shortcut())
        row.add_suffix(self._shortcut_widget)
        row.add_suffix(self._clear_button)
        row.add_suffix(button)
        row.set_activatable_widget(button)
        group.add(row)

        group.add(
            Adw.ActionRow(
                title="物理键",
                subtitle="默认右 Ctrl，可在设置窗口的「输入」页更换",
            )
        )
        group.add(
            Adw.ActionRow(
                title="触发方式",
                subtitle="默认按住说话；想要 Myna 的「按一下开始/再按一下结束」可在设置里切换",
            )
        )
        return page

    def _build_hud(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="悬浮胶囊",
            description="可选项：用 Myna 的 myna-hud 绘制录音指示器。",
        )
        page.add(group)

        self._hud_status_row = Adw.ActionRow(title="当前状态", subtitle=self._hud_status())
        group.add(self._hud_status_row)

        install_row = Adw.ActionRow(
            title="安装命令",
            subtitle="需要 cargo + libgtk-4-dev + libadwaita-1-dev",
        )
        copy = Gtk.Button()
        copy.set_valign(Gtk.Align.CENTER)
        copy.set_child(_button_content("edit-copy-symbolic", "复制"))
        copy.connect("clicked", lambda *_: self._copy_command())
        install_row.add_suffix(copy)
        install_row.set_activatable_widget(copy)
        group.add(install_row)

        group.add(
            Adw.ActionRow(
                title="不装也能用",
                subtitle="会退回内置的悬浮窗；想拿到 Myna 原版的定位，"
                "再跑 bash scripts/install-gnome-extension.sh 并注销重登",
            )
        )
        return page

    # ---- navigation ----

    def _pages(self) -> list[str]:
        return ["welcome", "login", "shortcut", "hud"]

    def _go(self, delta: int) -> None:
        if self._stack is None:
            return
        pages = self._pages()
        current = pages.index(self._stack.get_visible_child_name())
        target = current + delta
        if target >= len(pages):
            self._finish()
            return
        target = max(0, min(len(pages) - 1, target))
        self._stack.set_visible_child_name(pages[target])

    def _update_buttons(self) -> None:
        if self._stack is None or self._back_button is None or self._next_button is None:
            return
        pages = self._pages()
        current = pages.index(self._stack.get_visible_child_name())
        self._back_button.set_sensitive(current > 0)
        last = current == len(pages) - 1
        _set_button_content_label(self._next_button_content, "完成" if last else "下一步")
        if pages[current] == "login":
            # 未登录不让过(Myna 的 Components 步同样要求就绪)
            self._next_button.set_sensitive(
                self._app_state.login_status == LoginStatus.LOGGED_IN
            )
        else:
            self._next_button.set_sensitive(True)

    def _refresh_login_row(self) -> None:
        if self._login_row is None:
            return
        status = self._app_state.login_status
        if status == LoginStatus.LOGGED_IN:
            _set_subtitle(self._login_row, "已登录")
            _set_button_content_label(self._login_button_content, "重新登录")
        elif status == LoginStatus.NOT_LOGGED_IN:
            _set_subtitle(self._login_row, "未登录 · 请先完成一次登录")
            _set_button_content_label(self._login_button_content, "登录豆包")
        else:
            _set_subtitle(self._login_row, "检测中…")
            _set_button_content_label(self._login_button_content, "登录豆包")

    def _finish(self) -> None:
        if self._on_finish is not None:
            self._on_finish()
        if self._window is not None:
            self._window.close()

    # ---- helpers ----

    def _capture(self) -> None:
        start_capture(self._window, self._apply_shortcut)

    def _apply_shortcut(self, accelerator: str) -> None:
        if self._on_shortcut_set is None:
            return
        # 冲突检测与设置窗口一致:桌面保留键直接劝退。
        if self._on_shortcut_conflicts is not None:
            try:
                conflicts = self._on_shortcut_conflicts(accelerator) or []
            except Exception:
                conflicts = []
            if conflicts and conflicts[0][1]:
                self._toast(f"{accelerator} 被桌面保留({conflicts[0][0]}),换一个吧")
                return
        ok, error = self._on_shortcut_set(accelerator)
        if ok:
            _set_shortcut_text(self._shortcut_widget, self._desktop_shortcut() or accelerator)
            if self._clear_button is not None:
                self._clear_button.set_sensitive(True)
            self._toast(f"快捷键已设为 {accelerator}")
        else:
            self._toast(f"设置失败: {error}")

    def _clear_shortcut(self) -> None:
        if self._on_shortcut_set is None:
            return
        ok, error = self._on_shortcut_set("")
        if ok:
            _set_shortcut_text(self._shortcut_widget, "")
            if self._clear_button is not None:
                self._clear_button.set_sensitive(False)
            self._toast("已清除桌面快捷键")
        else:
            self._toast(f"清除失败: {error}")

    def _copy_command(self) -> None:
        try:
            from gi.repository import Gdk  # type: ignore

            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set(Gdk.ContentProvider.new_for_value(BUILD_HINT))
            self._toast(f"已复制:{BUILD_HINT}")
        except Exception as e:
            self._toast(f"复制失败: {e}")

    def _toast(self, message: str) -> None:
        logger.info("onboarding: %s", message)
        if self._toast_overlay is not None:
            self._toast_overlay.add_toast(Adw.Toast.new(message))
