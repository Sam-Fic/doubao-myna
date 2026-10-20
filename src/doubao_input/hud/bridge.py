"""把豆包的录音状态机翻译成 Myna HUD 的线状态。

桥接只做两件事:

1. 订阅 `AppState` 的 GObject 信号,把 豆包 的 RecordingState 映射成
   `com.canonical.Myna.Dictation` 的 State + StatusMessage;
2. 把麦克风 RMS 平滑成 20Hz 的电平流推给渲染器。

它不知道像素,也不知道豆包的 WebSocket:上面接状态机,下面接 publisher。
渲染器没起来/没装时整条链路安静降级,录音与注入照常工作。
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib  # type: ignore

from doubao_input.doubao.app_state import AppState, LoginStatus, RecordingState
from doubao_input.doubao.config import (
    HUD_AUTO_LAUNCH,
    HUD_ERROR_HOLD_MS,
    HUD_LEVEL_HZ,
    HUD_NOTICE_HOLD_MS,
    HUD_SHOW_TRANSCRIPT,
    HUD_STATUS_MAX_CHARS,
    HUD_STYLE,
)
from doubao_input.hud.launcher import HudLauncher, extension_enabled
from doubao_input.hud.publisher import DictationPublisher
from doubao_input.hud.wire import (
    ERROR,
    FINALIZING,
    IDLE,
    LOADING,
    NOTICE,
    RECORDING,
    STATUS_CONNECTING,
    STATUS_FINALIZING,
    STATUS_LISTENING,
    STATUS_NOT_LOGGED_IN,
    tail,
)

logger = logging.getLogger(__name__)

# 电平平滑:麦克风的 RMS 每 ~256ms 才来一次(16kHz / 4096 samples),
# 直接在两次之间插值,丝带才不会一顿一顿的。
LEVEL_SMOOTHING = 0.35
PEAK_DECAY = 0.90


class MynaHudBridge:
    """豆包状态机 → Myna HUD 的单向桥。"""

    def __init__(
        self,
        app_state: AppState,
        on_press: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
        on_failed: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._app_state = app_state
        self._on_failed = on_failed
        self._on_press = on_press
        self._on_release = on_release
        self._publisher = DictationPublisher(
            on_start=on_press,
            on_stop=on_release,
            on_toggle=self._toggle_from_dbus,
        )
        self._launcher = HudLauncher(on_failed=self._on_renderer_failed)
        self._handler_ids: list[int] = []

        self._ticker = 0
        self._hold_timer = 0
        self._level_target = 0.0
        self._level_value = 0.0
        self._level_peak = 0.0
        self.enabled = False       # D-Bus 名字拿到了,发布可用
        self.renderer = False      # myna-hud 进程起来了,有人画

    # ---- lifecycle ----

    @property
    def active(self) -> bool:
        """界面上真的有胶囊(self 与渲染器都在)。"""
        return self.enabled and self.renderer

    def start(self) -> bool:
        self.enabled = self._publisher.start()
        if not self.enabled:
            return False
        self._publisher.set_hud_style(HUD_STYLE)
        self._connect_state()
        if HUD_AUTO_LAUNCH:
            if extension_enabled():
                # 扩展自己会拉起渲染器(并负责定位)。
                logger.info("%s 已启用,由扩展拉起 myna-hud", "myna-shell")
                self.renderer = True
            else:
                self.renderer = self._launcher.start()
        return True

    def close(self) -> None:
        self._stop_ticker()
        self._clear_hold()
        for hid in self._handler_ids:
            self._app_state.disconnect(hid)
        self._handler_ids = []
        self._launcher.stop()
        self._publisher.stop()
        self.enabled = False
        self.renderer = False

    # ---- 供 app.py 调用的入口 ----

    def set_state(self, state: str, status_message: str = "") -> None:
        """设置状态(会一直保持,直到下一次调用)。"""
        self._clear_hold()
        self._apply(state, status_message)

    def flash(self, state: str, status_message: str, hold_ms: int = 0) -> None:
        """显示一次,hold_ms 毫秒后自动回到 idle(notice/error 的用法)。"""
        self._apply(state, status_message)
        self._clear_hold()
        if hold_ms > 0:
            self._hold_timer = GLib.timeout_add(hold_ms, self._on_hold_expired)

    def notice(self, message: str, hold_ms: int = HUD_NOTICE_HOLD_MS) -> None:
        self.flash(NOTICE, message, hold_ms)

    def error(self, message: str, hold_ms: int = HUD_ERROR_HOLD_MS) -> None:
        self.flash(ERROR, message, hold_ms)

    def idle(self) -> None:
        self.set_state(IDLE, "")

    def set_style(self, nick: str) -> None:
        """切换波形样式(bar / ribbon / vumeter),实时生效。"""
        if self.enabled:
            self._publisher.set_hud_style(nick)

    def push_level(self, rms: float) -> None:
        """麦克风 RMS 入口。**可以从音频线程调用**:这里只写一个 float。"""
        try:
            self._level_target = float(rms)
        except (TypeError, ValueError):
            self._level_target = 0.0

    def last_error(self) -> tuple[str, str, int]:
        """最近一次失败:(标题, 详情, 微秒时间戳)。没有则全空。"""
        if not self.enabled:
            return ("", "", 0)
        props = self._publisher._properties
        try:
            return (
                props["LastError"].get_string(),
                props["LastErrorDetail"].get_string(),
                int(props["LastErrorTime"].get_int64()),
            )
        except Exception:
            return ("", "", 0)

    def renderer_status(self) -> str:
        if not self.enabled:
            return "未启用"
        if self.renderer:
            binary = self._launcher.binary or "?"
            return f"已连接 ({binary})"
        return "发布中,但 myna-hud 未运行"

    # ---- 状态映射 ----

    def _connect_state(self) -> None:
        self._handler_ids = [
            self._app_state.connect("recording-state-changed", self._on_recording_state),
            self._app_state.connect("transcription-text-changed", self._on_text),
            self._app_state.connect("error-message-changed", self._on_error),
            self._app_state.connect("login-status-changed", self._on_login),
        ]

    def _on_recording_state(self, _state: AppState, _value: str) -> None:
        state = self._app_state.recording_state
        if state == RecordingState.IDLE:
            self.set_state(IDLE, "")
            self._stop_ticker()
        elif state == RecordingState.STARTING:
            # 冷启动窗口:WSS 还没连上,但麦克风已经在收音了。
            self.set_state(LOADING, STATUS_CONNECTING)
            self._start_ticker()
        elif state == RecordingState.RECORDING:
            self.set_state(RECORDING, self._status_text())
            self._start_ticker()
        elif state == RecordingState.STOPPING:
            self.set_state(FINALIZING, STATUS_FINALIZING)
            self._stop_ticker()

    def _on_text(self, _state: AppState, _value: str) -> None:
        if self._app_state.recording_state == RecordingState.IDLE:
            return
        self.set_state(RECORDING, self._status_text())

    def _on_error(self, _state: AppState, value: str) -> None:
        if not value:
            return
        # 豆包的错误信息是给用户看的,内容可控(不含识别内容)。
        headline = value[:HUD_STATUS_MAX_CHARS]
        self.error(headline)
        # 顺手记进"最近错误"(粘性,供诊断页读取)。
        if self.enabled:
            self._publisher.set_last_error(headline, value)

    def _on_login(self, _state: AppState, _value: str) -> None:
        if self._app_state.login_status == LoginStatus.NOT_LOGGED_IN:
            self.notice(STATUS_NOT_LOGGED_IN)

    def _status_text(self) -> str:
        text = (self._app_state.transcription_text or "").strip()
        if HUD_SHOW_TRANSCRIPT and text:
            return tail(text, HUD_STATUS_MAX_CHARS)
        return STATUS_LISTENING

    def _apply(self, state: str, status_message: str) -> None:
        if not self.enabled:
            return
        self._publisher.set_state(state, status_message)

    # ---- 电平泵 ----

    def _start_ticker(self) -> None:
        if self._ticker:
            return
        self._ticker = GLib.timeout_add(
            max(1, int(1000 / max(1, HUD_LEVEL_HZ))), self._tick
        )

    def _stop_ticker(self) -> None:
        if self._ticker:
            GLib.source_remove(self._ticker)
            self._ticker = 0
        self._level_target = 0.0
        self._level_value = 0.0
        self._level_peak = 0.0
        if self.enabled:
            # 契约 E2:idle 时电平归零。
            self._publisher.push_level(0.0, 0.0)

    def _tick(self) -> bool:
        self._level_value += (self._level_target - self._level_value) * LEVEL_SMOOTHING
        self._level_peak = max(self._level_value, self._level_peak * PEAK_DECAY)
        self._publisher.push_level(self._level_value, self._level_peak)
        return GLib.SOURCE_CONTINUE

    # ---- 杂项 ----

    def _clear_hold(self) -> None:
        if self._hold_timer:
            GLib.source_remove(self._hold_timer)
            self._hold_timer = 0

    def _on_hold_expired(self) -> bool:
        self._hold_timer = 0
        self._publisher.set_state(IDLE, "")
        return GLib.SOURCE_REMOVE

    def _toggle_from_dbus(self) -> None:
        """D-Bus 上的 Toggle:由 press/release 回调组合出来。"""
        if self._app_state.recording_state == RecordingState.IDLE:
            if self._on_press:
                self._on_press()
        elif self._on_release:
            self._on_release()

    def _on_renderer_failed(self, message: str) -> None:
        self.renderer = False
        logger.error("myna-hud unavailable: %s", message)
        if self._on_failed:
            self._on_failed(message)
