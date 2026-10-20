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
from typing import Any, Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # type: ignore

from doubao_input.doubao.app_state import AppState, LoginStatus
from doubao_input.doubao.config import (
    HUD_STYLE,
    INJECT_USE_SHIFT,
    SILENCE_TIMEOUT_SECS,
    TRIGGER_KEY_NAME,
    TRIGGER_MODE,
    get_params_path,
)
from doubao_input.ui.shortcut_capture import start_capture

#: 设置窗口里可选的物理键(evdev 键名 → 显示名)
TRIGGER_KEY_CHOICES = [
    ("KEY_RIGHTCTRL", "右 Ctrl"),
    ("KEY_LEFTCTRL", "左 Ctrl"),
    ("KEY_RIGHTALT", "右 Alt"),
    ("KEY_LEFTALT", "左 Alt"),
    ("KEY_RIGHTSHIFT", "右 Shift"),
    ("KEY_LEFTMETA", "左 Super"),
    ("KEY_RIGHTMETA", "右 Super"),
    ("KEY_SCROLLLOCK", "Scroll Lock"),
    ("KEY_PAUSE", "Pause"),
    ("KEY_F12", "F12"),
    ("KEY_F13", "F13"),
    ("KEY_COMPOSE", "Menu"),
]

#: 胶囊波形样式(Myna 的 hud-style 取值)
HUD_STYLE_CHOICES = [
    ("ribbon", "Ribbon(波浪)"),
    ("bar", "Default(电平条)"),
    ("vumeter", "VU meter"),
]

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
        trigger_key: str = TRIGGER_KEY_NAME,
        on_trigger_key_changed: Optional[Callable[[str], None]] = None,
        trigger_mode: str = TRIGGER_MODE,
        on_trigger_mode_changed: Optional[Callable[[str], None]] = None,
        silence_timeout: int = SILENCE_TIMEOUT_SECS,
        on_silence_timeout_changed: Optional[Callable[[int], None]] = None,
        hud_style: str = HUD_STYLE,
        on_hud_style_changed: Optional[Callable[[str], None]] = None,
        desktop_shortcut: str = "",
        desktop_shortcut_supported: bool = False,
        on_desktop_shortcut_changed: Optional[Callable[[str], Any]] = None,
        stop_on_focus_loss: bool = False,
        focus_loss_supported: bool = False,
        focus_loss_reason: str = "",
        on_stop_on_focus_loss_changed: Optional[Callable[[bool], None]] = None,
        sounds: bool = True,
        sounds_supported: bool = False,
        on_sounds_changed: Optional[Callable[[bool], None]] = None,
        on_desktop_shortcut_conflicts: Optional[Callable[[str], Any]] = None,
        last_error: Optional[Callable[[], str]] = None,
        report: Optional[Callable[[], str]] = None,
        on_run_onboarding: Optional[Callable[[], None]] = None,
        on_about: Optional[Callable[[], None]] = None,
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
        self._trigger_key = trigger_key
        self._on_trigger_key_changed = on_trigger_key_changed
        self._trigger_mode = "toggle" if trigger_mode == "toggle" else "hold"
        self._on_trigger_mode_changed = on_trigger_mode_changed
        self._silence_timeout = silence_timeout
        self._on_silence_timeout_changed = on_silence_timeout_changed
        self._hud_style = hud_style
        self._on_hud_style_changed = on_hud_style_changed
        self._desktop_shortcut = desktop_shortcut
        self._desktop_shortcut_supported = desktop_shortcut_supported
        self._on_desktop_shortcut_changed = on_desktop_shortcut_changed
        self._stop_on_focus_loss = stop_on_focus_loss
        self._focus_loss_supported = focus_loss_supported
        self._focus_loss_reason = focus_loss_reason
        self._on_stop_on_focus_loss_changed = on_stop_on_focus_loss_changed
        self._sounds = sounds
        self._sounds_supported = sounds_supported
        self._on_sounds_changed = on_sounds_changed
        self._on_desktop_shortcut_conflicts = on_desktop_shortcut_conflicts
        self._last_error = last_error
        self._last_error_label: Optional[Gtk.Label] = None
        self._report = report
        self._report_view: Optional[Gtk.TextView] = None
        self._on_run_onboarding = on_run_onboarding
        self._on_about = on_about
        self._shortcut_keycap: Optional[Gtk.Label] = None
        self._shortcut_button: Optional[Gtk.Button] = None
        self._shortcut_row = None
        self._capture_window = None
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
        self._refresh_hud_status()
        self._refresh_last_error()

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
        if self._on_run_onboarding is not None or self._on_about is not None:
            header.pack_end(self._build_menu())
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
        trigger_group = Adw.PreferencesGroup(
            title="触发",
            description="桌面快捷键可以带 Super/Ctrl/Alt 组合键;物理键由 evdev 直接监听。",
        )
        input_page.add(trigger_group)

        # 桌面快捷键(Myna 的做法:绑到 D-Bus Toggle)
        self._shortcut_row = Adw.ActionRow(
            title="桌面快捷键",
            subtitle="写进桌面的自定义快捷键,命令是 D-Bus Toggle",
        )
        self._shortcut_keycap = Gtk.Label()
        self._shortcut_keycap.add_css_class("keycap")
        self._shortcut_keycap.set_valign(Gtk.Align.CENTER)
        self._shortcut_button = Gtk.Button()
        self._shortcut_button.set_valign(Gtk.Align.CENTER)
        self._shortcut_button.connect("clicked", self._on_shortcut_button)
        self._shortcut_row.add_suffix(self._shortcut_keycap)
        self._shortcut_row.add_suffix(self._shortcut_button)
        trigger_group.add(self._shortcut_row)
        self._refresh_shortcut_row()

        # 物理键(evdev)
        key_row = Adw.ComboRow(
            title="物理键",
            subtitle="直接监听 /dev/input/event*,不需要桌面配合",
        )
        key_model = Gtk.StringList.new([name for _, name in TRIGGER_KEY_CHOICES])
        key_row.set_model(key_model)
        for index, (value, _name) in enumerate(TRIGGER_KEY_CHOICES):
            if value == self._trigger_key:
                key_row.set_selected(index)
        key_row.connect("notify::selected", self._on_trigger_key_selected)
        trigger_group.add(key_row)

        # 触发模式
        mode_row = Adw.ComboRow(
            title="触发方式",
            subtitle="「按一下开始」是 Myna 的交互;「按住说话」是豆包原生的",
        )
        mode_row.set_model(Gtk.StringList.new(["按住说话(松开即结束)", "按一下开始 / 再按一下结束"]))
        mode_row.set_selected(1 if self._trigger_mode == "toggle" else 0)
        mode_row.connect("notify::selected", self._on_trigger_mode_selected)
        trigger_group.add(mode_row)

        dictation_group = Adw.PreferencesGroup(title="听写")
        input_page.add(dictation_group)

        silence_row = Adw.SpinRow(
            title="静音自动结束(秒)",
            subtitle="0 = 不自动结束(对齐 Myna 的 silence-timeout)",
        )
        silence_row.set_adjustment(
            Gtk.Adjustment(
                value=self._silence_timeout, lower=0, upper=600, step_increment=1
            )
        )
        silence_row.connect("notify::value", self._on_silence_changed)
        dictation_group.add(silence_row)

        # 焦点离开就结束(可选;探测不到焦点时置灰并说明原因)
        focus_row = Adw.SwitchRow(
            title="焦点离开时结束",
            subtitle=self._focus_loss_reason or "Myna 的行为:焦点一离开就丢弃本次内容",
        )
        focus_row.set_active(self._stop_on_focus_loss)
        focus_row.set_sensitive(self._focus_loss_supported)
        focus_row.connect("notify::active", self._on_focus_loss_switch)
        dictation_group.add(focus_row)

        # 提示音(Myna 的 sounds:开始 / 结束 / 错误)
        sounds_row = Adw.SwitchRow(
            title="提示音",
            subtitle="开始 / 结束 / 错误时播放"
            + ("" if self._sounds_supported else "（未找到 canberra-gtk-play，不会响）"),
        )
        sounds_row.set_active(self._sounds)
        sounds_row.set_sensitive(self._sounds_supported)
        sounds_row.connect("notify::active", self._on_sounds_switch)
        dictation_group.add(sounds_row)

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

        style_row = Adw.ComboRow(title="波形样式", subtitle="Myna 的 hud-style")
        style_row.set_model(Gtk.StringList.new([name for _, name in HUD_STYLE_CHOICES]))
        for index, (value, _name) in enumerate(HUD_STYLE_CHOICES):
            if value == self._hud_style:
                style_row.set_selected(index)
        style_row.connect("notify::selected", self._on_hud_style_selected)
        hud_group.add(style_row)

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
        last_error_row = Adw.ActionRow(title="最近错误")
        self._last_error_label = Gtk.Label()
        self._last_error_label.set_wrap(True)
        self._last_error_label.set_justify(Gtk.Justification.LEFT)
        last_error_row.add_suffix(self._last_error_label)
        status_group.add(last_error_row)
        self._refresh_last_error()

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

        # ---- 诊断报告(Myna 的隐私诊断:不含音频/识别文本/文件路径) ----
        report_group = Adw.PreferencesGroup(
            title="诊断报告",
            description="报告不含音频、识别文本或任何文件路径(路径一律替换为 [redacted])。",
        )
        diag.add(report_group)

        report_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        refresh_button = Gtk.Button.new_with_label("刷新")
        refresh_button.set_tooltip_text("重新检查本机与各组件状态")
        refresh_button.connect("clicked", lambda *_: self._refresh_report())
        report_buttons.append(refresh_button)
        copy_button = Gtk.Button.new_with_label("复制")
        copy_button.set_tooltip_text("复制隐私安全的诊断报告到剪贴板")
        copy_button.connect("clicked", lambda *_: self._copy_report())
        report_buttons.append(copy_button)
        try:
            report_group.set_header_suffix(report_buttons)
        except Exception:
            # 老版本 libadwaita 没有 header-suffix,就退化成一行。
            actions = Adw.ActionRow(title="操作")
            actions.add_suffix(report_buttons)
            report_group.add(actions)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(240)
        scrolled.set_vexpand(True)
        scrolled.set_has_frame(True)
        self._report_view = Gtk.TextView()
        self._report_view.set_editable(False)
        self._report_view.set_cursor_visible(False)
        self._report_view.set_monospace(True)
        self._report_view.set_left_margin(8)
        self._report_view.set_right_margin(8)
        self._report_view.set_top_margin(8)
        self._report_view.set_bottom_margin(8)
        self._report_view.set_wrap_mode(Gtk.WrapMode.WORD)
        scrolled.set_child(self._report_view)
        report_group.add(scrolled)
        self._refresh_report()

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

    def _build_menu(self) -> Gtk.Widget:
        """主菜单:运行设置向导 / 关于(Myna Settings 的同款入口)。"""
        button = Gtk.MenuButton()
        button.set_icon_name("open-menu-symbolic")
        button.set_tooltip_text("主菜单")

        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        if self._on_run_onboarding is not None:
            item = Gtk.Button(label="运行设置向导…")
            item.add_css_class("flat")
            item.connect("clicked", self._on_run_onboarding_clicked)
            box.append(item)
        if self._on_about is not None:
            item = Gtk.Button(label="关于")
            item.add_css_class("flat")
            item.connect("clicked", self._on_about_clicked)
            box.append(item)
        popover.set_child(box)
        button.set_popover(popover)
        return button

    def _on_run_onboarding_clicked(self, *_args) -> None:
        if self._on_run_onboarding is not None:
            self._on_run_onboarding()

    def _on_about_clicked(self, *_args) -> None:
        if self._on_about is not None:
            self._on_about()

    # ---- 快捷键(Myna 风格:键帽 + 捕获) ----

    def _refresh_shortcut_row(self) -> None:
        if self._shortcut_keycap is None or self._shortcut_button is None:
            return
        binding = self._desktop_shortcut
        self._shortcut_keycap.set_label(binding or "未设置")
        self._shortcut_button.set_label("更改" if binding else "设置")
        if not self._desktop_shortcut_supported:
            self._shortcut_row.set_subtitle(
                "当前桌面不支持写入自定义快捷键(需要 GNOME 或 Xfce)"
            )
            self._shortcut_button.set_sensitive(False)

    def _on_shortcut_button(self, *_args) -> None:
        start_capture(self._window, self._offer_shortcut)

    def _offer_shortcut(self, accelerator: str) -> None:
        """写键前先查冲突(Myna:桌面保留键要提示换一个,别人的自定义键可替换)。"""
        conflicts: list = []
        if self._on_desktop_shortcut_conflicts is not None:
            try:
                conflicts = self._on_desktop_shortcut_conflicts(accelerator) or []
            except Exception as e:
                logger.warning("conflict check failed: %s", e)
        if not conflicts:
            self._apply_shortcut(accelerator)
            return

        owner, reserved = conflicts[0]
        if reserved:
            self.toast(f"{accelerator} 被桌面保留({owner}),换一个吧")
            return
        if not _HAS_ADW or self._window is None:
            self.toast(f"{accelerator} 已被「{owner}」占用")
            return

        dialog = Adw.AlertDialog.new(
            "替换快捷键?",
            f"{accelerator} 已被「{owner}」使用。替换会把它从那里移除。",
        )
        dialog.add_response("cancel", "取消")
        dialog.add_response("replace", "替换")
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_replace_response, accelerator)
        dialog.present(self._window)

    def _on_replace_response(self, _dialog, response: str, accelerator: str) -> None:
        if response == "replace":
            self._apply_shortcut(accelerator)

    def _apply_shortcut(self, accelerator: str) -> None:
        if self._on_desktop_shortcut_changed is None:
            return
        ok, error = self._on_desktop_shortcut_changed(accelerator)
        if ok:
            self._desktop_shortcut = accelerator
            self._refresh_shortcut_row()
            self.toast(f"快捷键已设为 {accelerator}")
        else:
            self.toast(f"快捷键设置失败:{error}")

    # ---- 触发 / 听写设置 ----

    def _on_trigger_key_selected(self, row, _param) -> None:
        index = row.get_selected()
        if index < 0 or index >= len(TRIGGER_KEY_CHOICES):
            return
        value = TRIGGER_KEY_CHOICES[index][0]
        self._trigger_key = value
        if self._on_trigger_key_changed is not None:
            self._on_trigger_key_changed(value)

    def _on_trigger_mode_selected(self, row, _param) -> None:
        mode = "toggle" if row.get_selected() == 1 else "hold"
        self._trigger_mode = mode
        if self._on_trigger_mode_changed is not None:
            self._on_trigger_mode_changed(mode)

    def _on_silence_changed(self, row, _param) -> None:
        seconds = int(row.get_value())
        self._silence_timeout = seconds
        if self._on_silence_timeout_changed is not None:
            self._on_silence_timeout_changed(seconds)

    def _on_sounds_switch(self, row, *_args) -> None:
        active = row.get_active() if hasattr(row, "get_active") else False
        self._sounds = bool(active)
        if self._on_sounds_changed is not None:
            self._on_sounds_changed(bool(active))

    def _on_focus_loss_switch(self, row, *_args) -> None:
        active = row.get_active() if hasattr(row, "get_active") else False
        self._stop_on_focus_loss = bool(active)
        if self._on_stop_on_focus_loss_changed is not None:
            self._on_stop_on_focus_loss_changed(bool(active))

    def _on_hud_style_selected(self, row, _param) -> None:
        index = row.get_selected()
        if index < 0 or index >= len(HUD_STYLE_CHOICES):
            return
        value = HUD_STYLE_CHOICES[index][0]
        self._hud_style = value
        if self._on_hud_style_changed is not None:
            self._on_hud_style_changed(value)

    def _refresh_last_error(self) -> None:
        if self._last_error_label is None:
            return
        if self._last_error is None:
            self._last_error_label.set_text("")
            return
        try:
            self._last_error_label.set_markup(
                f"<small>{GLib.markup_escape_text(self._last_error())}</small>"
            )
        except Exception as e:
            self._last_error_label.set_text(f"未知 ({e})")

    # ---- 诊断报告(Myna 的隐私诊断) ----

    def _refresh_report(self) -> None:
        if self._report_view is None:
            return
        try:
            text = self._report() if self._report is not None else ""
        except Exception as e:
            logger.warning("diagnostics report failed: %s", e)
            text = f"诊断报告生成失败: {e}"
        self._report_view.get_buffer().set_text(text)

    def _copy_report(self) -> None:
        if self._report_view is None:
            return
        try:
            buffer = self._report_view.get_buffer()
            text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
            from gi.repository import Gdk  # type: ignore

            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set(Gdk.ContentProvider.new_for_value(text))
            self.toast("诊断报告已复制到剪贴板")
        except Exception as e:
            self.toast(f"复制失败: {e}")

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
