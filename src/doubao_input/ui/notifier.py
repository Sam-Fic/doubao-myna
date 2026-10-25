"""桌面通知兜底 —— 没有 Myna 胶囊时,状态得有地方显示。

对齐 Myna 的 `NotifyIndicator`:

  * 一个会话**只用一条通知**,状态推进时用同一个 id **原地替换**,不堆叠;
  * Urgency 必须 Normal(GNOME Shell 会把 Low 直接丢进托盘、不弹横幅),
    错误才用 Critical;
  * 通知文案**永远不含转写文本**(Myna 的 N8 / 契约 C3);
  * notice(可恢复)会自己消失,error 留着等下一个状态。
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gio  # type: ignore

from doubao_input.i18n import _

logger = logging.getLogger(__name__)

NOTIFICATION_ID = "doubao-dictation"
TITLE = "Doubao Dictation"

# 与 wire 常量保持一致,避免循环导入
IDLE = "idle"
LOADING = "loading"
RECORDING = "recording"
TRANSCRIBING = "transcribing"
FINALIZING = "finalizing"
NOTICE = "notice"
ERROR = "error"


class Notifier:
    """Single, replaced-in-place desktop notification for dictation state."""

    def __init__(self, app=None) -> None:
        self._app = app
        self._timer = 0

    # ---- public ----

    def set_state(self, state: str, message: str = "") -> None:
        if self._app is None:
            return
        if state == IDLE:
            self.close()
            return

        title = _(TITLE)
        body = self._body_for(state, message)
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        # Normal, not Low:否则 GNOME 不弹横幅,等于看不见。
        notification.set_priority(
            Gio.NotificationPriority.URGENT
            if state == ERROR
            else Gio.NotificationPriority.NORMAL
        )
        self._app.send_notification(NOTIFICATION_ID, notification)
        self._schedule_hide(state, body)

    def close(self) -> None:
        self._cancel_hide()
        if self._app is not None:
            self._app.withdraw_notification(NOTIFICATION_ID)

    # ---- internals ----

    @staticmethod
    def _body_for(state: str, message: str) -> str:
        """正文永远是内容无关的文案:识别文本绝不进通知。"""
        if state == LOADING:
            return _("Connecting…")
        if state in (RECORDING, TRANSCRIBING):
            return _("Listening…")
        if state == FINALIZING:
            return _("Transcribing…")
        return message or "…"

    def _schedule_hide(self, state: str, body: str) -> None:
        self._cancel_hide()
        if state == ERROR:
            return  # 严重错误不自动消失,等下一个状态替掉它
        # Myna:60ms/字符,clamp 8~15s。
        hold_ms = min(15000, max(8000, len(body) * 60))
        self._timer = GLib.timeout_add(hold_ms, self._on_hide)

    def _cancel_hide(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _on_hide(self) -> bool:
        self._timer = 0
        self.close()
        return GLib.SOURCE_REMOVE
