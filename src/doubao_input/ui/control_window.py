"""Control / settings window.

界面沿用 Myna Settings(myna-config,~/Desktop/myna/client/myna-config)那套
libadwaita 设置窗口:Adw.ApplicationWindow + ToolbarView + HeaderBar +
ViewSwitcher + PreferencesPage/Group + ActionRow/SwitchRow,分三页
(账号 / 输入 / 诊断)。逻辑与回调一个没动,换的只是"壳"。

没有 libadwaita(gi.require_version('Adw','1') 失败)的老系统上,自动退回
原来的纯 GTK4 窗口(_ensure_legacy_window),功能完全一致。

Content:
- 账号:  登录状态、登录/重新登录、凭证路径
- 输入:  触发键、最短按压、粘贴方式、Myna 悬浮胶囊开关
- 诊断:  麦克风自检、粘贴链路自检、悬浮窗状态、退出
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # type: ignore

from doubao_input.doubao.app_state import AppState, LoginStatus
from doubao_input.doubao.config import INJECT_USE_SHIFT, get_params_path

logger = logging.getLogger(__name__)

#: hicolor 主题里的图标名,由 .deb 安装为 scalable SVG(图标取自 Myna)。
_ICON_NAME = "doubao-input"

try:
    gi.require_version("Adw", "1")
    from gi.repository import Adw  # type: ignore

    Adw.init()
    _HAS_ADW = True
except Exception as e:  # pragma: no cover - 只在缺 libadwaita 时发生
    Adw = None  # type: ignore
    _HAS_ADW = False
    logger.info("libadwaita unavailable (%s); using the plain GTK window", e)


class ControlWindow:
    def __init__(
        self,
        app_state: AppState,
        on_login_clicked: Callable[[], None],
        on_quit_clicked: Callable[[], None],
        on_check_mic_clicked: Callable[[], None],
        on_test_inject_clicked: Optional[Callable[[], None]] = None,
        app: Optional[Gtk.Application] = None,
        hud_enabled: bool = False,
        on_hud_toggle: Optional[Callable[[bool], None]] = None,
        hud_status: Optional[Callable[[], str]] = None,
        inject_shift: bool = INJECT_USE_SHIFT,
        on_inject_shift_toggle: Optional[Callable[[bool], None]] = None,
    ) -> None:
        self._app_state = app_state
        self._on_login = on_login_clicked
        self._on_quit = on_quit_clicked
        self._on_check_mic = on_check_mic_clicked
        self._on_test_inject = on_test_inject_clicked
        self._app = app
        self._hud_enabled = hud_enabled
        self._on_hud_toggle = on_hud_toggle
        self._hud_status = hud_status
        self._inject_shift = inject_shift
        self._on_inject_shift_toggle = on_inject_shift_toggle
        self._window: Optional[Gtk.Window] = None
        self._status_label: Optional[Gtk.Label] = None
        self._account_row = None
        self._login_button: Optional[Gtk.Button] = None
        self._hud_status_label: Optional[Gtk.Label] = None
        self._hud_row = None
        self._toast_overlay = None
        self._app_state.connect("login-status-changed", self._on_status_changed)

    # ---- public ----

    def show(self) -> None:
        self._ensure_window()
        self._window.present()
        self._refresh_status()

    def hide(self) -> None:
        if self._window:
            self._window.set_visible(False)

    def destroy(self) -> None:
        if self._window:
            self._window.destroy()
            self._window = None

    def toast(self, message: str) -> None:
        """短暂提示(libadwaita 的 toast);没有 Adw 时忽略。"""
        if self._toast_overlay is None:
            logger.info("toast: %s", message)
            return
        self._toast_overlay.add_toast(Adw.Toast.new(message))

    # ---- internals ----

    def _ensure_window(self) -> None:
        if self._window is not None:
            return
        if _HAS_ADW:
            self._ensure_adw_window()
        else:
            self._ensure_legacy_window()

    # ---------- libadwaita:与 Myna Settings 同款 ----------

    def _ensure_adw_window(self) -> None:
        win = Adw.ApplicationWindow(application=self._app)
        win.set_title("豆包语音输入法")
        win.set_default_size(520, 560)
        # 图标走 hicolor 主题名(.deb 装的是 scalable SVG);源码运行没装
        # 图标时,GTK 只是不显示,不会报错。
        win.set_icon_name(_ICON_NAME)

        toolbar = Adw.ToolbarView()
        win.set_content(toolbar)

        stack = Adw.ViewStack()

        header = Adw.HeaderBar()
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        toolbar.add_top_bar(header)

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(stack)
        toolbar.set_content(self._toast_overlay)

        # --- 账号 ---
        account = Adw.PreferencesPage()
        account.set_title("账号")
        account.set_icon_name("avatar-default-symbolic")
        group = Adw.PreferencesGroup(title="豆包账号")
        account.add(group)

        self._account_row = Adw.ActionRow(title="登录状态", subtitle="检测中…")
        self._account_icon = Gtk.Image.new_from_icon_name("emblem-synchronizing-symbolic")
        self._account_icon.set_pixel_size(16)
        self._account_row.add_prefix(self._account_icon)
        self._login_button = Gtk.Button.new_with_label("登录豆包")
        self._login_button.set_valign(Gtk.Align.CENTER)
        self._login_button.add_css_class("suggested-action")
        self._login_button.connect("clicked", lambda *_: self._on_login())
        self._account_row.add_suffix(self._login_button)
        self._account_row.set_activatable_widget(self._login_button)
        group.add(self._account_row)

        creds = Adw.ActionRow(title="凭证文件", subtitle=str(get_params_path()))
        creds.set_subtitle_selectable(True)
        group.add(creds)

        # --- 输入 ---
        input_page = Adw.PreferencesPage()
        input_page.set_title("输入")
        input_page.set_icon_name("input-keyboard-symbolic")
        trigger_group = Adw.PreferencesGroup(title="触发")
        input_page.add(trigger_group)

        trigger_group.add(
            Adw.ActionRow(
                title="按住说话",
                subtitle="按住右 Ctrl 开始,松开即把识别结果粘贴到当前输入框",
            )
        )
        trigger_group.add(
            Adw.ActionRow(
                title="最短按压",
                subtitle="短于 0.15 秒视为误触,不录音也不注入",
            )
        )

        inject_group = Adw.PreferencesGroup(title="粘贴方式")
        input_page.add(inject_group)
        shift_row = Adw.SwitchRow(
            title="使用 Ctrl+Shift+V",
            subtitle="开启:终端也能粘贴;关闭:仅 GUI 应用可用的 Ctrl+V",
        )
        shift_row.set_active(self._inject_shift)
        shift_row.connect("notify::active", self._on_inject_shift_switch)
        inject_group.add(shift_row)

        hud_group = Adw.PreferencesGroup(title="悬浮窗")
        input_page.add(hud_group)
        if self._on_hud_toggle is not None:
            self._hud_row = Adw.SwitchRow(
                title="使用 Myna 悬浮胶囊",
                subtitle="由 Myna 的 myna-hud 绘制;关闭则用内置悬浮窗",
            )
            self._hud_row.set_active(self._hud_enabled)
            self._hud_row.connect("notify::active", self._on_hud_switch)
            hud_group.add(self._hud_row)

        usage_group = Adw.PreferencesGroup(title="使用方式")
        input_page.add(usage_group)
        usage = Gtk.Label()
        usage.set_xalign(0.0)
        usage.set_wrap(True)
        usage.set_markup(
            "1. 在任意输入框聚焦\n"
            "2. 按住 <b>右 Ctrl</b> 说话\n"
            "3. 松开右 Ctrl,识别结果自动粘贴到当前输入框\n\n"
            "<span alpha=\"50%\">终端里若粘贴失败,文字仍在剪贴板,可手动 Ctrl+Shift+V。</span>"
        )
        usage_group.add(usage)

        # --- 诊断 ---
        diag = Adw.PreferencesPage()
        diag.set_title("诊断")
        diag.set_icon_name("preferences-system-symbolic")
        self_group = Adw.PreferencesGroup(title="自检")
        diag.add(self_group)

        mic_row = Adw.ActionRow(title="麦克风", subtitle="采集 3 秒并输出 RMS 峰值")
        mic_button = Gtk.Button.new_with_label("检查")
        mic_button.set_valign(Gtk.Align.CENTER)
        mic_button.connect("clicked", lambda *_: self._on_check_mic())
        mic_row.add_suffix(mic_button)
        mic_row.set_activatable_widget(mic_button)
        self_group.add(mic_row)

        paste_row = Adw.ActionRow(
            title="粘贴链路", subtitle="注入一段固定文本,验证 wl-copy + uinput"
        )
        paste_button = Gtk.Button.new_with_label("测试")
        paste_button.set_valign(Gtk.Align.CENTER)
        if self._on_test_inject is not None:
            paste_button.connect("clicked", lambda *_: self._on_test_inject())
        else:
            paste_button.set_sensitive(False)
        paste_row.add_suffix(paste_button)
        paste_row.set_activatable_widget(paste_button)
        self_group.add(paste_row)

        status_group = Adw.PreferencesGroup(title="状态")
        diag.add(status_group)
        hud_status_row = Adw.ActionRow(title="悬浮窗")
        self._hud_status_label = Gtk.Label()
        self._hud_status_label.set_wrap(True)
        self._hud_status_label.set_justify(Gtk.Justification.LEFT)
        hud_status_row.add_suffix(self._hud_status_label)
        status_group.add(hud_status_row)
        self._refresh_hud_status()

        about_group = Adw.PreferencesGroup()
        diag.add(about_group)
        quit_row = Adw.ActionRow(title="退出", subtitle="停止监听并关闭悬浮窗")
        quit_button = Gtk.Button.new_with_label("退出")
        quit_button.set_valign(Gtk.Align.CENTER)
        quit_button.add_css_class("destructive-action")
        quit_button.connect("clicked", lambda *_: self._on_quit())
        quit_row.add_suffix(quit_button)
        quit_row.set_activatable_widget(quit_button)
        about_group.add(quit_row)

        stack.add_titled_with_icon(account, "account", "账号", "avatar-default-symbolic")
        stack.add_titled_with_icon(input_page, "input", "输入", "input-keyboard-symbolic")
        stack.add_titled_with_icon(diag, "diagnostics", "诊断", "preferences-system-symbolic")

        self._window = win

    # ---------- 退化路径:纯 GTK4 ----------

    def _ensure_legacy_window(self) -> None:
        win = Gtk.ApplicationWindow(application=self._app) if self._app is not None else Gtk.Window()
        win.set_title("豆包语音输入法")
        win.set_default_size(440, 420)
        win.set_destroy_with_parent(True)
        win.set_icon_name(_ICON_NAME)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_margin_top(20)
        box.set_margin_bottom(20)

        self._status_label = Gtk.Label()
        self._status_label.set_xalign(0.0)
        self._status_label.set_wrap(True)
        self._status_label.set_selectable(True)
        box.append(self._status_label)

        login_btn = Gtk.Button.new_with_label("登录豆包")
        login_btn.connect("clicked", lambda *_: self._on_login())
        box.append(login_btn)

        check_btn = Gtk.Button.new_with_label("检查麦克风 (输出 RMS)")
        check_btn.connect("clicked", lambda *_: self._on_check_mic())
        box.append(check_btn)

        test_btn = Gtk.Button.new_with_label("测试粘贴 (注入 'hello 测试 123')")
        if self._on_test_inject is not None:
            test_btn.connect("clicked", lambda *_: self._on_test_inject())
        else:
            test_btn.set_sensitive(False)
        box.append(test_btn)

        # 悬浮窗开关(Myna 胶囊 / 内置悬浮窗)
        if self._on_hud_toggle is not None:
            hud_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            hud_name = Gtk.Label(label="使用 Myna 悬浮胶囊")
            hud_name.set_xalign(0.0)
            hud_name.set_hexpand(True)
            hud_switch = Gtk.Switch()
            hud_switch.set_active(self._hud_enabled)
            hud_switch.set_valign(Gtk.Align.CENTER)
            hud_switch.connect("state-set", self._on_hud_switch)
            hud_box.append(hud_name)
            hud_box.append(hud_switch)
            box.append(hud_box)

            self._hud_status_label = Gtk.Label()
            self._hud_status_label.set_xalign(0.0)
            self._hud_status_label.set_wrap(True)
            box.append(self._hud_status_label)
            self._refresh_hud_status()

        help = Gtk.Label()
        help.set_xalign(0.0)
        help.set_wrap(True)
        help.set_markup(
            "<small>"
            "<b>使用方式</b>\n"
            "1. 在任意输入框聚焦\n"
            "2. 按住 <b>右 Ctrl</b> 说话\n"
            "3. 松开右 Ctrl,识别结果自动粘贴到当前输入框\n"
            "\n"
            "<b>注意</b>\n"
            "• 终端里需手动 Ctrl+Shift+V\n"
            f"• 凭证保存在 {get_params_path()}\n"
            "</small>"
        )
        box.append(help)

        quit_btn = Gtk.Button.new_with_label("退出")
        quit_btn.connect("clicked", lambda *_: self._on_quit())
        box.append(quit_btn)

        win.set_child(box)
        self._window = win

    # ---- 行回调 ----

    def _on_hud_switch(self, row, *_args) -> bool:
        """Adw.SwitchRow 走 notify::active,Gtk.Switch 走 state-set;两种都接。

        注意 Gtk.Switch 的 state-set 在状态真正翻转前触发,那时 get_active()
        还是旧值,必须取信号带来的参数。
        """
        if isinstance(row, Gtk.Switch):
            active = bool(_args[0]) if _args else row.get_active()
        else:
            active = row.get_active()
        if self._on_hud_toggle is not None:
            self._on_hud_toggle(bool(active))
        self._hud_enabled = bool(active)
        GLib.timeout_add(300, lambda: (self._refresh_hud_status(), False)[1])
        return False

    def _on_inject_shift_switch(self, row, _param) -> None:
        active = bool(row.get_active())
        self._inject_shift = active
        if self._on_inject_shift_toggle is not None:
            self._on_inject_shift_toggle(active)

    def _refresh_hud_status(self) -> None:
        if not self._hud_status_label:
            return
        if self._hud_status is None:
            self._hud_status_label.set_text("")
            return
        try:
            self._hud_status_label.set_markup(
                f"<small>{GLib.markup_escape_text(self._hud_status())}</small>"
            )
        except Exception as e:
            self._hud_status_label.set_text(f"悬浮窗状态未知 ({e})")

    def _on_status_changed(self, *_args) -> None:
        self._refresh_status()

    def _refresh_status(self) -> None:
        status = self._app_state.login_status
        if status == LoginStatus.LOGGED_IN:
            text, icon = "已登录", "emblem-ok-symbolic"
        elif status == LoginStatus.NOT_LOGGED_IN:
            text, icon = "未登录 · 点击「登录豆包」完成一次登录", "dialog-warning-symbolic"
        else:
            text, icon = "检测中…", "emblem-synchronizing-symbolic"

        if self._status_label is not None:  # 退化路径
            if status == LoginStatus.LOGGED_IN:
                self._status_label.set_markup("状态:<b>已登录</b>  ✅")
            elif status == LoginStatus.NOT_LOGGED_IN:
                self._status_label.set_markup(
                    "状态:<b>未登录</b>  ❌\n请点击「登录豆包」完成一次登录。"
                )
            else:
                self._status_label.set_markup("状态:<b>检测中…</b>")
            return

        if self._account_row is None:
            return
        self._account_row.set_subtitle(text)
        if self._login_button is not None:
            self._login_button.set_label(
                "重新登录" if status == LoginStatus.LOGGED_IN else "登录豆包"
            )
        self._account_icon.set_from_icon_name(icon)
