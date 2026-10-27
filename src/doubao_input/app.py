"""Main GtkApplication: orchestrates trigger, ASR, HUD capsule, injector, login.

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
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gio, Gtk  # type: ignore

from doubao_input import autostart
from doubao_input.doubao.app_state import AppState, LoginStatus, RecordingState
from doubao_input.doubao.asr_client import ASRClient
from doubao_input.doubao.audio_capture import AudioCapture
from doubao_input.doubao.config import (
    CANCEL_KEY_NAME,
    FOCUS_CONFIRM_TICKS,
    FOCUS_POLL_SECS,
    PASTE_DELAY,
    SILENCE_RMS_THRESHOLD,
    TRIGGER_KEY_CHOICES,
    get_config_dir,
)
from doubao_input.doubao.params_store import ParamsStore
from doubao_input.doubao.transcription import TranscriptionManager
from doubao_input.hud.bridge import MynaHudBridge
from doubao_input.hud.settings import (
    load_desktop_shortcut,
    load_hud_style,
    load_inject_shift,
    load_silence_timeout,
    load_sounds,
    load_stop_on_focus_loss,
    load_onboarding_done,
    save_onboarding_done,
    load_trigger_key,
    load_trigger_mode,
    save_desktop_shortcut,
    save_hud_style,
    save_inject_shift,
    save_silence_timeout,
    save_sounds,
    save_stop_on_focus_loss,
    save_trigger_key,
    save_trigger_mode,
)
from doubao_input.hud.wire import IDLE, LOADING, NOTICE, RECORDING, STATUS_EMPTY
from doubao_input.i18n import _
from doubao_input.inject.injector import Injector
from doubao_input.trigger.desktop_shortcut import DesktopShortcut
from doubao_input.trigger.evdev_ptt import EvdevPtt
from doubao_input.ui import diagnostics
from doubao_input.ui.control_window import ControlWindow
from doubao_input.ui.focus_watch import focused_identity, reason, supported
from doubao_input.ui.notifier import Notifier
from doubao_input.ui.onboarding import OnboardingWindow, available as adw_available
from doubao_input.ui.sounds import Sounds
from doubao_input.ui.tray import Tray

logger = logging.getLogger(__name__)


def _app_version() -> str:
    """应用版本(装过的包读 metadata,源码运行时退回 pyproject 里的版本号)。"""
    from doubao_input.ui.about import app_version

    return app_version()


class DoubaoInputApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="com.doubao.Input",
            # 单实例(不带 NON_UNIQUE):第二次启动会通过 D-Bus 把命令行
            # 转给已有实例,于是 .desktop 的 show-control action 只是把
            # 现有窗口叫出来,而不是再开一个。
            # HANDLES_COMMAND_LINE:让 `--verbose` / `--quiet` / `--show` 真正生效
            # (.desktop 的 show-control action 以前是死参数)。
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        # PyGObject does NOT dispatch do_activate() automatically in all
        # versions — connect the signal explicitly so the first run
        # actually shows the UI.
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)
        self._setup_done = False
        self.app_state = AppState()
        self._control: ControlWindow | None = None
        self._login_window = None
        self._ptt: EvdevPtt | None = None
        self._tm: TranscriptionManager | None = None
        self._injector: Injector | None = None
        self._last_press_at: float = 0.0
        # Myna 悬浮胶囊前端(self._hud 存在 != 生效:渲染器没连上就只走桌面通知)
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
        self._tray: Tray | None = None
        # 托盘图标是否真的显示出来了(决定关窗是隐藏还是退出)
        self._tray_ready = False
        # 是否已经 hold() 住了应用。
        # 注意:Gio.Application.hold() 返回 **void**(PyGObject 里是 None),
        # 拿不到 id,所以只能用一个旗标自己记账 —— 否则重复 hold 会导致
        # 计数泄露、quit() 永远退不掉。
        self._held = False
        self._notifier: Notifier | None = None
        self._onboarding: OnboardingWindow | None = None
        self._last_voice_at = 0.0
        self._silence_timer = 0
        self._focus_timer = 0
        self._focus_change_count = 0
        self._session_focus: str | None = None

    # ---- Gtk.Application hooks (signal handlers, not do_*) ----

    def do_command_line(self, command_line) -> int:
        """命令行开关:-v/--verbose、--quiet、--show、--log-file <路径>。

        整个流程包在 try 里:单实例应用里,第二实例是把命令行**转发**给
        主实例的,主实例这边一旦抛异常不回话,转发方就会一直干等 ——
        表现就是「再跑一次 ./start.sh 一点反应都没有」。所以宁可返回
        非 0,也不能让它挂住。
        """
        try:
            level = logging.INFO
            show = False
            log_file = None
            arguments = command_line.get_arguments()[1:]
            index = 0
            while index < len(arguments):
                argument = arguments[index]
                if argument in ("--verbose", "-v"):
                    level = logging.DEBUG
                elif argument == "--quiet":
                    level = logging.WARNING
                elif argument == "--show":
                    show = True
                elif argument == "--log-file" and index + 1 < len(arguments):
                    index += 1
                    # 只接受相对文件名(落到应用自己的配置目录);绝对路径
                    # 一律拒绝,避免把日志写到任意位置。
                    candidate = arguments[index]
                    if os.path.isabs(candidate):
                        logger.warning(
                            "--log-file 仅接受文件名(写入配置目录),忽略绝对路径: %s",
                            candidate,
                        )
                    else:
                        log_file = Path(candidate).name
                else:
                    logger.info("ignoring unknown argument: %s", argument)
                index += 1
            logging.getLogger().setLevel(level)
            logger.debug("command line level set to %s", logging.getLevelName(level))
            if log_file:
                self._attach_file_log(log_file)
            self.activate()
            if show and self._control is not None:
                self._control.show()
        except Exception:
            logger.exception("命令行处理失败")
            return 1
        return 0

    @staticmethod
    def _attach_file_log(path: str) -> None:
        try:
            # 相对文件名统一落到应用配置目录(那里是 0700,不会别组/别人读)
            target = get_config_dir() / Path(path).name
            handler = logging.FileHandler(target, encoding="utf-8")
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            )
            logging.getLogger().addHandler(handler)
            logger.info("logging to %s", target)
        except Exception as e:
            logger.warning("cannot log to %s: %s", path, e)

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
        # 首次运行:先弹控制窗口,再开向导(Myna 的 onboarding)。
        if not load_onboarding_done():
            GLib.timeout_add(600, self._maybe_show_onboarding)

    def _startup_hint(self) -> str:
        """启动时那一闪的文案 —— 按**当前**的登录态和按键配置来说话。

        以前写死"按住右 Ctrl",用户改了键或已经登录之后就文不对题。
        """
        if self.app_state.login_status != LoginStatus.LOGGED_IN:
            return _("Doubao input is ready · sign in from the control window first")
        shortcut = self.desktop_shortcut()
        if shortcut:
            # 桌面快捷键走 D-Bus Toggle,语义就是"按一下开始/再按一下结束"。
            return _("Ready · press %s to start, press again to stop") % shortcut
        label = _(dict(TRIGGER_KEY_CHOICES).get(self._trigger_key, self._trigger_key))
        if self._trigger_mode == "toggle":
            return _("Ready · press “%s” to start, press again to stop") % label
        return _("Ready · hold “%s” to talk, release to paste") % label

    def _maybe_show_onboarding(self) -> bool:
        if load_onboarding_done():
            return GLib.SOURCE_REMOVE
        self.show_onboarding()
        return GLib.SOURCE_REMOVE

    def _show_about(self) -> None:
        """关于对话框(Adw.AboutDialog;实现见 ui/about.py)。"""
        from doubao_input.ui.about import show_about

        parent = self._control._window if self._control else None
        show_about(self, parent, version=_app_version())

    def _rebuild_onboarding(self) -> None:
        """界面语言变了 → 把首次运行向导(如果开着)重建一遍。

        向导是另一套窗口,里面的字符串同样是建时定死的,不重建就会停在旧语言。
        """
        # 托盘的菜单文案 / 标题也是建时定死的,一样得刷一遍。
        if self._tray is not None:
            try:
                self._tray.retranslate()
            except Exception as e:
                logger.debug("tray retranslate failed: %s", e)
        if self._onboarding is None:
            return
        window = self._onboarding._window
        self._onboarding = None
        if window is not None:
            try:
                window.destroy()
            except Exception as e:
                logger.warning("onboarding rebuild failed: %s", e)

    def show_onboarding(self) -> None:
        """打开首次运行向导(设置窗口主菜单也能再开)。"""
        if not adw_available():
            logger.info("libadwaita 不可用,跳过向导")
            return
        if self._onboarding is None:
            self._onboarding = OnboardingWindow(
                app_state=self.app_state,
                on_login=self._show_login,
                on_shortcut_set=self.set_desktop_shortcut,
                on_shortcut_conflicts=self.desktop_shortcut_conflicts,
                desktop_shortcut=self.desktop_shortcut,
                trigger_key=self._trigger_key,
                trigger_mode=self._trigger_mode,
                on_trigger_key_set=self.set_trigger_key,
                on_trigger_mode_set=self.set_trigger_mode,
                hud_status=self._hud_status,
                on_finish=lambda: save_onboarding_done(True),
                parent=self._control._window if self._control else None,
            )
        self._onboarding.show()
        self._onboarding.refresh()

    def _boot_flash_overlay(self) -> bool:
        """启动时闪一下 —— 让用户看到应用确实活着。只走 Myna 胶囊。"""
        message = self._startup_hint()
        if self._use_hud and self._hud is not None:
            self._hud.flash(NOTICE, message, 3000)
        elif self._notifier is not None:
            self._notifier.set_state(NOTICE, message)
        return False

    def _on_shutdown(self, _app) -> None:
        logger.info("shutting down")
        self._onboarding = None
        self._release_hold()
        if self._tray is not None:
            self._tray.close()
            self._tray = None
        if self._hud:
            self._hud.close()
            self._hud = None
        if self._ptt:
            self._ptt.stop()
        if self._injector:
            self._injector.close()

    # ---- Myna HUD 前端 ----

    def _start_hud(self) -> bool:
        """启动 Myna 悬浮胶囊(唯一外观)。失败时状态改走桌面通知。"""
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
                "Myna 胶囊不可用,状态改走桌面通知: %s", self._hud.renderer_status()
            )
        return self._use_hud

    # ---- 托盘 ----

    def _build_tray(self) -> None:
        """建托盘图标。任何失败都静默:没有 SNI 宿主(GNOME 默认)只是不显示。"""
        try:
            self._tray = Tray(
                on_show=self._show_control_window,
                on_check_mic=self._check_mic,
                on_quit=self._quit,
                on_registered=self._on_tray_registered,
            )
        except Exception as e:
            logger.info("tray unavailable, continuing without it: %s", e)
            self._tray = None

    def _on_tray_registered(self, registered: bool) -> None:
        """托盘真的显示出来了,才允许「关窗 = 隐藏」。

        顺序很重要(照 mihomo-manifold 的做法):没有图标的时候把窗口
        藏起来,就再也没有入口把它叫回来了——应用活着却完全无法触达。
        """
        if not registered:
            return
        self._tray_ready = True
        # 回调可能在 _control 建好之前就到了(注册是异步的),所以两边
        # 都要叫一次;set_hide_on_close 是幂等的。
        self._apply_hide_on_close()
        # 最后一个窗口关掉后 GTK 会结束应用(连带停止 evdev 监听),
        # hold() 把它抱住,直到托盘菜单里点「退出」。
        if self._held:
            return
        self.hold()
        self._held = True
        logger.info("tray: hide-on-close enabled, app held open")

    def _apply_hide_on_close(self) -> None:
        if not self._tray_ready:
            return
        if self._control is not None:
            try:
                self._control.set_hide_on_close(True)
            except Exception as e:
                logger.debug("set_hide_on_close failed: %s", e)

    def _release_hold(self) -> None:
        """释放 hold(),否则 quit() 也结束不了应用。"""
        if not self._held:
            return
        self._held = False
        try:
            self.release()
        except Exception as e:
            logger.debug("application.release() failed: %s", e)

    def _show_control_window(self) -> None:
        """托盘菜单 / 左键点击的统一入口。"""
        if self._control is not None:
            self._control.show()
            return
        self.activate()

    def _on_recording_state(self, _state, value: str) -> None:
        if self._tray is not None:
            self._tray.set_recording(value in ("starting", "recording"))

    def _on_hud_failed(self, message: str) -> None:
        logger.error("Myna 胶囊失效,状态改走桌面通知: %s", message)
        self._use_hud = False

    def _hud_status(self) -> str:
        return self._hud.renderer_status() if self._hud is not None else _("Disabled")

    def _last_error(self) -> str:
        """诊断页显示的最近错误(标题 + 本地时间)。"""
        if self._hud is None:
            return _("None")
        headline, _detail, micros = self._hud.last_error()
        if not headline:
            return _("None")
        if micros:
            stamp = time.strftime("%m-%d %H:%M", time.localtime(micros / 1_000_000))
            return f"{headline} ({stamp})"
        return headline

    def desktop_shortcut_conflicts(self, accelerator: str) -> list[tuple[str, bool]]:
        """该快捷键被谁占了:[(占用者, 是否桌面保留)]。"""
        return self._shortcut.conflicts(accelerator)

    def set_inject_shift(self, enabled: bool) -> None:
        """控制窗口的粘贴方式开关(Ctrl+Shift+V / Ctrl+V)。"""
        self._inject_shift = bool(enabled)
        save_inject_shift(self._inject_shift)

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
        self._sync_trigger_ui()

    def set_trigger_mode(self, mode: str) -> None:
        """hold = 按住说话(豆包原生);toggle = 按一下开/再按一下停(Myna)。"""
        self._trigger_mode = "toggle" if mode == "toggle" else "hold"
        save_trigger_mode(self._trigger_mode)
        logger.info("trigger mode: %s", self._trigger_mode)
        self._sync_trigger_ui()

    def _sync_trigger_ui(self) -> None:
        """设置窗口开着的话,把触发键 / 触发方式那两行同步过来。"""
        if self._control is None:
            return
        try:
            self._control.refresh_trigger_settings(self._trigger_key, self._trigger_mode)
        except Exception as e:
            logger.debug("sync trigger ui failed: %s", e)

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

    # ---- 指示器路由(只有 Myna 胶囊) ----
    #
    # 界面固定用 Myna 的胶囊(`myna-hud`)。原先还有一套自绘的圆角矩形悬浮窗
    # (`ui/overlay.py`)作为回退,现在不再使用 —— 两套外观不一致,用户会看到
    # 两个完全不同的东西。
    #
    # 胶囊起不来时**不再换一个窗口**,而是退回桌面通知(`ui/notifier.py`,
    # 也就是 Myna 自己的 NotifyIndicator 行为):功能不受影响,右 Ctrl 照常
    # 听写、照常粘贴,只是状态提示走系统通知。诊断页会说明原因。

    def _indicator_show(self, wire_state: str, message: str) -> None:
        if self._hud is not None:
            self._hud.set_state(wire_state, message)
        if not self._use_hud and self._notifier is not None:
            self._notifier.set_state(wire_state, message)

    def _indicator_text(self, message: str) -> None:
        if self._hud is not None:
            self._hud.set_state(RECORDING, message)

    def _indicator_notice(self, message: str) -> None:
        """可恢复提示(对齐 Myna 的 notice):不是错误,几秒后自己消失。"""
        if self._use_hud and self._hud is not None:
            self._hud.notice(message)
        elif self._notifier is not None:
            self._notifier.set_state(NOTICE, message)

    def _indicator_hide(self) -> None:
        if self._hud is not None:
            self._hud.idle()
        if not self._use_hud and self._notifier is not None:
            self._notifier.set_state(IDLE, "")

    def _push_rms(self, rms: float) -> None:
        """麦克风 RMS 回调(音频线程)。这里只写值,不碰 GTK。"""
        if rms >= SILENCE_RMS_THRESHOLD:
            self._last_voice_at = time.monotonic()
        if self._hud is not None:
            self._hud.push_level(rms)

    # ---- build ----

    def _build(self) -> None:
        self._injector = Injector()
        # 胶囊没起来时的兜底:状态走桌面通知(Myna 的 NotifyIndicator)。
        self._notifier = Notifier(self)
        # 任何错误都出一声(Myna:严重错误必播 Error)。
        self.app_state.connect("error-message-changed", self._on_error_message)

        # ---- Myna HUD:界面固定用 Myna 的胶囊 ----
        # 不再有“用 Myna 胶囊 / 用内置悬浮窗”的开关 —— 只有这一种外观。
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
            LOADING, _("Starting speech recognition…")
        )
        tm.on_overlay_hide = self._indicator_hide
        tm.on_overlay_update = lambda text: self._indicator_text(text)
        tm.on_paste = self._do_paste
        tm.on_empty_result = self._on_empty_result
        tm.on_cancel_enabled_changed = lambda enabled: None
        tm.on_auth_expired = self._on_auth_expired
        tm.on_params_needed = self._provide_params
        self._tm = tm

        # ---- 托盘(StatusNotifierItem,失败静默;见 ui/tray.py) ----
        # 必须在控制窗口之前建:菜单里的「显示控制窗口」要用到 self._control,
        # 但回调是延迟触发的,那时 _control 已经存在。
        self._build_tray()

        # ---- Control window ----
        self._control = ControlWindow(
            app_state=self.app_state,
            on_login_clicked=self._show_login,
            on_quit_clicked=self._quit,
            on_check_mic_clicked=self._check_mic,
            on_test_inject_clicked=self._test_inject,
            app=self,
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
            autostart=self.autostart_enabled(),
            autostart_supported=self.autostart_supported(),
            autostart_reason=self.autostart_reason(),
            on_autostart_changed=self.set_autostart,
            on_desktop_shortcut_conflicts=self.desktop_shortcut_conflicts,
            last_error=self._last_error,
            report=lambda: diagnostics.collect(self),
            on_run_onboarding=self.show_onboarding,
            on_about=self._show_about,
            on_language_changed=self._rebuild_onboarding,
        )
        # 托盘回调可能比 _control 早到(注册是异步的),这里补一刀。
        self._apply_hide_on_close()

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

        # 录音状态 -> 托盘图标(录音中换 Attention 图标)
        self.app_state.connect("recording-state-changed", self._on_recording_state)

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
            self._hud.notice(_("Sign in from the control window to start dictating"))
        elif self._notifier is not None:
            self._notifier.set_state(NOTICE, _("Sign in from the control window to start dictating"))

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
        self._indicator_notice(_("Dictation cancelled"))

    def _on_error_message(self, _state, value: str) -> None:
        if value:
            self._sounds.play("error")

    def set_sounds(self, enabled: bool) -> None:
        """开始 / 结束 / 错误提示音开关(Myna 的 sounds)。"""
        self._sounds.enabled = bool(enabled)
        save_sounds(self._sounds.enabled)

    # ---- 开机自启(XDG autostart / systemd user unit,见 autostart.py) ----

    @staticmethod
    def autostart_enabled() -> bool:
        """现在到底是不是「登录即自启」—— 直接读后端,不看缓存。"""
        try:
            return autostart.is_enabled()
        except Exception as e:
            logger.warning("autostart state unreadable: %s", e)
            return False

    @staticmethod
    def autostart_supported() -> bool:
        try:
            return autostart.supported()
        except Exception as e:
            logger.warning("autostart unsupported: %s", e)
            return False

    @staticmethod
    def autostart_reason() -> str:
        try:
            return autostart.reason()
        except Exception:
            return ""

    def set_autostart(self, enabled: bool) -> tuple[bool, str]:
        """开机自启开关。返回 (是否成功, 失败原因) —— 失败时控制窗口会把
        开关拨回去,免得界面显示「开」而下次登录其实不启动。"""
        try:
            ok, error = autostart.set_enabled(bool(enabled))
        except Exception as e:
            logger.exception("autostart toggle crashed")
            return False, str(e)
        logger.info(
            "autostart: want=%s ok=%s%s",
            "on" if enabled else "off",
            ok,
            f" error={error}" if error else "",
        )
        return ok, error

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
            self._indicator_notice(_("Focus left the window; nothing was typed"))
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
        # 注意:日志里绝不出现 text 内容 —— 识别文本可能很私密,
        # 且 systemd user 服务下 stdout 会进 journald 持久留存。
        logger.info("_do_paste called (len=%d)", len(text))
        if not self._injector:
            logger.warning("no injector; paste skipped")
            return
        # Myna 胶囊也要先消失,否则注入的 Ctrl+V 会落到我们的窗口上。
        if self._hud is not None:
            self._hud.set_state(IDLE, "")
        # 控制窗口**只有真的抢到焦点时才需要躲**:注入的 Ctrl+V 会落到
        # 当时有焦点的窗口上,而我们没焦点时它本来就收不到。
        # (以前是无条件隐藏 + 600ms 后恢复,于是每次粘贴完设置窗口都会
        #  闪一下 —— 即使它根本没焦点。)
        control_was_active = False
        if self._control and self._control._window:
            try:
                control_was_active = self._control._window.is_active()
                if control_was_active:
                    self._control._window.set_visible(False)
            except Exception:
                control_was_active = False

        def do_inject():
            logger.info("_do_paste: now injecting (len=%d)", len(text))
            ok = self._injector.inject(text, use_shift=self._inject_shift)
            logger.info("_do_paste: injector.inject returned %s", ok)
            if not ok:
                # Myna 的原则:失败要作为本次的错误上报,绝不静默丢字。
                self._indicator_notice(
                    _("Paste failed; the text is still on the clipboard — press Ctrl+Shift+V")
                )
                if self._control is not None:
                    self._control.toast(_("Paste failed; the text is still on the clipboard"))
            else:
                # 注入成功后清空剪贴板:识别文本不再留在系统剪贴板
                # (剪贴板管理器历史、下一次误粘贴都不会带上它)。
                # 延迟要足够长,目标应用先把 Ctrl+V 消费掉。
                injector_ref = self._injector

                def clear_clipboard():
                    try:
                        injector_ref.clear_clipboard()
                    except Exception:
                        pass
                    return GLib.SOURCE_REMOVE

                GLib.timeout_add(1500, clear_clipboard)
            # 只有刚才被我们藏起来的窗口才恢复(见上文 is_active 判断)。
            def restore_control():
                if (
                    control_was_active
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
        logger.info("_test_inject: clicked test-paste button")
        if self._control is not None:
            self._control.toast(_("Injecting the test string now…"))
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
                self._control.toast(_("Signed in: %s") % (nickname or _("Doubao account")))
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
            self._hud.flash(RECORDING, _("Testing the microphone…"), 4000)

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
            if self._control is not None:
                self._control.toast(_("Failed to start the microphone: %s") % e)
            return

        def stop_and_report():
            cap.stop()
            cap._on_rms = None  # restore
            if captured:
                peak = max(captured)
                avg = sum(captured) / len(captured)
                message = _("Test complete  peak=%0.2f  avg=%0.3f") % (peak, avg)
            else:
                message = _("Test complete (no data)")
            if self._use_hud and self._hud is not None:
                self._hud.flash(RECORDING, message, 1500)
            if self._control is not None:
                self._control.toast(message)
            return False

        GLib.timeout_add(3000, stop_and_report)
        GLib.timeout_add(4500, lambda: self._indicator_hide() or False)

    def _quit(self) -> None:
        if self._tm and self.app_state.recording_state != RecordingState.IDLE:
            self._tm.handle_cancel()
        if self._tray is not None:
            self._tray.close()
            self._tray = None
        if self._hud:
            self._hud.close()
            self._hud = None
        if self._ptt:
            self._ptt.stop()
        if self._injector:
            self._injector.close()
        # 先放掉 hold(),否则 quit() 只是发个请求、应用继续活着。
        self._release_hold()
        self.quit()
