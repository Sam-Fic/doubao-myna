"""隐私诊断报告 —— 对齐 Myna Settings 的 Diagnostics 页。

规矩和 Myna 一样(也是它的原话):

  **No audio, transcript, or filesystem path is ever included.**

报告里只有:系统 / 机器 / 听写配置 / 指示器状态 / 最近错误 / 待做的自检 /
发现的问题。**绝不包含**麦克风采到的音频、识别出来的文本、以及任何
绝对路径(一律替换成 `[redacted]`,连我们自己的二进制路径也一样)。
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
from datetime import datetime

from doubao_input import autostart

logger = logging.getLogger(__name__)

#: 绝对路径一律脱敏(Myna 的 diagnostics.rs 同样处理命令行 flag 值)。
_PATH_RE = re.compile(
    r"(/(?:home|root|tmp|var|opt|usr|etc|Users|private)/[^\s'\",;()]+)"
)


def redact(text: str) -> str:
    return _PATH_RE.sub("[redacted]", str(text))


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("doubao-input")
    except Exception:
        return "dev"


def collect(app) -> str:
    """生成报告文本。`app` 是 DoubaoInputApp(只为读状态,不做任何 UI 操作)。"""
    lines: list[str] = []
    add = lines.append

    add(f"豆包输入法 {_version()} · 诊断报告")
    add(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    add("")

    # ---- 系统 ----
    add("[系统]")
    add(f"桌面: {os.environ.get('XDG_CURRENT_DESKTOP') or '未知'}"
        f" ({os.environ.get('XDG_SESSION_TYPE') or '未知'})")
    add(f"系统: {platform.system()} {platform.release()}"
        f" · 内核 {platform.version()}")
    add(f"语言: {os.environ.get('LANG') or os.environ.get('LC_ALL') or '未设置'}")
    add("")

    # ---- 机器 ----
    add("[机器]")
    add(f"CPU: {platform.processor() or platform.machine() or '未知'}"
        f" ({os.cpu_count() or '?'} 核)")
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            total = next(
                (line for line in fh if line.startswith("MemTotal")), ""
            ).split(":")[-1].strip()
        add(f"内存: {total or '未知'}")
    except Exception:
        add("内存: 未知")
    add("")

    # ---- 听写配置 ----
    add("[听写]")
    add(f"登录: {'已登录' if _logged_in(app) else '未登录'}")
    add("ASR 端点: ws-samantha.doubao.com")
    add(f"触发: 物理键 {app._trigger_key} · 模式 {app._trigger_mode}"
        f" · 静音 {app._silence_timeout}s")
    add(f"桌面快捷键: {app.desktop_shortcut() or '未设置'}")
    add(f"粘贴: {'Ctrl+Shift+V' if app._inject_shift else 'Ctrl+V'}")
    add(f"提示音: {'开' if app._sounds.enabled else '关'}")
    add(f"焦点离开结束: {'开' if app._stop_on_focus_loss else '关'}")
    add(f"开机自启: {'开' if autostart.is_enabled() else '关'}"
        f" · {autostart.backend()}")
    add("")

    # ---- 指示器 ----
    add("[指示器]")
    # 渲染器状态里可能带二进制路径,脱敏后再写进报告。
    add(f"Myna HUD: {redact(app._hud_status())}")
    if app._hud is not None:
        head, _detail, micros = app._hud.last_error()
        if head:
            stamp = (
                datetime.fromtimestamp(micros / 1_000_000).strftime("%m-%d %H:%M")
                if micros else "时间未知"
            )
            add(f"最近错误: {redact(head)}({stamp})")
    add(f"GNOME 扩展: {'已启用' if _extension_enabled(app) else '未启用'}")
    add(f"托盘图标: {_tray_status(app)}")
    add(f"evdev 监听: {'运行中' if _ptt_running(app) else '未运行'}")
    add("")

    # ---- 待做的自检 ----
    add("[自检]")
    add("麦克风: 未测试 —— 在设置窗口点「检查」")
    add("粘贴链路: 未测试 —— 在设置窗口点「测试」")
    add("")

    # ---- 问题 ----
    problems = _problems(app)
    if problems:
        add("[问题]")
        for problem in problems:
            add(f"- {problem}")
    else:
        add("[问题]")
        add("- 未发现问题")

    return "\n".join(lines)


# ---- helpers ----

def _logged_in(app) -> bool:
    try:
        from doubao_input.doubao.app_state import LoginStatus

        return app.app_state.login_status == LoginStatus.LOGGED_IN
    except Exception:
        return False


def _extension_enabled(app) -> bool:
    try:
        from doubao_input.hud.launcher import extension_enabled

        return extension_enabled()
    except Exception:
        return False


def _tray_status(app) -> str:
    """托盘状态。没装 AppIndicator 扩展时这里会明说,而不是笼统地"不可用"。"""
    tray = getattr(app, "_tray", None)
    if tray is None:
        return "未创建"
    try:
        return tray.status()
    except Exception:
        return "未知"


def _ptt_running(app) -> bool:
    try:
        return bool(app._ptt and app._ptt.is_running())
    except Exception:
        return False


def _problems(app) -> list[str]:
    problems: list[str] = []
    if not _logged_in(app):
        problems.append("未登录豆包,按住快捷键只会提示登录")
    if not _ptt_running(app):
        problems.append("evdev 监听未运行(检查是否在 input 组、是否有可读的 /dev/input/event*)")
    if app._hud is None or not app._use_hud:
        problems.append("Myna 胶囊不可用,当前用内置悬浮窗(跑 scripts/build-myna-hud.sh 可装上)")
    if app._sounds.available is False:
        problems.append("提示音不可用(缺 canberra-gtk-play / libcanberra)")
    if not shutil.which("wl-copy"):
        problems.append("缺 wl-copy(wl-clipboard),注入会失败")
    tray = getattr(app, "_tray", None)
    if tray is not None and not getattr(tray, "available", False):
        problems.append(
            "托盘图标未显示:桌面没有 StatusNotifierItem 宿主"
            "(GNOME 需装 AppIndicator 扩展,如 gnome-shell-extension-appindicator)"
        )
    return problems
