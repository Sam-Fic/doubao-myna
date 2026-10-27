"""Control / settings window.

界面沿用 Myna Settings(myna-config)那套 libadwaita 设置窗口:
Adw.ApplicationWindow + ToolbarView + HeaderBar + ViewStack/ViewSwitcher +
PreferencesPage/Group + ActionRow/SwitchRow/ComboRow/SpinRow,
外面再套 Adw.Banner(登录提示)与 Adw.ToastOverlay(瞬时结果)。

组件尽量交给 libadwaita 的默认值:
  * 主菜单用 Gio.Menu(而不是手搓 Popover + 一堆扁平按钮);
  * 按钮内容用 Adw.ButtonContent(图标 + 文字);
  * 快捷键用 Adw.ShortcutLabel 画键帽(旧版 libadwaita 退回自带 .keycap 样式);
  * 状态信息一律走「行的副标题」,不再自己拼 Gtk.Label;
  * 诊断报告不再套一层边框(卡片套卡片是 Adw 的反模式),高度交给页面滚动;
  * 图标全部使用 Adwaita 的 symbolic 图标名。

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
from gi.repository import GLib, Gdk, Gio, Gtk  # type: ignore

from doubao_input.doubao.app_state import AppState, LoginStatus
from doubao_input.doubao.config import (
    HUD_STYLE,
    INJECT_USE_SHIFT,
    SILENCE_TIMEOUT_SECS,
    TRIGGER_KEY_CHOICES,
    TRIGGER_KEY_NAME,
    TRIGGER_MODE,
    TRIGGER_MODE_CHOICES,
    get_params_path,
)
from doubao_input import i18n
from doubao_input.i18n import LANGUAGES, _
from doubao_input.hud.settings import save_language
from doubao_input.ui.adw_compat import (
    HAS_ADW as _HAS_ADW,
    Adw,
    copy_text as _copy_text,
    icon_name as _icon_name,
    set_subtitle as _set_subtitle,
    shortcut_widget as _shortcut_widget,
    accelerator_label as _accelerator_label,
)
from doubao_input.ui.shortcut_capture import start_capture

#: 胶囊波形样式(Myna 的 hud-style 取值;Default 排第一;显示名走 i18n,源码英文)。
#: (物理键那张表在 doubao/config.py —— 那是唯一来源。)
HUD_STYLE_CHOICES = [
    ("bar", "Default (level bar)"),
    ("ribbon", "Ribbon (wave)"),
    ("vumeter", "VU meter"),
]

logger = logging.getLogger(__name__)

#: hicolor 主题里的图标名,由 .deb 安装为 scalable SVG(图标取自 Myna)。
_ICON_NAME = "doubao-input"

#: 诊断报告的卡片样式(圆角 + 跟随主题的底色/边框)。
_report_card_provider = None


def _report_card_css():
    """诊断报告框的 CSS(方框改圆角卡片)。只创建一次。"""
    global _report_card_provider
    if _report_card_provider is None:
        provider = Gtk.CssProvider()
        provider.load_from_data(
            ".report-card {"
            "  border-radius: 12px;"
            "  background-color: @view_bg_color;"
            "  border: 1px solid @borders;"
            "  padding: 4px;"
            "}"
            ".report-card textview { background: transparent; }"
        )
        _report_card_provider = provider
    return _report_card_provider


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
        autostart: bool = False,
        autostart_supported: bool = True,
        autostart_reason: str = "",
        on_autostart_changed: Optional[Callable[[bool], Any]] = None,
        on_desktop_shortcut_conflicts: Optional[Callable[[str], Any]] = None,
        last_error: Optional[Callable[[], str]] = None,
        report: Optional[Callable[[], str]] = None,
        on_run_onboarding: Optional[Callable[[], None]] = None,
        on_about: Optional[Callable[[], None]] = None,
        on_language_changed: Optional[Callable[[], None]] = None,
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
        self._autostart = autostart
        self._autostart_supported = autostart_supported
        self._autostart_reason = autostart_reason
        self._on_autostart_changed = on_autostart_changed
        # 失败回拨开关时用来挡掉连锁的 notify::active
        self._autostart_updating = False
        self._on_desktop_shortcut_conflicts = on_desktop_shortcut_conflicts
        self._last_error = last_error
        self._last_error_row = None
        self._report = report
        self._report_view: Optional[Gtk.TextView] = None
        self._on_run_onboarding = on_run_onboarding
        self._on_about = on_about
        self._on_language_changed = on_language_changed
        self._shortcut_widget: Optional[Gtk.Widget] = None
        self._shortcut_button: Optional[Gtk.Button] = None
        self._shortcut_row = None
        self._capture_window = None
        self._window: Optional[Gtk.Window] = None
        self._status_label: Optional[Gtk.Label] = None
        self._account_row = None
        self._login_button: Optional[Gtk.Button] = None
        self._hud_status_row = None
        self._hud_status_label: Optional[Gtk.Label] = None
        self._hud_row = None
        self._hud_style_row = None
        self._trigger_key_row = None
        self._trigger_mode_row = None
        self._banner = None
        self._toast_overlay = None
        self._app_state.connect("login-status-changed", self._on_status_changed)
        # 关窗口 = 隐藏到托盘(不是退出)。只有托盘菜单的「退出」才真退出。
        # 与 mihomo-manifold 的做法一致:没托盘时就退化成「关掉即退出」,
        # 否则窗口一关应用就失联了(没有入口能把它叫回来)。
        self._hide_on_close = False

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

    def set_hide_on_close(self, enabled: bool) -> None:
        """关窗时隐藏而不是退出。只应在托盘图标真的显示出来之后打开。"""
        self._hide_on_close = bool(enabled)

    def _on_close_request(self, _window) -> bool:
        """返回 True 阻止默认的 destroy。

        托盘可用时把窗口收起来(应用继续常驻、热键监听不断),
        托盘不可用时返回 False,让 GTK 走正常的关窗→应用退出。
        """
        if not self._hide_on_close:
            return False
        logger.info("control window closed -> hidden to tray")
        self._window.set_visible(False)
        return True

    def destroy(self) -> None:
        if not self._window:
            return
        # 先把菜单弹层收掉:否则销毁窗口时 GTK 会警告
        # "Finalizing GtkMenuButton ... but it still has children left"
        # (切换界面语言会走这条重建路径,不想每次都刷一行警告)。
        self._close_popovers(self._window)
        self._window.destroy()
        self._window = None

    @classmethod
    def _close_popovers(cls, widget: Gtk.Widget) -> None:
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.MenuButton):
                popover = child.get_popover()
                if popover is not None:
                    try:
                        popover.popdown()
                    except Exception:
                        pass
            cls._close_popovers(child)
            child = child.get_next_sibling()

    def toast(self, message: str) -> None:
        """短暂提示(libadwaita 的 toast);没有 Adw 时忽略。"""
        if self._toast_overlay is None:
            logger.info("toast: %s", message)
            return
        self._toast_overlay.add_toast(Adw.Toast.new(message))

    def refresh_trigger_settings(self, key: str, mode: str) -> None:
        """外部(向导)改了触发键 / 触发方式后,把这两行同步过来。

        不直接 set_selected 之前先比对,避免和 notify::selected 回调互相触发。
        """
        self._trigger_key = key
        self._trigger_mode = "toggle" if mode == "toggle" else "hold"
        if self._trigger_key_row is not None:
            for index, (value, _name) in enumerate(TRIGGER_KEY_CHOICES):
                if value == self._trigger_key:
                    self._trigger_key_row.set_selected(index)
                    break
        if self._trigger_mode_row is not None:
            for index, (value, _name) in enumerate(TRIGGER_MODE_CHOICES):
                if value == self._trigger_mode:
                    self._trigger_mode_row.set_selected(index)
                    break

    # ---- internals ----

    def _ensure_window(self) -> None:
        if self._window is not None:
            return
        if _HAS_ADW:
            try:
                self._ensure_adw_window()
                return
            except Exception:
                # Adw 窗口构建失败(比如系统上的 libadwaita 有坑、组件被裁剪):
                # 退到纯 GTK4 窗口,总比一个窗口都不显示强。
                # (曾经在这里崩掉,结果应用活着却什么都不显示,用户只看到
                #  「启动没反应」。)
                logger.exception("Adw 窗口构建失败,退回纯 GTK4 窗口")
                self._window = None
        self._ensure_legacy_window()

    # ---------- libadwaita:与 Myna Settings 同款 ----------

    def _ensure_adw_window(self) -> None:
        win = Adw.ApplicationWindow(application=self._app)
        win.set_title(_("Doubao Voice Input"))
        win.set_default_size(560, 640)
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
        # 主菜单永远在(语言子菜单与向导/关于无关)。
        header.pack_end(self._build_menu(win))
        toolbar.add_top_bar(header)

        # 内容 = Banner(登录提示)+ ViewStack,外面套 ToastOverlay。
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._banner = Adw.Banner()
        self._banner.set_button_label(_("Sign in"))
        self._banner.set_use_markup(False)
        self._banner.connect("button-clicked", lambda *_: self._on_login())
        content.append(self._banner)

        stack.set_vexpand(True)
        content.append(stack)

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(content)
        toolbar.set_content(self._toast_overlay)

        # --- 账号 ---
        account = Adw.PreferencesPage()
        account.set_title(_("Account"))
        account.set_icon_name("avatar-default-symbolic")
        group = Adw.PreferencesGroup(
            title=_("Doubao Account"),
            description=_(
                "Recognition is done by Doubao's web service; login "
                "credentials are stored only on this machine."
            ),
        )
        account.add(group)

        self._account_row = Adw.ActionRow(title=_("Login status"), subtitle=_("Detecting…"))
        self._account_icon = Gtk.Image.new_from_icon_name(
            _icon_name("content-loading-symbolic", "emblem-synchronizing-symbolic")
        )
        self._account_icon.set_pixel_size(16)
        self._account_row.add_prefix(self._account_icon)
        self._login_button = Gtk.Button.new_with_label(_("Sign in to Doubao"))
        self._login_button.set_valign(Gtk.Align.CENTER)
        self._login_button.add_css_class("suggested-action")
        self._login_button.connect("clicked", lambda *_: self._on_login())
        self._account_row.add_suffix(self._login_button)
        self._account_row.set_activatable_widget(self._login_button)
        group.add(self._account_row)

        creds = Adw.ActionRow(title=_("Credential file"), subtitle=str(get_params_path()))
        creds.set_subtitle_selectable(True)
        copy_path = Gtk.Button.new_with_label(_("Copy"))
        copy_path.set_valign(Gtk.Align.CENTER)
        copy_path.set_tooltip_text(_("Copy credential file path"))
        copy_path.connect("clicked", lambda *_: self._copy_creds_path())
        creds.add_suffix(copy_path)
        creds.set_activatable_widget(copy_path)
        group.add(creds)

        # --- 输入 ---
        input_page = Adw.PreferencesPage()
        input_page.set_title(_("Input"))
        input_page.set_icon_name("input-keyboard-symbolic")
        trigger_group = Adw.PreferencesGroup(
            title=_("Trigger"),
            description=_(
                "Desktop shortcuts may include Super/Ctrl/Alt combos; the "
                "physical key is monitored directly by evdev."
            ),
        )
        input_page.add(trigger_group)

        # 桌面快捷键(Myna 的做法:绑到 D-Bus Toggle)
        self._shortcut_row = Adw.ActionRow(
            title=_("Desktop shortcut"),
            subtitle=_("Writes a custom desktop shortcut whose command is D-Bus Toggle"),
        )
        self._shortcut_widget = _shortcut_widget(self._desktop_shortcut)
        self._shortcut_widget.set_valign(Gtk.Align.CENTER)
        self._shortcut_button = Gtk.Button()
        self._shortcut_button.set_valign(Gtk.Align.CENTER)
        self._shortcut_button.connect("clicked", self._on_shortcut_button)
        self._shortcut_row.add_suffix(self._shortcut_widget)
        self._shortcut_row.add_suffix(self._shortcut_button)
        self._shortcut_row.set_activatable_widget(self._shortcut_button)
        trigger_group.add(self._shortcut_row)
        self._refresh_shortcut_row()

        # 物理键(evdev)
        key_row = Adw.ComboRow(
            title=_("Physical key"),
            subtitle=_("Monitors /dev/input/event* directly; no desktop cooperation needed"),
        )
        key_model = Gtk.StringList.new([_(name) for _key, name in TRIGGER_KEY_CHOICES])
        key_row.set_model(key_model)
        for index, (value, _name) in enumerate(TRIGGER_KEY_CHOICES):
            if value == self._trigger_key:
                key_row.set_selected(index)
        key_row.connect("notify::selected", self._on_trigger_key_selected)
        trigger_group.add(key_row)
        self._trigger_key_row = key_row

        # 触发模式
        mode_row = Adw.ComboRow(
            title=_("Trigger mode"),
        )
        mode_row.set_model(Gtk.StringList.new([_(name) for _key, name in TRIGGER_MODE_CHOICES]))
        mode_row.set_selected(1 if self._trigger_mode == "toggle" else 0)
        mode_row.connect("notify::selected", self._on_trigger_mode_selected)
        trigger_group.add(mode_row)
        self._trigger_mode_row = mode_row

        dictation_group = Adw.PreferencesGroup(title=_("Dictation"))
        input_page.add(dictation_group)

        silence_row = Adw.SpinRow(
            title=_("Auto-stop on silence (seconds)"),
            subtitle=_("0 = never auto-stop (matches Myna's silence-timeout)"),
        )
        silence_row.set_numeric(True)
        adjustment = Gtk.Adjustment(
            value=self._silence_timeout,
            lower=0,
            upper=600,
            step_increment=1,
            page_increment=10,
        )
        try:
            # 长按微调时的加速速率(Gtk.Adjustment 构造参数里没有,得单独设)。
            adjustment.set_climb_rate(1.0)
        except Exception:
            pass
        silence_row.set_adjustment(adjustment)
        silence_row.connect("notify::value", self._on_silence_changed)
        dictation_group.add(silence_row)

        # 焦点离开就结束(可选;探测不到焦点时置灰并说明原因)
        focus_row = Adw.SwitchRow(
            title=_("Stop on focus loss"),
            subtitle=self._focus_loss_reason
            or _("Myna behavior: drops the current dictation as soon as focus leaves"),
        )
        focus_row.set_active(self._stop_on_focus_loss)
        focus_row.set_sensitive(self._focus_loss_supported)
        focus_row.connect("notify::active", self._on_focus_loss_switch)
        dictation_group.add(focus_row)

        # 提示音(Myna 的 sounds:开始 / 结束 / 错误)
        sounds_row = Adw.SwitchRow(
            title=_("Sound effects"),
            subtitle=_("Played on start / stop / error")
            + ("" if self._sounds_supported else _("（no usable player found; silent）")),
        )
        sounds_row.set_active(self._sounds)
        sounds_row.set_sensitive(self._sounds_supported)
        sounds_row.connect("notify::active", self._on_sounds_switch)
        dictation_group.add(sounds_row)

        inject_group = Adw.PreferencesGroup(title=_("Paste method"))
        input_page.add(inject_group)
        shift_row = Adw.SwitchRow(
            title=_("Use Ctrl+Shift+V"),
            subtitle=_("On: pasting also works in terminals; Off: only Ctrl+V in GUI apps"),
        )
        shift_row.set_active(self._inject_shift)
        shift_row.connect("notify::active", self._on_inject_shift_switch)
        inject_group.add(shift_row)

        hud_group = Adw.PreferencesGroup(title=_("Floating window"))
        input_page.add(hud_group)
        if self._on_hud_toggle is not None:
            self._hud_row = Adw.SwitchRow(
                title=_("Use Myna floating capsule"),
                subtitle=_("Rendered by Myna's myna-hud; off falls back to the built-in floating window"),
            )
            self._hud_row.set_active(self._hud_enabled)
            self._hud_row.connect("notify::active", self._on_hud_switch)
            hud_group.add(self._hud_row)

        style_row = Adw.ComboRow(
            title=_("Waveform style"),
            subtitle=_("Myna's hud-style (only affects the Myna capsule)"),
        )
        style_row.set_model(Gtk.StringList.new([_(name) for _key, name in HUD_STYLE_CHOICES]))
        for index, (value, _name) in enumerate(HUD_STYLE_CHOICES):
            if value == self._hud_style:
                style_row.set_selected(index)
        style_row.connect("notify::selected", self._on_hud_style_selected)
        hud_group.add(style_row)
        self._hud_style_row = style_row
        # 波形样式只影响 Myna 胶囊:没开胶囊时置灰,免得用户以为能改内置窗。
        style_row.set_sensitive(self._hud_enabled)

        # 开机自启:状态直接问后端(systemd user service / XDG autostart),
        # 不在 settings.json 里另存一份 —— 用户可能用 systemctl 自己改过。
        startup_group = Adw.PreferencesGroup(title=_("Startup"))
        input_page.add(startup_group)
        autostart_row = Adw.SwitchRow(
            title=_("Start on login"),
            subtitle=self._autostart_reason
            or _("Runs automatically when the desktop session starts"),
        )
        autostart_row.set_active(self._autostart)
        autostart_row.set_sensitive(self._autostart_supported)
        autostart_row.connect("notify::active", self._on_autostart_switch)
        startup_group.add(autostart_row)

        # --- 诊断 ---
        diag = Adw.PreferencesPage()
        diag.set_title(_("Diagnostics"))
        diag.set_icon_name("preferences-system-symbolic")
        self_group = Adw.PreferencesGroup(title=_("Self-check"))
        diag.add(self_group)

        mic_row = Adw.ActionRow(title=_("Microphone"), subtitle=_("Capture 3 seconds and print the RMS peak"))
        mic_button = Gtk.Button.new_with_label(_("Check"))
        mic_button.set_valign(Gtk.Align.CENTER)
        mic_button.connect("clicked", lambda *_: self._on_check_mic())
        mic_row.add_suffix(mic_button)
        mic_row.set_activatable_widget(mic_button)
        self_group.add(mic_row)

        paste_row = Adw.ActionRow(
            title=_("Paste pipeline"), subtitle=_("Injects a fixed text to verify wl-copy + uinput")
        )
        paste_button = Gtk.Button.new_with_label(_("Test"))
        paste_button.set_valign(Gtk.Align.CENTER)
        if self._on_test_inject is not None:
            paste_button.connect("clicked", lambda *_: self._on_test_inject())
        else:
            paste_button.set_sensitive(False)
        paste_row.add_suffix(paste_button)
        paste_row.set_activatable_widget(paste_button)
        self_group.add(paste_row)

        status_group = Adw.PreferencesGroup(title=_("Status"))
        diag.add(status_group)
        self._last_error_row = Adw.ActionRow(title=_("Latest error"), subtitle=_("None"))
        status_group.add(self._last_error_row)

        self._hud_status_row = Adw.ActionRow(title=_("Floating window"), subtitle=_("Disabled"))
        status_group.add(self._hud_status_row)
        self._refresh_last_error()
        self._refresh_hud_status()

        quit_group = Adw.PreferencesGroup(title=_("Application"))
        diag.add(quit_group)
        quit_row = Adw.ActionRow(
            title=_("Quit"),
            subtitle=_("Stop listening and quit completely; closing the window only hides it to the tray"),
        )
        quit_button = Gtk.Button.new_with_label(_("Quit"))
        quit_button.set_valign(Gtk.Align.CENTER)
        quit_button.add_css_class("destructive-action")
        quit_button.connect("clicked", lambda *_: self._on_quit())
        quit_row.add_suffix(quit_button)
        quit_row.set_activatable_widget(quit_button)
        quit_group.add(quit_row)

        # ---- 诊断报告(Myna 的隐私诊断:不含音频/识别文本/文件路径) ----
        report_group = Adw.PreferencesGroup(
            title=_("Diagnostic report"),
            description=_(
                "The report contains no audio, transcribed text, or any "
                "file paths (paths are replaced with [redacted])."
            ),
        )
        diag.add(report_group)

        report_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        # 组标题行会因为描述文字换行而变高,组里的按钮默认会被拉成一样高 ——
        # 显式垂直居中,按钮保持默认高度。
        report_buttons.set_valign(Gtk.Align.CENTER)
        refresh_button = Gtk.Button.new_with_label(_("Refresh"))
        refresh_button.set_valign(Gtk.Align.CENTER)
        refresh_button.set_tooltip_text(_("Re-check local machine and component status"))
        refresh_button.connect("clicked", lambda *_: self._refresh_report())
        report_buttons.append(refresh_button)
        copy_button = Gtk.Button.new_with_label(_("Copy"))
        copy_button.set_valign(Gtk.Align.CENTER)
        copy_button.set_tooltip_text(_("Copy the privacy-safe diagnostic report to the clipboard"))
        copy_button.connect("clicked", lambda *_: self._copy_report())
        report_buttons.append(copy_button)
        try:
            report_group.set_header_suffix(report_buttons)
        except Exception:
            # 老版本 libadwaita 没有 header-suffix,就退化成一行。
            actions = Adw.ActionRow(title=_("Actions"))
            actions.add_suffix(report_buttons)
            report_group.add(actions)

        # 报告区:一个圆角卡片(圆角 + 跟随深浅色主题的底色/边框),高度封顶后
        # 交给页面滚动,避免「页面里套一个滚动区」的双层滚动。
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_max_content_height(320)
        scrolled.set_vexpand(False)
        scrolled.add_css_class("report-card")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            _report_card_css(),
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self._report_view = Gtk.TextView()
        self._report_view.set_editable(False)
        self._report_view.set_cursor_visible(False)
        self._report_view.set_monospace(True)
        self._report_view.set_left_margin(10)
        self._report_view.set_right_margin(10)
        self._report_view.set_top_margin(10)
        self._report_view.set_bottom_margin(10)
        self._report_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scrolled.set_child(self._report_view)
        report_group.add(scrolled)
        self._refresh_report()

        stack.add_titled_with_icon(account, "account", _("Account"), "avatar-default-symbolic")
        stack.add_titled_with_icon(input_page, "input", _("Input"), "input-keyboard-symbolic")
        stack.add_titled_with_icon(diag, "diagnostics", _("Diagnostics"), "preferences-system-symbolic")

        win.connect("close-request", self._on_close_request)
        self._window = win

    # ---------- 退化路径:纯 GTK4 ----------

    def _ensure_legacy_window(self) -> None:
        win = Gtk.ApplicationWindow(application=self._app) if self._app is not None else Gtk.Window()
        win.set_title(_("Doubao Voice Input"))
        win.set_default_size(440, 420)
        win.set_destroy_with_parent(True)
        win.set_icon_name(_ICON_NAME)

        header = Gtk.HeaderBar()
        win.set_titlebar(header)

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

        login_btn = Gtk.Button.new_with_label(_("Sign in to Doubao"))
        login_btn.add_css_class("suggested-action")
        login_btn.connect("clicked", lambda *_: self._on_login())
        box.append(login_btn)

        check_btn = Gtk.Button.new_with_label(_("Check microphone (RMS output)"))
        check_btn.connect("clicked", lambda *_: self._on_check_mic())
        box.append(check_btn)

        test_btn = Gtk.Button.new_with_label(_("Test paste (inject 'hello 测试 123')"))
        if self._on_test_inject is not None:
            test_btn.connect("clicked", lambda *_: self._on_test_inject())
        else:
            test_btn.set_sensitive(False)
        box.append(test_btn)

        # 悬浮窗开关(Myna 胶囊 / 内置悬浮窗)
        if self._on_hud_toggle is not None:
            hud_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            hud_name = Gtk.Label(label=_("Use Myna floating capsule"))
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
            self._hud_status_label.add_css_class("dim-label")
            box.append(self._hud_status_label)
            self._refresh_hud_status()

        # 开机自启(与 Adw 路径共用同一个回调,失败同样回拨 + toast)
        if self._on_autostart_changed is not None:
            auto_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            auto_name = Gtk.Label(label=_("Start on login"))
            auto_name.set_xalign(0.0)
            auto_name.set_hexpand(True)
            auto_switch = Gtk.Switch()
            auto_switch.set_active(self._autostart)
            auto_switch.set_sensitive(self._autostart_supported)
            auto_switch.set_valign(Gtk.Align.CENTER)
            auto_switch.connect("state-set", self._on_autostart_switch)
            auto_box.append(auto_name)
            auto_box.append(auto_switch)
            box.append(auto_box)

        help = Gtk.Label()
        help.set_xalign(0.0)
        help.set_wrap(True)
        help.add_css_class("dim-label")
        help.set_markup(
            _("<b>Note</b>\n• In terminal, manually use Ctrl+Shift+V\n• Credentials stored at %s\n")
            % get_params_path()
        )
        box.append(help)

        quit_btn = Gtk.Button.new_with_label(_("Quit"))
        quit_btn.add_css_class("destructive-action")
        quit_btn.connect("clicked", lambda *_: self._on_quit())
        box.append(quit_btn)

        win.set_child(box)
        win.connect("close-request", self._on_close_request)
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
        # 波形样式只对 Myna 胶囊有意义,跟着开关置灰。
        if self._hud_style_row is not None:
            self._hud_style_row.set_sensitive(self._hud_enabled)
        GLib.timeout_add(300, lambda: (self._refresh_hud_status(), False)[1])
        return False

    def _on_inject_shift_switch(self, row, _param) -> None:
        active = bool(row.get_active())
        self._inject_shift = active
        if self._on_inject_shift_toggle is not None:
            self._on_inject_shift_toggle(active)

    def _build_menu(self, win: Gtk.Window) -> Gtk.MenuButton:
        """主菜单:Gio.Menu + Gtk.MenuButton(Adw 风格,自带键盘导航与高亮)。

        文案走 i18n(源码英文,中文由 locale/*.po 提供);「语言」子菜单用来
        切换界面语言。
        """
        button = Gtk.MenuButton()
        button.set_icon_name("open-menu-symbolic")
        button.set_tooltip_text(_("Main Menu"))

        if self._on_run_onboarding is not None:
            action = Gio.SimpleAction.new("onboarding", None)
            action.connect("activate", lambda *_: self._on_run_onboarding())
            win.add_action(action)
        if self._on_about is not None:
            action = Gio.SimpleAction.new("about", None)
            action.connect("activate", lambda *_: self._on_about())
            win.add_action(action)
        # 语言切换:带字符串参数的动作,目标值就是语言代码。
        language = Gio.SimpleAction.new("language", GLib.VariantType("s"))
        language.connect("activate", self._on_language_activated)
        win.add_action(language)

        menu = Gio.Menu()
        section = Gio.Menu()
        if self._on_run_onboarding is not None:
            section.append(_("Run Setup Wizard…"), "win.onboarding")
        if self._on_about is not None:
            section.append(_("About %s") % _("Doubao Voice Input"), "win.about")
        menu.append_section(None, section)
        menu.append_section(_("Language"), self._build_language_menu())
        button.set_menu_model(menu)
        return button

    def _build_language_menu(self) -> Gio.Menu:
        """语言子菜单。

        语言名一律用**各自语言自己的写法**(English / 简体中文 / 繁體中文,
        GNOME「区域与语言」的惯例),所以这里不需要翻译;当前语言在标签前
        加一个勾。

        注:试过用 Gio.MenuItem 的 "icon" 属性(配 object-select-symbolic)
        打勾,实测 **Gtk.PopoverMenu 根本不渲染普通条目的 icon**
        (Image 的 visible=False、宽高 0),所以退回文本前缀。
        """
        submenu = Gio.Menu()
        current = i18n.current()
        for code, name in LANGUAGES.items():
            item = Gio.MenuItem()
            item.set_label(f"✓ {name}" if code == current else name)
            item.set_action_and_target_value("win.language", GLib.Variant("s", code))
            submenu.append_item(item)
        return submenu

    def _on_language_activated(self, _action, parameter) -> None:
        code = parameter.get_string() if parameter is not None else ""
        self.set_language(code)

    def set_language(self, code: str) -> None:
        """切换界面语言:记住选择 → 立即生效 → 重建界面。

        界面字符串是**建窗口时**就定死的,所以只能把窗口拆了重建
        (toast 用的是新语言,正好当切换成功的反馈)。
        """
        if code not in LANGUAGES:
            return
        save_language(code)
        i18n.switch([code])
        logger.info("language switched to %s", code)
        # 首次运行向导(如果开着)是另一套窗口,让 app 去重建它。
        if self._on_language_changed is not None:
            try:
                self._on_language_changed()
            except Exception as e:
                logger.warning("language change callback failed: %s", e)
        self.destroy()
        self.show()
        self.toast(_("Interface language: %s") % LANGUAGES[code])

    def _on_run_onboarding_clicked(self, *_args) -> None:
        if self._on_run_onboarding is not None:
            self._on_run_onboarding()

    def _on_about_clicked(self, *_args) -> None:
        if self._on_about is not None:
            self._on_about()

    # ---- 快捷键(Myna 风格:键帽 + 捕获) ----

    def _refresh_shortcut_row(self) -> None:
        if self._shortcut_widget is None or self._shortcut_button is None:
            return
        binding = self._desktop_shortcut
        # 快捷键(或「未设置」)直接写进副标题,键帽不再单独显示。
        self._shortcut_widget.set_visible(False)
        self._shortcut_button.set_label(_("Change") if binding else _("Set"))
        if not self._desktop_shortcut_supported:
            _set_subtitle(
                self._shortcut_row,
                _(
                    "Current desktop does not support writing custom "
                    "shortcuts (needs GNOME or Xfce)"
                ),
            )
            self._shortcut_button.set_sensitive(False)
        else:
            base = _("Writes a custom desktop shortcut whose command is D-Bus Toggle")
            head = _accelerator_label(binding) if binding else _("Not set")
            _set_subtitle(self._shortcut_row, f"{head} · {base}")

    def _copy_creds_path(self) -> None:
        if _copy_text(str(get_params_path())):
            self.toast(_("Credential path copied"))
        else:
            self.toast(_("Copy failed"))

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
            self.toast(_("%s is reserved by the desktop (%s); pick another") % (accelerator, owner))
            return
        if not _HAS_ADW or self._window is None:
            self.toast(_("%s is already taken by “%s”") % (accelerator, owner))
            return

        dialog = Adw.AlertDialog.new(
            _("Replace shortcut?"),
            _("%s is already used by “%s”. Replacing removes it from there.") % (accelerator, owner),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("replace", _("Replace"))
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
            self.toast(_("Shortcut set to %s") % accelerator)
        else:
            self.toast(_("Failed to set shortcut: %s") % error)

    # ---- 触发 / 听写设置 ----

    def _on_trigger_key_selected(self, row, _param) -> None:
        index = row.get_selected()
        if index < 0 or index >= len(TRIGGER_KEY_CHOICES):
            return
        value = TRIGGER_KEY_CHOICES[index][0]
        # 外部(向导)同步过来的同值不再回调,免得反复重启 evdev 监听。
        if value == self._trigger_key:
            return
        self._trigger_key = value
        if self._on_trigger_key_changed is not None:
            self._on_trigger_key_changed(value)

    def _on_trigger_mode_selected(self, row, _param) -> None:
        index = row.get_selected()
        if index < 0 or index >= len(TRIGGER_MODE_CHOICES):
            return
        mode = TRIGGER_MODE_CHOICES[index][0]
        if mode == self._trigger_mode:
            return
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

    def _on_autostart_switch(self, row, *args) -> bool:
        """开机自启开关。写后端是可能失败的(systemd 不可用、目录不可写),
        失败要把开关拨回去并告诉用户原因 —— 否则界面显示「开」而实际没开。

        Gtk.Switch 的 state-set 在状态翻转**之前**触发,所以新值取信号参数;
        回拨统一丢进 idle,等当前这轮信号走完再动,免得和 GTK 自己的状态
        更新打架。
        """
        if self._autostart_updating:
            return False
        if isinstance(row, Gtk.Switch):
            active = bool(args[0]) if args else row.get_active()
        else:
            active = row.get_active()
        ok, error = True, ""
        if self._on_autostart_changed is not None:
            try:
                ok, error = self._on_autostart_changed(bool(active))
            except Exception as e:
                logger.exception("autostart toggle failed")
                ok, error = False, str(e)
        if ok:
            self._autostart = bool(active)
            return False
        self._autostart = not active
        self._autostart_updating = True
        GLib.idle_add(self._revert_autostart_switch, row, not active)
        self.toast(_("Failed to change autostart: %s") % error)
        return False

    def _revert_autostart_switch(self, row, active: bool) -> bool:
        try:
            row.set_active(bool(active))
        finally:
            self._autostart_updating = False
        return GLib.SOURCE_REMOVE

    def _on_hud_style_selected(self, row, _param) -> None:
        index = row.get_selected()
        if index < 0 or index >= len(HUD_STYLE_CHOICES):
            return
        value = HUD_STYLE_CHOICES[index][0]
        self._hud_style = value
        if self._on_hud_style_changed is not None:
            self._on_hud_style_changed(value)

    def _refresh_last_error(self) -> None:
        if self._last_error_row is None:
            return
        if self._last_error is None:
            _set_subtitle(self._last_error_row, _("None"))
            return
        try:
            _set_subtitle(self._last_error_row, self._last_error())
        except Exception as e:
            _set_subtitle(self._last_error_row, _("Unknown (%s)") % e)

    # ---- 诊断报告(Myna 的隐私诊断) ----

    def _refresh_report(self) -> None:
        if self._report_view is None:
            return
        try:
            text = self._report() if self._report is not None else ""
        except Exception as e:
            logger.warning("diagnostics report failed: %s", e)
            text = _("Failed to generate diagnostic report: %s") % e
        self._report_view.get_buffer().set_text(text)

    def _copy_report(self) -> None:
        if self._report_view is None:
            return
        buffer = self._report_view.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        if _copy_text(text):
            self.toast(_("Diagnostic report copied to clipboard"))
        else:
            self.toast(_("Copy failed"))

    def _refresh_hud_status(self) -> None:
        if self._hud_status_row is not None:
            if self._hud_status is None:
                _set_subtitle(self._hud_status_row, _("Disabled"))
                return
            try:
                _set_subtitle(self._hud_status_row, self._hud_status())
            except Exception as e:
                _set_subtitle(self._hud_status_row, _("Floating window status unknown (%s)") % e)
            return
        if not self._hud_status_label:
            return
        if self._hud_status is None:
            self._hud_status_label.set_text(_("Disabled"))
            return
        try:
            self._hud_status_label.set_markup(
                f"<small>{GLib.markup_escape_text(self._hud_status())}</small>"
            )
        except Exception as e:
            self._hud_status_label.set_text(_("Floating window status unknown (%s)") % e)

    def _on_status_changed(self, *_args) -> None:
        self._refresh_status()

    def _refresh_status(self) -> None:
        status = self._app_state.login_status
        if status == LoginStatus.LOGGED_IN:
            # emblem-ok-symbolic 只有 Yaru 有,Adwaita 主题下会画成白块,
            # 所以优先用 object-select-symbolic。
            text, icon = _("Signed in"), _icon_name(
                "object-select-symbolic", "emblem-ok-symbolic"
            )
        elif status == LoginStatus.NOT_LOGGED_IN:
            text, icon = _("Not signed in · click “Sign in to Doubao” to log in once"), "dialog-warning-symbolic"
        else:
            text, icon = _("Detecting…"), _icon_name(
                "content-loading-symbolic", "emblem-synchronizing-symbolic"
            )

        if self._status_label is not None:  # 退化路径
            if status == LoginStatus.LOGGED_IN:
                self._status_label.set_markup(_("Status: <b>Signed in</b>  ✅"))
            elif status == LoginStatus.NOT_LOGGED_IN:
                self._status_label.set_markup(
                    _("Status: <b>Not signed in</b>  ❌\nClick “Sign in to Doubao” to log in once.")
                )
            else:
                self._status_label.set_markup(_("Status: <b>Detecting…</b>"))
            return

        if self._account_row is None:
            return
        _set_subtitle(self._account_row, text)
        if self._login_button is not None:
            self._login_button.set_label(
                _("Sign in again") if status == LoginStatus.LOGGED_IN else _("Sign in to Doubao")
            )
            # 强调色只留给「还没登录、需要用户去登录」的状态;
            # 已登录后的「重新登录」是次要操作,不该再抢眼。
            if status == LoginStatus.NOT_LOGGED_IN:
                self._login_button.add_css_class("suggested-action")
            else:
                self._login_button.remove_css_class("suggested-action")
        self._account_icon.set_from_icon_name(icon)

        # 没登录时在窗口顶部挂一条可点的横幅(Adw.Banner),别让用户去猜。
        if self._banner is not None:
            if status == LoginStatus.NOT_LOGGED_IN:
                self._banner.set_title(
                    _("Not signed in to Doubao yet; holding Right Ctrl won't trigger recognition")
                )
                self._banner.set_revealed(True)
            else:
                self._banner.set_revealed(False)
