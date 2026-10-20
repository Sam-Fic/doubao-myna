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
COPYRIGHT = "© 2026 Sam-Fic · © 2026 doubao-input-for-linux contributors"

WEBSITE = "https://github.com/Sam-Fic/doubao-myna"

#: Myna 自己的 About 页面(myna-config/src/app.rs 的 present_about)只署这些:
#:   application_name "Myna Settings" / developer_name "Canonical"
#:   copyright "© 2025-2026 Canonical Ltd." / license AGPL-3.0
#:   website https://github.com/canonical/myna
#: 界面、图标、myna-hud、GNOME 扩展都出自那里,这里原样继承这份署名。
MYNA_COPYRIGHT = "© 2025-2026 Canonical Ltd."
MYNA_WEBSITE = "https://github.com/canonical/myna"

#: 贡献者名单快照日期 —— 下面几节是当天从各仓库 GitHub contributors API 拉的。
#: 人不多,就手写在代码里(不想为了几行字去发网络请求);换新血时改这里即可。
CONTRIBUTORS_SNAPSHOT = "2026-10-21"

#: 主页面「开发者」= 本项目作者 + 上游作者。
DEVELOPERS = [
    "Sam-Fic https://github.com/Sam-Fic",
    "wurong98 https://github.com/wurong98",
]

#: 鸣谢页:图标与界面出自谁手。
ARTISTS = [
    f"Myna — Canonical Ltd.({MYNA_COPYRIGHT}):应用图标 com.canonical.Myna.svg、"
    "myna-hud 悬浮胶囊、GNOME Shell 扩展与设置窗口风格",
]

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
    ("上游:Myna", MYNA_WEBSITE),
    ("上游:doubao-input-for-linux", "https://github.com/wurong98/doubao-input-for-linux"),
]

#: Credits 页:本项目直接借鉴 / 依赖的上游项目与其贡献者。
#: 名单为 CONTRIBUTORS_SNAPSHOT 当天从 GitHub contributors API 拉取的快照。
CREDIT_SECTIONS = [
    (
        "本项目",
        [
            "Sam-Fic — 界面层(Myna 化)、触发可配、诊断报告、首次运行向导",
            "wurong98 — 上游 doubao-input-for-linux 的作者:push-to-hold、"
            "evdev 触发、剪贴板 + uinput 注入、WebKit 登录",
        ],
    ),
    (
        f"Myna(canonical/myna · AGPL-3.0-or-later · {CONTRIBUTORS_SNAPSHOT} 快照)",
        [
            f"Canonical Ltd. — {MYNA_COPYRIGHT}(Myna 自己的 About 只署 Canonical)",
            "quine00", "3v1n0", "jibel", "weblate", "juanruitina",
            "Matthaiks", "paul-geoghegan", "IhorHordiichuk", "ogres",
            "mz2", "github-actions[bot]", "Copilot", "dependabot[bot]",
        ],
    ),
    (
        f"doubao-input-for-linux 贡献者(wurong98/doubao-input-for-linux · MIT · {CONTRIBUTORS_SNAPSHOT} 快照)",
        ["wurong98"],
    ),
]

#: Acknowledgements 页:运行时依赖
ACKNOWLEDGEMENT_SECTIONS = [
    (
        "界面与桌面集成",
        [
            "GTK 4 与 libadwaita — 界面框架",
            "wl-clipboard — 剪贴板写入",
            "evdev 与 uinput — 物理键监听与文本注入",
            "canberra-gtk-play 与 freedesktop 声音主题 — 提示音",
            "GNOME Shell(myna-shell 扩展)— 悬浮胶囊的原版定位",
        ],
    ),
    (
        "Python 与音频",
        [
            "PyGObject — GTK 绑定",
            "websockets — 豆包 ASR 的 WebSocket 客户端",
            "sounddevice / PortAudio — 麦克风采集",
        ],
    ),
]

