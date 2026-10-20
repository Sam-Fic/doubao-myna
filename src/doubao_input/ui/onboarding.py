"""首次运行向导 —— 对齐 Myna 的 onboarding(Welcome → 组件 → 快捷键)。

后端不同,步骤也相应调整:

  1. **欢迎** —— 说明"按住右 Ctrl 说话、松开就粘贴",以及"凭证只存本地"。
  2. **登录豆包** —— 没登录不让继续(WebKit 登录窗口由 app 提供)。
  3. **快捷键** —— 桌面快捷键(共用 control_window 的捕获逻辑)+ 物理键说明。
  4. **Myna 胶囊(可选)** —— 显示当前状态;没装就给一行安装命令和复制按钮。

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


def available() -> bool:
    """libadwaita 是否可用(不可用时向导静默跳过)。"""
    return _HAS_ADW


BUILD_HINT = "bash scripts/build-myna-hud.sh"


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
        self._shortcut_keycap: Optional[Gtk.Label] = None
        self._hud_status_label: Optional[Gtk.Label] = None
        self._parent = parent

    # ---- public ----

    def show(self) -> None:
        if not _HAS_ADW:
            logger.info("libadwaita 不可用,跳过向导")
            return
        self._ensure_window()
        if self._window is not None:
            self._window.present()

    def refresh(self) -> None:
        """登录态 / 胶囊状态变化后刷新当前页。"""
        if self._shortcut_keycap is not None:
            self._shortcut_keycap.set_label(self._desktop_shortcut() or "未设置")
        if self._hud_status_label is not None:
            self._hud_status_label.set_markup(
                f"<small>{GLib.markup_escape_text(self._hud_status())}</small>"
            )
        self._update_buttons()

    # ---- internals ----

    def _ensure_window(self) -> None:
        if self._window is not None:
            return
        win = Adw.Window()
        if self._parent is not None:
            win.set_transient_for(self._parent)
        win.set_title("设置豆包语音输入法")
        win.set_default_size(520, 520)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)
        win.set_content(toolbar)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        toolbar.set_content(self._stack)

        self._stack.add_named(self._build_welcome(), "welcome")
        self._stack.add_named(self._build_login(), "login")
        self._stack.add_named(self._build_shortcut(), "shortcut")
        self._stack.add_named(self._build_hud(), "hud")

        action_bar = Gtk.ActionBar()
        self._back_button = Gtk.Button(label="上一步")
        self._back_button.connect("clicked", lambda *_: self._go(-1))
        action_bar.pack_start(self._back_button)
        self._next_button = Gtk.Button(label="下一步")
        self._next_button.add_css_class("suggested-action")
        self._next_button.connect("clicked", lambda *_: self._go(1))
        action_bar.pack_end(self._next_button)
        toolbar.add_bottom_bar(action_bar)

        self._stack.connect("notify::visible-child", lambda *_: self._update_buttons())
        self._app_state.connect("login-status-changed", lambda *_: self._update_buttons())
        self._window = win
        self._update_buttons()

    # ---- pages ----

    def _build_welcome(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(32)
        box.set_margin_end(32)

        icon = Gtk.Image.new_from_icon_name("doubao-input")
        icon.set_pixel_size(96)
        box.append(icon)

        title = Gtk.Label()
        title.set_markup("<b><big>设置豆包语音输入法</big></b>")
        box.append(title)

        body = Gtk.Label()
        body.set_justify(Gtk.Justification.CENTER)
        body.set_wrap(True)
        body.set_markup(
            "在任意输入框聚焦,<b>按住右 Ctrl</b> 说话,松开就把识别结果粘贴进去。\n"
            "<small>识别由豆包的网页服务完成;登录凭证只保存在本机,不会发给第三方。</small>"
        )
        box.append(body)
        return box

    def _build_login(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="登录豆包",
            description="第一次使用需要登录一次,之后凭证会复用。",
        )
        page.add(group)

        row = Adw.ActionRow(title="登录状态")
        self._login_button = Gtk.Button(label="登录豆包")
        self._login_button.set_valign(Gtk.Align.CENTER)
        self._login_button.add_css_class("suggested-action")
        self._login_button.connect("clicked", lambda *_: self._on_login())
        row.add_suffix(self._login_button)
        row.set_activatable_widget(self._login_button)
        group.add(row)

        hint = Gtk.Label()
        hint.set_xalign(0.0)
        hint.set_wrap(True)
        hint.set_markup(
            "<small>点「登录豆包」会打开一个网页窗口,在里面正常登录即可;"
            "成功后本窗口的状态会自动更新。</small>"
        )
        group.add(hint)
        return page

    def _build_shortcut(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="快捷键",
            # 注意 < > 在 Adw 的 description 里是 Pango 标记,必须转义。
            description="桌面快捷键支持 &lt;Super&gt;j 这类组合键;物理键则由 evdev 直接监听。",
        )
        page.add(group)

        row = Adw.ActionRow(
            title="桌面快捷键",
            subtitle="写进桌面的自定义快捷键,命令是 D-Bus Toggle",
        )
        self._shortcut_keycap = Gtk.Label(label="未设置")
        self._shortcut_keycap.add_css_class("keycap")
        self._shortcut_keycap.set_valign(Gtk.Align.CENTER)
        button = Gtk.Button(label="设置")
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", lambda *_: self._capture())
        row.add_suffix(self._shortcut_keycap)
        row.add_suffix(button)
        row.set_activatable_widget(button)
        group.add(row)

        group.add(
            Adw.ActionRow(
                title="物理键",
                subtitle="默认右 Ctrl,可在设置窗口的「输入」页更换",
            )
        )
        group.add(
            Adw.ActionRow(
                title="触发方式",
                subtitle="默认按住说话;想要 Myna 的「按一下开始/再按一下结束」可在设置里切换",
            )
        )
        self._shortcut_keycap.set_label(self._desktop_shortcut() or "未设置")
        return page

    def _build_hud(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="悬浮胶囊",
            description="可选项:用 Myna 的 myna-hud 绘制录音指示器。",
        )
        page.add(group)

        row = Adw.ActionRow(title="当前状态")
        self._hud_status_label = Gtk.Label()
        self._hud_status_label.set_wrap(True)
        self._hud_status_label.set_justify(Gtk.Justification.LEFT)
        row.add_suffix(self._hud_status_label)
        group.add(row)
        self.refresh()

        install_row = Adw.ActionRow(
            title="安装命令",
            subtitle="需要 cargo + libgtk-4-dev + libadwaita-1-dev",
        )
        copy = Gtk.Button(label="复制")
        copy.set_valign(Gtk.Align.CENTER)
        copy.connect("clicked", lambda *_: self._copy_command())
        install_row.add_suffix(copy)
        install_row.set_activatable_widget(copy)
        group.add(install_row)

        note = Gtk.Label()
        note.set_xalign(0.0)
        note.set_wrap(True)
        note.set_markup(
            "<small>不装也能用:会退回内置的悬浮窗。想拿到 Myna 原版的定位,"
            "再跑 <tt>bash scripts/install-gnome-extension.sh</tt> 并注销重登。</small>"
        )
        group.add(note)
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
        self._next_button.set_label("完成" if last else "下一步")
        if pages[current] == "login":
            # 未登录不让过(Myna 的 Components 步同样要求就绪)
            self._next_button.set_sensitive(
                self._app_state.login_status == LoginStatus.LOGGED_IN
            )
        else:
            self._next_button.set_sensitive(True)

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
            self._shortcut_keycap.set_label(self._desktop_shortcut() or accelerator)
            self._toast(f"快捷键已设为 {accelerator}")
        else:
            self._toast(f"设置失败: {error}")

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
