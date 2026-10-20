"""Main GtkApplication: orchestrates trigger, ASR, overlay, injector, login.

Lifecycle:
  1. On first activate: build all components. Show login window if no
     saved credentials; otherwise just start the PTT listener and
     show the control window.
  2. On subsequent activate (single-instance re-launch via the desktop
     entry or `python -m doubao_input` again): just present the control
     window.
  3. Quit: stop everything cleanly.
"""
from __future__ import annotations

import logging
import os
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # type: ignore

from doubao_input.doubao.app_state import AppState, LoginStatus, RecordingState
from doubao_input.doubao.asr_client import ASRClient
from doubao_input.doubao.audio_capture import AudioCapture
from doubao_input.doubao.config import (
    CANCEL_KEY_NAME,
    FOCUS_CONFIRM_TICKS,
    FOCUS_POLL_SECS,
    PASTE_DELAY,
    SILENCE_RMS_THRESHOLD,
)
from doubao_input.doubao.params_store import ParamsStore
from doubao_input.doubao.transcription import TranscriptionManager
from doubao_input.hud.bridge import MynaHudBridge
from doubao_input.hud.settings import (
    load_desktop_shortcut,
    load_enabled,
    load_hud_style,
    load_inject_shift,
    load_silence_timeout,
    load_sounds,
    load_stop_on_focus_loss,
    load_trigger_key,
    load_trigger_mode,
    save_desktop_shortcut,
    save_enabled,
    save_hud_style,
    save_inject_shift,
    save_silence_timeout,
    save_sounds,
    save_stop_on_focus_loss,
    save_trigger_key,
    save_trigger_mode,
)
from doubao_input.hud.wire import IDLE, LOADING, NOTICE, RECORDING, STATUS_EMPTY
from doubao_input.inject.injector import Injector
from doubao_input.trigger.desktop_shortcut import DesktopShortcut
from doubao_input.trigger.evdev_ptt import EvdevPtt
from doubao_input.ui.control_window import ControlWindow
from doubao_input.ui.focus_watch import focused_identity, reason, supported
from doubao_input.ui.notifier import Notifier
from doubao_input.ui.overlay import Overlay
from doubao_input.ui.sounds import Sounds

logger = logging.getLogger(__name__)


class DoubaoInputApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="com.doubao.Input",
            flags=Gio_APPLICATION_NON_UNIQUE(),
        )
        # PyGObject does NOT dispatch do_activate() automatically in all
        # versions — connect the signal explicitly so the first run
        # actually shows the UI.
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)
        self._setup_done = False
        self.app_state = AppState()
        self._overlay: Overlay | None = None
        self._control: ControlWindow | None = None
        self._login_window = None
        self._ptt: EvdevPtt | None = None
        self._tm: TranscriptionManager | None = None
        self._injector: Injector | None = None
        self._last_press_at: float = 0.0
        # Myna 悬浮胶囊前端(self._hud 存在 != 生效:渲染器没起来就退回内置悬浮窗)
        self._hud: MynaHudBridge | None = None
        self._use_hud = False
        self._inject_shift = load_inject_shift()
        # ---- 触发配置(与 Myna 对齐:按键可配 + 可选桌面快捷键) ----
        self._trigger_key = load_trigger_key()
        self._trigger_mode = load_trigger_mode()
        self._silence_timeout = load_silence_timeout()
        self._desktop_shortcut = load_desktop_shortcut()
        self._shortcut = DesktopShortcut()
        self._stop_on_focus_loss = load_stop_on_focus_loss()
        self._sounds = Sounds(load_sounds())
        self._notifier: Notifier | None = None
        self._last_voice_at = 0.0
        self._silence_timer = 0
        self._focus_timer = 0
        self._focus_change_count = 0
        self._session_focus: str | None = None

    # ---- Gtk.Application hooks (signal handlers, not do_*) ----

    def _on_activate(self, _app) -> None:
        logger.info("on_activate: setup_done=%s", self._setup_done)
        if not self._setup_done:
            self._setup_done = True
            self._build()
        if self._control:
            self._control.show()
        # Boot-time proof-of-life: briefly flash the floating overlay so
        # the user can see *something* from this app even before they log
        # in. This is the "弹出输入法" signal. Hide it 3 seconds later.
        from gi.repository import GLib
        GLib.timeout_add(400, self._boot_flash_overlay)

    def _boot_flash_overlay(self) -> bool:
        message = "豆包输入法已启动 · 请登录或按住右 Ctrl 说话"
        if self._use_hud and self._hud is not None:
            self._hud.flash(NOTICE, message, 3000)
            return False
        if self._overlay is None:
            return False
        self._overlay.show(message)
        GLib.timeout_add_seconds(3, lambda: (self._overlay.hide(), False)[1])
        return False

    def _on_shutdown(self, _app) -> None:
        logger.info("shutting down")
        if self._hud:
            self._hud.close()
            self._hud = None
        if self._ptt:
            self._ptt.stop()
        if self._injector:
            self._injector.close()

    # ---- Myna HUD 前端 ----

    def _start_hud(self) -> bool:
        """启动 Myna 悬浮胶囊。拿不到 D-Bus 名字或拉不起渲染器就退回内置悬浮窗。"""
        if self._hud is not None:
            self._hud.close()
            self._hud = None
        self._hud = MynaHudBridge(
            self.app_state,
            on_press=self._on_ptt_press,
            on_release=self._on_ptt_release,
            on_failed=self._on_hud_failed,
        )
        self._use_hud = self._hud.start() and self._hud.active
        self._hud.set_style(load_hud_style())
        if self._use_hud:
            logger.info("Myna HUD ready: %s", self._hud.renderer_status())
        else:
            logger.warning(
                "Myna HUD 不可用,沿用内置悬浮窗: %s", self._hud.renderer_status()
            )
        return self._use_hud

    def _on_hud_failed(self, message: str) -> None:
        logger.error("Myna HUD 失效,回退到内置悬浮窗: %s", message)
        self._use_hud = False

    def _hud_status(self) -> str:
        return self._hud.renderer_status() if self._hud is not None else "未启用"

    def set_inject_shift(self, enabled: bool) -> None:
        """控制窗口的粘贴方式开关(Ctrl+Shift+V / Ctrl+V)。"""
        self._inject_shift = bool(enabled)
        save_inject_shift(self._inject_shift)

    def set_hud_enabled(self, enabled: bool) -> None:
        """控制窗口开关:实时切换指示器并记住选择。"""
        save_enabled(enabled)
        if enabled:
            self._start_hud()
        else:
            if self._hud is not None:
                self._hud.close()
                self._hud = None
            self._use_hud = False

    def set_hud_style(self, nick: str) -> None:
        """胶囊波形样式:bar / ribbon / vumeter。"""
        save_hud_style(nick)
        if self._hud is not None:
            self._hud.set_style(nick)

    # ---- 触发配置(与 Myna 对齐) ----

    def set_trigger_key(self, key_name: str) -> None:
        """物理键(evdev 键名)。改完立刻重启监听线程。"""
        save_trigger_key(key_name)
        self._trigger_key = key_name
        self._restart_ptt()

    def set_trigger_mode(self, mode: str) -> None:
        """hold = 按住说话(豆包原生);toggle = 按一下开/再按一下停(Myna)。"""
        self._trigger_mode = "toggle" if mode == "toggle" else "hold"
        save_trigger_mode(self._trigger_mode)
        logger.info("trigger mode: %s", self._trigger_mode)

    def set_silence_timeout(self, seconds: int) -> None:
        """静音多少秒自动结束;0 = 不自动结束(对齐 Myna 的 silence-timeout)。"""
        self._silence_timeout = max(0, min(600, int(seconds)))
        save_silence_timeout(self._silence_timeout)

    def set_desktop_shortcut(self, accelerator: str) -> tuple[bool, str]:
        """往桌面写自定义快捷键(命令是 D-Bus Toggle,和 Myna 一样)。"""
        if not accelerator:
            self._shortcut.clear()
            self._desktop_shortcut = ""
            save_desktop_shortcut("")
            return True, ""
        ok, error = self._shortcut.bind(accelerator)
        if ok:
            self._desktop_shortcut = accelerator
            save_desktop_shortcut(accelerator)
            logger.info("desktop shortcut bound to %s", accelerator)
        return ok, error

    def desktop_shortcut(self) -> str:
        """桌面上实际生效的快捷键(以桌面里的为准)。"""
        return self._shortcut.binding() or self._desktop_shortcut

    def desktop_shortcut_supported(self) -> bool:
        return self._shortcut.available()

    def _restart_ptt(self) -> None:
        if self._ptt is None:
            return
        try:
            self._ptt.stop()
        except Exception:
            pass
        self._ptt = EvdevPtt(
            on_press=self._on_ptt_press,
            on_release=self._on_ptt_release,
            on_error=self._on_ptt_error,
            key_name=self._trigger_key,
            cancel_key_name=CANCEL_KEY_NAME,
            on_cancel=self._on_cancel_key,
        )
        try:
            if not self._ptt.start():
                logger.warning("evdev PTT 未启动(键=%s)", self._trigger_key)
        except Exception as e:
            logger.warning("evdev PTT failed: %s", e)

    # ---- 指示器路由(内置悬浮窗 / Myna 胶囊二选一) ----

    def _indicator_show(self, wire_state: str, message: str) -> None:
        if self._hud is not None:
            self._hud.set_state(wire_state, message)
        if not self._use_hud:
            if self._overlay is not None:
                self._overlay.show(message)
            # 胶囊没起来时,状态至少要在通知里看得见(Myna 的兜底)。
            if self._notifier is not None:
                self._notifier.set_state(wire_state, message)

    def _indicator_text(self, message: str) -> None:
        if self._hud is not None:
            self._hud.set_state(RECORDING, message)
        if self._overlay is not None and not self._use_hud:
            self._overlay.set_text(message)

    def _indicator_notice(self, message: str) -> None:
        """可恢复提示(对齐 Myna 的 notice):不是错误,几秒后自己消失。"""
        if self._use_hud and self._hud is not None:
            self._hud.notice(message)
        else:
            if self._overlay is not None:
                self._overlay.show(message)
                GLib.timeout_add_seconds(2, lambda: (self._overlay.hide(), False)[1])
            if self._notifier is not None:
                self._notifier.set_state(NOTICE, message)

    def _indicator_hide(self) -> None:
        if self._hud is not None:
            self._hud.idle()
        if not self._use_hud:
            if self._overlay is not None:
                self._overlay.hide()
            if self._notifier is not None:
                self._notifier.set_state(IDLE, "")

    def _push_rms(self, rms: float) -> None:
        """麦克风 RMS 回调(音频线程)。这里只写值,不碰 GTK。"""
        if rms >= SILENCE_RMS_THRESHOLD:
            self._last_voice_at = time.monotonic()
        if self._hud is not None:
            self._hud.push_level(rms)
        if self._overlay is not None and not self._use_hud:
            self._overlay.push_rms(rms)

    # ---- build ----

    def _build(self) -> None:
        self._overlay = Overlay()
        self._injector = Injector()
        # 胶囊没起来时的兜底:状态走桌面通知(Myna 的 NotifyIndicator)。
        self._notifier = Notifier(self)
        # 任何错误都出一声(Myna:严重错误必播 Error)。
        self.app_state.connect("error-message-changed", self._on_error_message)

        # ---- Myna HUD:桌面上那个胶囊可以换成 Myna 的渲染器 ----
        if load_enabled():
            self._start_hud()

        # ---- TranscriptionManager (state machine) ----
        tm = TranscriptionManager(self.app_state)
        # Replace its audio_capture with our instance so we can wire RMS
        from doubao_input.doubao.audio_capture import AudioCapture
        self._audio_capture = AudioCapture()
        tm.audio_capture = self._audio_capture

        # Wrap start() so that on every recording, RMS is piped to the
        # overlay (waveform). Wrapping is safer than monkey-patching the
        # class globally.
        _ac_orig_start = self._audio_capture.start
        def _start_with_rms(on_audio_data):
            _ac_orig_start(on_audio_data)
            self._audio_capture._on_rms = self._push_rms
        self._audio_capture.start = _start_with_rms  # type: ignore[assignment]
        _ac_orig_stop = self._audio_capture.stop
        def _stop_clear_rms():
            _ac_orig_stop()
            self._audio_capture._on_rms = None
        self._audio_capture.stop = _stop_clear_rms  # type: ignore[assignment]

        tm.on_show_login = self._show_login
        tm.on_overlay_show = lambda: self._indicator_show(
            LOADING, "正在启动语音识别…"
        )
        tm.on_overlay_hide = self._indicator_hide
        tm.on_overlay_update = lambda text: self._indicator_text(text)
        tm.on_paste = self._do_paste
        tm.on_empty_result = self._on_empty_result
        tm.on_cancel_enabled_changed = lambda enabled: None
        tm.on_auth_expired = self._on_auth_expired
        tm.on_params_needed = self._provide_params
        self._tm = tm

        # ---- Control window ----
        self._control = ControlWindow(
            app_state=self.app_state,
            on_login_clicked=self._show_login,
            on_quit_clicked=self._quit,
            on_check_mic_clicked=self._check_mic,
            on_test_inject_clicked=self._test_inject,
            app=self,
            hud_enabled=self._use_hud,
            on_hud_toggle=self.set_hud_enabled,
            hud_status=self._hud_status,
            inject_shift=self._inject_shift,
            on_inject_shift_toggle=self.set_inject_shift,
            trigger_key=self._trigger_key,
            on_trigger_key_changed=self.set_trigger_key,
            trigger_mode=self._trigger_mode,
            on_trigger_mode_changed=self.set_trigger_mode,
            silence_timeout=self._silence_timeout,
            on_silence_timeout_changed=self.set_silence_timeout,
            hud_style=load_hud_style(),
            on_hud_style_changed=self.set_hud_style,
            desktop_shortcut=self.desktop_shortcut(),
            desktop_shortcut_supported=self.desktop_shortcut_supported(),
            on_desktop_shortcut_changed=self.set_desktop_shortcut,
            stop_on_focus_loss=self._stop_on_focus_loss,
            focus_loss_supported=self.focus_loss_supported(),
            focus_loss_reason=self.focus_loss_reason(),
            on_stop_on_focus_loss_changed=self.set_stop_on_focus_loss,
            sounds=self._sounds.enabled,
            sounds_supported=self._sounds.available,
            on_sounds_changed=self.set_sounds,
        )

        # ---- Initial state: cached params? ----
        if ParamsStore.has_saved():
            self.app_state.login_status = LoginStatus.LOGGED_IN
        else:
            self.app_state.login_status = LoginStatus.NOT_LOGGED_IN

        # ---- PTT trigger ----
        self._ptt = EvdevPtt(
            on_press=self._on_ptt_press,
            on_release=self._on_ptt_release,
            on_error=self._on_ptt_error,
            key_name=self._trigger_key,
            cancel_key_name=CANCEL_KEY_NAME,
            on_cancel=self._on_cancel_key,
        )
        try:
            started = self._ptt.start()
        except Exception as e:
            # 缺 evdev / 没进 input 组都走这里:热键没了,但控制窗口和
            # HUD 还得起来,否则用户没法诊断。
            started = False
            logger.warning("evdev PTT failed: %s", e)
        if not started:
            logger.warning("evdev PTT failed to start; will retry in background")
            # Don't block; user can still open the control window to diagnose.

        logger.info("build complete")

    # ---- PTT callbacks (run on GTK main thread) ----

    def _on_ptt_press(self) -> None:
        if not self._tm:
            return
        if self.app_state.login_status != LoginStatus.LOGGED_IN:
            self._not_logged_in()
            return
        if self._trigger_mode == "toggle":
            # Myna 的交互:按一下开始,再按一下结束。
            if self.app_state.recording_state == RecordingState.IDLE:
                self._start_session()
            else:
                self._stop_session()
            return
        self._start_session()

    def _on_ptt_release(self) -> None:
        if not self._tm:
            return
        if self.app_state.login_status != LoginStatus.LOGGED_IN:
            self._indicator_hide()
            return
        if self._trigger_mode == "toggle":
            return  # toggle 模式下松键不做事
        self._stop_session()

    def _not_logged_in(self) -> None:
        if self._use_hud and self._hud is not None:
            self._hud.notice("请先在控制窗口登录豆包")
        elif self._overlay is not None:
            self._overlay.set_text("请先在控制窗口完成登录")
            self._overlay.show("未登录")

    def _start_session(self) -> None:
        if not self._tm:
            return
        self._last_voice_at = time.monotonic()
        self._tm.handle_press()
        self._sounds.play("start")  # Myna:按下即播,不等后端就绪
        self._start_silence_watch()
        self._start_focus_watch()

    def _stop_session(self) -> None:
        if not self._tm:
            return
        self._stop_silence_watch()
        self._stop_focus_watch()
        self._tm.handle_release()
        self._sounds.play("stop")

    def _on_cancel_key(self) -> None:
        """会话中按 ESC(可配):取消,丢弃本次内容。"""
        if not self._tm or self.app_state.recording_state == RecordingState.IDLE:
            return
        logger.info("取消键:丢弃本次听写")
        self._stop_silence_watch()
        self._stop_focus_watch()
        self._tm.handle_cancel()
        self._sounds.play("stop")
        self._indicator_notice("已取消本次听写")

    def _on_error_message(self, _state, value: str) -> None:
        if value:
            self._sounds.play("error")

    def set_sounds(self, enabled: bool) -> None:
        """开始 / 结束 / 错误提示音开关(Myna 的 sounds)。"""
        self._sounds.enabled = bool(enabled)
        save_sounds(self._sounds.enabled)

    # ---- 焦点离开就结束(可选开关,对齐 Myna 的 Focus lost) ----

    def set_stop_on_focus_loss(self, enabled: bool) -> None:
        self._stop_on_focus_loss = bool(enabled)
        save_stop_on_focus_loss(self._stop_on_focus_loss)
        if not enabled:
            self._stop_focus_watch()

    def focus_loss_supported(self) -> bool:
        return supported()

    def focus_loss_reason(self) -> str:
        return reason()

    def _start_focus_watch(self) -> None:
        if not self._stop_on_focus_loss or not supported() or self._focus_timer:
            return
        self._session_focus = focused_identity()
        self._focus_change_count = 0
        if not self._session_focus:
            logger.info("焦点探测拿不到窗口标识,本次不监视焦点")
            return
        self._focus_timer = GLib.timeout_add_seconds(
            max(1, FOCUS_POLL_SECS), self._focus_tick
        )

    def _stop_focus_watch(self) -> None:
        if self._focus_timer:
            GLib.source_remove(self._focus_timer)
            self._focus_timer = 0
        self._session_focus = None

    def _focus_tick(self) -> bool:
        if self.app_state.recording_state == RecordingState.IDLE:
            self._focus_timer = 0
            return GLib.SOURCE_REMOVE
        current = focused_identity()
        if current and self._session_focus and current != self._session_focus:
            # X11/XWayland 下这个 id 偶尔会抖,连续两次都是新值才认定焦点真走了。
            self._focus_change_count += 1
            if self._focus_change_count < FOCUS_CONFIRM_TICKS:
                return GLib.SOURCE_CONTINUE
            logger.info("焦点已离开(→ %s),结束本次听写", current)
            self._stop_focus_watch()
            self._stop_silence_watch()
            if self._tm is not None:
                # Myna 的语义:焦点丢失时**丢弃**已识别的文本,不注入。
                self._tm.handle_cancel()
            self._indicator_notice("焦点已离开,本次未输入")
            return GLib.SOURCE_REMOVE
        self._focus_change_count = 0
        return GLib.SOURCE_CONTINUE

    # ---- 静音自动结束(Myna 的 silence-timeout) ----

    def _start_silence_watch(self) -> None:
        if self._silence_timeout <= 0 or self._silence_timer:
            return
        self._silence_timer = GLib.timeout_add_seconds(1, self._silence_tick)

    def _stop_silence_watch(self) -> None:
        if self._silence_timer:
            GLib.source_remove(self._silence_timer)
            self._silence_timer = 0

    def _silence_tick(self) -> bool:
        state = self.app_state.recording_state
        if state == RecordingState.IDLE:
            self._silence_timer = 0
            return GLib.SOURCE_REMOVE
        if self._last_voice_at:
            silent_for = time.monotonic() - self._last_voice_at
            if silent_for >= self._silence_timeout:
                logger.info("静音 %.0fs,自动结束(对齐 Myna 的 silence-timeout)", silent_for)
                self._stop_silence_watch()
                if self._tm is not None:
                    self._tm.handle_release()
                return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _on_empty_result(self) -> None:
        """说完但没识别到内容 → 可恢复提示(Myna 的 “No speech detected”)。"""
        self._indicator_notice(STATUS_EMPTY)

    def _on_ptt_error(self, msg: str) -> None:
        logger.warning("PTT error: %s", msg)

    # ---- Paste ----

    def _do_paste(self, text: str) -> None:
        logger.info("_do_paste called, text=%r (len=%d)", text[:30], len(text))
        if not self._injector:
            logger.warning("no injector; paste skipped")
            return
        # Myna 胶囊也要先消失,否则注入的 Ctrl+V 会落到我们的窗口上。
        if self._hud is not None:
            self._hud.set_state(IDLE, "")
        # CRITICAL: hide BOTH our windows so the injected Ctrl+V goes
        # to whatever input field the user had focused before pressing
        # right-Ctrl, not to our own widgets. On Wayland, focus
        # follows the compositor; the only reliable way to release
        # focus is to take the window off the screen.
        if self._overlay is not None and self._overlay._window:
            try:
                self._overlay._window.set_visible(False)
            except Exception:
                pass
        # Track whether we had to forcibly hide the control window so
        # we can restore it after the paste.
        control_was_visible = False
        if self._control and self._control._window:
            try:
                control_was_visible = self._control._window.get_visible()
                if control_was_visible:
                    self._control._window.set_visible(False)
            except Exception:
                control_was_visible = False

        def do_inject():
            logger.info("_do_paste: now injecting %r", text[:30])
            ok = self._injector.inject(text, use_shift=self._inject_shift)
            logger.info("_do_paste: injector.inject returned %s", ok)
            if not ok:
                # Myna 的原则:失败要作为本次的错误上报,绝不静默丢字。
                self._indicator_notice("粘贴失败,文字仍在剪贴板,可手动 Ctrl+Shift+V")
                if self._control is not None:
                    self._control.toast("粘贴失败,文字仍在剪贴板")
            # Restore control window
            def restore_control():
                if (
                    control_was_visible
                    and self._control
                    and self._control._window
                ):
                    try:
                        self._control._window.set_visible(True)
                    except Exception:
                        pass
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(600, restore_control)
            return GLib.SOURCE_REMOVE

        # Wait for the right-Ctrl physical release + the compositor to
        # hand focus back to the user's window, THEN inject.
        GLib.timeout_add(int((PASTE_DELAY + 0.10) * 1000), do_inject)

    def _test_inject(self) -> None:
        """Diagnostic: inject a fixed string via the same code path the
        voice pipeline uses. Used by the 「测试粘贴」 button so the user
        can verify wl-copy + uinput Ctrl+V without logging in first."""
        logger.info("_test_inject: clicked 测试粘贴 button")
        if self._control is not None:
            self._control.toast("正在注入 'hello 测试 123'…")
        # Use the same focus-management code path as _do_paste so we
        # can be confident the test matches production behaviour.
        self._do_paste("hello 测试 123\n")

    # ---- Login ----

    def _show_login(self) -> None:
        from doubao_input.doubao.login_window import LoginWindow
        if self._login_window is None:
            lw = LoginWindow(self.app_state)
            lw._on_login_status_change = self._on_login_detected
            self._login_window = lw
        self._login_window.show()

    def _on_login_detected(self, status: str, nickname: str | None) -> None:
        if status == "loggedIn":
            self.app_state.login_status = LoginStatus.LOGGED_IN
            logger.info("logged in as %s", nickname)
            if self._control is not None:
                self._control.toast(f"已登录:{nickname or '豆包账号'}")
            # Extract params after a short delay, then close the WebView.
            GLib.timeout_add(800, self._extract_and_close_login)

    def _extract_and_close_login(self) -> bool:
        if not self._login_window:
            return False
        def on_params(params):
            if params:
                ParamsStore.save(params)
            if self._login_window:
                try:
                    self._login_window.hide()
                except Exception:
                    pass
                try:
                    self._login_window.destroy()
                except Exception:
                    pass
                self._login_window = None
        self._login_window.extract_params_async(on_params)
        return False

    def _provide_params(self, callback) -> None:
        if self._login_window and self._login_window.is_active:
            self._login_window.extract_params_async(callback)
        else:
            self._show_login()
            callback(None)

    def _on_auth_expired(self) -> None:
        ParamsStore.clear()
        self.app_state.login_status = LoginStatus.NOT_LOGGED_IN
        self._show_login()

    def _check_mic(self) -> None:
        """3-second mic test: open stream, push RMS to the indicator, then close."""
        if self._use_hud and self._hud is not None:
            self._hud.flash(RECORDING, "麦克风测试中…", 4000)
        else:
            self._overlay.show("麦克风测试中…")
            self._overlay.set_text("请对麦克风说话")

        captured: list[float] = []
        cap = self._audio_capture

        def on_rms_test(rms: float):
            captured.append(rms)
            self._push_rms(rms)

        # Hook RMS for the test (we restore it after stop)
        cap._on_rms = on_rms_test
        try:
            cap.start(on_audio_data=lambda b: None)
        except Exception as e:
            self._overlay.set_text(f"麦克风启动失败: {e}")
            GLib.timeout_add(1500, lambda: self._overlay.hide() or False)
            return

        def stop_and_report():
            cap.stop()
            cap._on_rms = None  # restore
            if captured:
                peak = max(captured)
                avg = sum(captured) / len(captured)
                message = f"测试完成  peak={peak:.2f}  avg={avg:.3f}"
            else:
                message = "测试完成(无数据)"
            if self._use_hud and self._hud is not None:
                self._hud.flash(RECORDING, message, 1500)
            else:
                self._overlay.set_text(message)
            if self._control is not None:
                self._control.toast(message)
            return False

        GLib.timeout_add(3000, stop_and_report)
        GLib.timeout_add(4500, lambda: self._indicator_hide() or False)

    def _quit(self) -> None:
        if self._tm and self.app_state.recording_state != RecordingState.IDLE:
            self._tm.handle_cancel()
        if self._hud:
            self._hud.close()
            self._hud = None
        if self._ptt:
            self._ptt.stop()
        if self._injector:
            self._injector.close()
        self.quit()


def Gio_APPLICATION_NON_UNIQUE():
    from gi.repository import Gio  # type: ignore
    return Gio.ApplicationFlags.FLAGS_NONE
