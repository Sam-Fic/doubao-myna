"""「关于」对话框 —— 用 Adw.AboutDialog 重做(libadwaita ≥ 1.5)。

为什么不用老的 Adw.AboutWindow:
  Adw.AboutWindow 从 libadwaita 1.5 起被 Adw.AboutDialog 取代(前者已 deprecated)。
  AboutDialog 是真正的 Adw.Dialog,自带「主页面 / 新功能 / 详情 / 疑难解答 /
  鸣谢 / 法律声明」六个页面,以及「把调试信息存成文件」的功能。

内容分工:
  主页面    图标、应用名、开发者、版本
  新功能    release notes(AppStream 风格标记:<p> / <ul> / <li> / <em> / <code>)
  详情      一段说明 + 若干链接
  疑难解答  隐私安全的诊断报告(不含音频、识别文本、绝对路径)
  鸣谢      Credits(开发者 + 参考项目)、Acknowledgements(运行时依赖)
  法律声明  AGPL-3.0-or-later + 图标出处

老系统(libadwaita < 1.5)没有 AboutDialog,退回 API 基本一致的 AboutWindow;
两个版本的差异都由 _set() / _add() 按属性是否存在自动跳过。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # type: ignore

from doubao_input.ui.adw_compat import HAS_ADW as _HAS_ADW
from doubao_input.ui.adw_compat import Adw, adw_has

logger = logging.getLogger(__name__)

# ---- 应用信息 ----

APP_NAME = "豆包语音输入法"
ICON_NAME = "doubao-input"
DEVELOPER_NAME = "Sam-Fic"
COPYRIGHT = "© 2026 Sam-Fic"

WEBSITE = "https://github.com/Sam-Fic/doubao-myna"

#: 主页面上的「支持问题 / 报告问题」两个入口。
#: 仓库目前没开 Issues / Discussions(GitHub 上是禁用状态,点进去只有提示页),
#: 所以先留空,不往主页面摆死链;开了之后把地址填上即可自动出现。
ISSUE_URL = ""
SUPPORT_URL = ""

#: 详情页里的额外链接(网站本身由 website 属性提供)
LINKS = [
    ("使用说明", f"{WEBSITE}#readme"),
    ("安装指南", f"{WEBSITE}#安装指南"),
    ("已知限制", f"{WEBSITE}#已知限制"),
    ("更新日志", f"{WEBSITE}#更新日志"),
    ("设计文档", f"{WEBSITE}/blob/main/docs/design.md"),
    ("与 Myna 的对齐说明", f"{WEBSITE}/blob/main/docs/myna-parity.md"),
]

#: Credits 页:本项目直接借鉴 / 依赖的上游项目
CREDIT_SECTIONS = [
    (
        "参考项目",
        [
            "Myna (Canonical) — 界面风格、应用图标、myna-hud 悬浮胶囊",
            "doubao-murmur — 豆包 ASR 协议与逆向实现",
            "wurong98/doubao-input-for-linux — 上游 Linux 端口",
        ],
    ),
]

#: Acknowledgements 页:运行时依赖
ACKNOWLEDGEMENT_SECTIONS = [
    (
        "运行时依赖",
        [
            "GTK 4 与 libadwaita — 界面框架",
            "wl-clipboard — 剪贴板写入",
            "evdev 与 uinput — 物理键监听与文本注入",
            "canberra-gtk-play — 提示音",
        ],
    ),
]

#: 法律声明里的额外条目
LEGAL_SECTIONS = [
    (
        "应用图标",
        "图标取自 Canonical 的 Myna,按 AGPL-3.0-or-later 使用,详见仓库 NOTICE。",
    ),
]

#: 详情页说明(Pango 标记,允许链接)
COMMENTS = (
    "全局语音输入法:在任意应用的输入框里聚焦,默认按住 <b>右 Ctrl</b> 说话,"
    "松开就把识别结果粘贴进去。\n"
    "识别由豆包的网页 ASR 完成;登录凭证只保存在本机,除音频外不上传任何内容。"
)

#: 新功能页(AppStream 风格:只认 <p> / <ul> / <ol> / <li> / <em> / <code>)
#: 内容对齐 README 的「更新日志 → v1.1.0」。
RELEASE_NOTES_VERSION = "1.1.0"
RELEASE_NOTES = (
    "<p>v1.1.0 的重点:</p>"
    "<ul>"
    "<li>设置界面重做成 libadwaita 三页布局(输入 / 诊断 / 应用)</li>"
    "<li>集成 Myna <code>myna-hud</code> 渲染器与 D-Bus 状态同步,可选悬浮胶囊</li>"
    "<li>触发可配:桌面快捷键(组合键)、evdev 物理键、按住说话 / Myna 式 toggle</li>"
    "<li>快捷键冲突检测与最近错误记录</li>"
    "<li>首次运行向导与设置窗口主菜单</li>"
    "<li>隐私诊断报告(不含音频、识别文本、绝对路径)</li>"
    "<li>提示音(开始 / 结束 / 错误)与 ESC 取消</li>"
    "<li>命令行支持 <code>-v</code> / <code>--quiet</code> / <code>--show</code> 与文件日志</li>"
    "</ul>"
)

#: 疑难解答页里「另存为」时的建议文件名
DEBUG_FILENAME = "doubao-input-diagnostics.txt"


def app_version() -> str:
    """应用版本(装过的包读 metadata,源码运行时退回内置版本号)。"""
    try:
        from importlib.metadata import version

        return version("doubao-input")
    except Exception:
        return "1.1.0"


def _license_type() -> Gtk.License:
    """AGPL-3.0 许可类型。

    GTK 4.10 起按 SPDX 重命名为 AGPL_3_0,更早的 GTK 4 只有 AGPL_3,
    两个名字都认一下,免得在老系统上直接 AttributeError。
    """
    for name in ("AGPL_3_0", "AGPL_3"):
        value = getattr(Gtk.License, name, None)
        if value is not None:
            return value
    return Gtk.License.GPL_3_0


def _set(component: Any, name: str, value: Any) -> None:
    """设置一个属性;两个版本的 About 组件属性名一致,个别项缺失就跳过。"""
    setter = getattr(component, f"set_{name}", None)
    if setter is None:
        return
    try:
        setter(value)
    except Exception as e:
        logger.debug("about: set_%s failed: %s", name, e)


def _add(component: Any, method: str, *args: Any) -> None:
    """调用 add_* 方法(没有就跳过)。"""
    func = getattr(component, method, None)
    if func is None:
        return
    try:
        func(*args)
    except Exception as e:
        logger.debug("about: %s failed: %s", method, e)


def _debug_info(app: Any) -> str:
    """疑难解答页的调试信息 —— 复用隐私诊断报告(不含音频/识别文本/路径)。"""
    if app is None:
        return ""
    try:
        from doubao_input.ui.diagnostics import collect

        return collect(app)
    except Exception as e:
        logger.warning("about: cannot build debug info: %s", e)
        return ""


def _fill(component: Any, app: Any, version: str) -> None:
    """把内容灌进 AboutDialog / AboutWindow(两者 API 基本一致)。"""
    _set(component, "application_name", APP_NAME)
    _set(component, "application_icon", ICON_NAME)
    _set(component, "version", version)
    _set(component, "developer_name", DEVELOPER_NAME)
    _set(component, "copyright", COPYRIGHT)
    _set(component, "comments", COMMENTS)
    _set(component, "website", WEBSITE)
    if ISSUE_URL:
        _set(component, "issue_url", ISSUE_URL)
    if SUPPORT_URL:
        _set(component, "support_url", SUPPORT_URL)
    _set(component, "license_type", _license_type())
    _set(component, "developers", [DEVELOPER_NAME])
    _set(component, "release_notes", RELEASE_NOTES)
    _set(component, "release_notes_version", RELEASE_NOTES_VERSION)
    _set(component, "debug_info", _debug_info(app))
    _set(component, "debug_info_filename", DEBUG_FILENAME)

    for title, url in LINKS:
        _add(component, "add_link", title, url)
    for title, people in CREDIT_SECTIONS:
        _add(component, "add_credit_section", title, people)
    for title, people in ACKNOWLEDGEMENT_SECTIONS:
        _add(component, "add_acknowledgement_section", title, people)
    for title, text in LEGAL_SECTIONS:
        _add(component, "add_legal_section", title, text)


def show_about(
    app: Any = None,
    parent: Optional[Gtk.Widget] = None,
    version: Optional[str] = None,
) -> bool:
    """弹出「关于」对话框;返回是否真的弹出来了。

    `app` 用来生成隐私安全的诊断报告(疑难解答页),可以传 None。
    `parent` 是设置窗口,用来做模态归属。
    """
    if not _HAS_ADW:
        logger.info("libadwaita 不可用,跳过关于对话框")
        return False

    version = version or app_version()
    try:
        if adw_has("AboutDialog"):
            dialog = Adw.AboutDialog()
            _fill(dialog, app, version)
            dialog.present(parent)
        else:
            # libadwaita < 1.5:退回同样内容的 AboutWindow。
            window = Adw.AboutWindow()
            _fill(window, app, version)
            if parent is not None:
                window.set_transient_for(parent)
            window.present()
        return True
    except Exception as e:
        logger.warning("about dialog failed: %s", e)
        return False