#: 法律声明页:每个组件的版权与许可。
#: 元组 = (标题, 版权行, Gtk.License, 自定义许可链接/文本)
LEGAL_SECTIONS = [
    (
        "doubao-input-for-linux(上游)",
        "© 2026 doubao-input-for-linux contributors",
        "MIT_X11",
        None,
    ),
    (
        "doubao-murmur(src/doubao_input/doubao/ 下的 ASR 逻辑)",
        "© 2024 doubao-murmur contributors — 署名详见仓库 NOTICE",
        "MIT_X11",
        None,
    ),
    (
        "Myna(应用图标 / myna-hud / GNOME 扩展 / 设置窗口风格)",
        f"{MYNA_COPYRIGHT} — AGPL-3.0-or-later,详见仓库 NOTICE",
        "AGPL_3_0",
        None,
    ),
]

#: 详情页说明(Pango 标记,允许链接)。触发那一段按用户当前配置生成,
#: 不再写死"右 Ctrl"—— 用户很可能早就改了键/模式。
def comments(app: Any = None) -> str:
    trigger = _trigger_phrase(app)
    return (
        f"全局语音输入法:在任意应用的输入框里聚焦,{trigger}。\n"
        "识别由豆包的网页 ASR 完成;登录凭证只保存在本机,除音频外不上传任何内容。"
    )


def _trigger_phrase(app: Any = None) -> str:
    """「怎么触发」的一句话,跟着设置走;拿不到配置就退回默认文案。"""
    if app is None:
        return "默认按住 <b>右 Ctrl</b> 说话,松开就粘贴进去"
    try:
        from doubao_input.doubao.config import TRIGGER_KEY_CHOICES

        shortcut = app.desktop_shortcut()
        if shortcut:
            return f"按 <b>{shortcut}</b> 开始,再按一次结束"
        label = dict(TRIGGER_KEY_CHOICES).get(app._trigger_key, app._trigger_key)
        if app._trigger_mode == "toggle":
            return f"按 <b>「{label}」</b>开始,再按一次结束"
        return f"按住 <b>「{label}」</b>说话,松开就粘贴进去"
    except Exception as e:
        logger.debug("about: trigger phrase fallback: %s", e)
        return "默认按住 <b>右 Ctrl</b> 说话,松开就粘贴进去"

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


def _license(name: str) -> Gtk.License:
    """按名字取 Gtk.License;取不到就退回 UNKNOWN(不会炸)。

    GTK 4.10 起按 SPDX 改名(MIT → MIT_X11、AGPL_3 → AGPL_3_0),
    所以这里用字符串查表,老 GTK 也能跑。
    """
    value = getattr(Gtk.License, name, None)
    if value is None:
        # 老 GTK 上的 MIT 叫 MIT_X11,新的也有;AGPL_3_0 老名字是 AGPL_3。
        fallback = {"MIT": "MIT_X11", "MIT_X11": "MIT", "AGPL_3_0": "AGPL_3", "AGPL_3": "AGPL_3_0"}
        value = getattr(Gtk.License, fallback.get(name, ""), None)
    return value if value is not None else Gtk.License.UNKNOWN


def _license_type() -> Gtk.License:
    """本项目自己的许可:AGPL-3.0-or-later。"""
    return _license("AGPL_3_0")


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
    _set(component, "comments", comments(app))
    _set(component, "website", WEBSITE)
    if ISSUE_URL:
        _set(component, "issue_url", ISSUE_URL)
    if SUPPORT_URL:
        _set(component, "support_url", SUPPORT_URL)
    _set(component, "license_type", _license_type())
    _set(component, "developers", DEVELOPERS)
    _set(component, "artists", ARTISTS)
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
    # add_legal_section(title, copyright, license_type, license=None)
    # 注意是四个参数 —— 以前只传两个会被 PyGObject 静默拒绝,法律页就是空的。
    for title, copyright_text, license_name, custom in LEGAL_SECTIONS:
        if custom:
            _add(component, "add_legal_section", title, copyright_text,
                 Gtk.License.CUSTOM, custom)
        else:
            _add(component, "add_legal_section", title, copyright_text,
                 _license(license_name))


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
