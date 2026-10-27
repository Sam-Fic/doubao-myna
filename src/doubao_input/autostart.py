"""开机自启(XDG autostart ↔ systemd user unit)。

设置窗口「输入 → 启动」里的「开机自启」开关对应这里。状态**永远从后端读
回来**(:func:`is_enabled`),不另外在 settings.json 存一份 —— 用户完全可能
用 `systemctl --user enable` 或桌面的「启动应用程序」自己改过,缓存会说谎。

两套后端:

* 装过 .deb(能找到 ``doubao-input.service`` 这个 user unit)→
  `systemctl --user enable/disable`,和 README 里手敲的命令完全等价,
  还自带 `Restart=on-failure`;
* 否则(源码运行 / 没有 systemd)→ 写 / 删
  ``~/.config/autostart/doubao-input.desktop``(XDG autostart,任何桌面环境
  登录时都会读这个目录)。

**读的时候两套都看** —— 别人用 systemctl 打开的自启,开关必须显示为开,
否则「关不掉」(只删 XDG 文件的话,开关会弹回去并报错);**写的时候只用一套**,
免得登录时被拉起两个实例。

一个绕不开的坑:装 .deb 时 debhelper 会**替所有用户**把 unit enable 到
``/etc/systemd/user/default.target.wants/``(root 才有权限改),于是
`systemctl --user disable` 打完招呼状态还是 enabled。关不掉的开关等于没做,
所以这时补一刀 `systemctl --user mask` —— 用户级 unit 目录
(``~/.config/systemd/user``)优先级高于 ``/etc/systemd/user``,mask 一盖,
全局那份 enable 就不生效了;再开时先 `unmask` 再 `enable` 即可。

成败不看单条命令的返回码,而是写完**再读一次真实状态对账**:systemd 报错
但 XDG 写成功(或反之)也算成功 —— 用户只关心「下次登录会不会自动启动」。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from doubao_input.i18n import _

logger = logging.getLogger(__name__)

#: .deb 装的 systemd user unit(debian/doubao-input.service)。
SERVICE_UNIT = "doubao-input.service"

#: XDG autostart 条目(每家桌面登录时都读 ~/.config/autostart/)。
AUTOSTART_ENTRY = "doubao-input.desktop"

#: unit 文件的安装位置(dpkg 装到 /usr/lib/systemd/user)。
_UNIT_DIRS = (
    "/usr/lib/systemd/user",
    "/lib/systemd/user",
    "/usr/local/lib/systemd/user",
)

#: 图标名(装过 .deb 就是 hicolor 主题里的 doubao-input)。
#: 用主题名而不是绝对路径:绝对路径在 GNOME 的图标缓存里拿不到按尺寸的
#: 版本,而且写成主题名时桌面能自动跟随图标主题。
_ICON_NAME = "doubao-input"

#: 装包后的图标落点(判断主题名能不能用)。
_ICON_PATH = "/usr/share/icons/hicolor/scalable/apps/doubao-input.svg"

#: systemctl 的超时秒数 —— 这些调用会落在 GTK 主线程上,宁可失败也不能挂住界面。
_SYSTEMCTL_TIMEOUT = 5


# ---- 路径 / 后端探测 ----

def autostart_path() -> Path:
    """XDG autostart 条目的落盘位置(尊重 $XDG_CONFIG_HOME)。"""
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config_home) / "autostart" / AUTOSTART_ENTRY


def _unit_installed() -> bool:
    return any(Path(directory, SERVICE_UNIT).is_file() for directory in _UNIT_DIRS)


def _systemd_available() -> bool:
    """systemd 后端能不能用(unit 已装 + 有 systemctl)。"""
    return _unit_installed() and shutil.which("systemctl") is not None


def _systemctl(*args: str) -> tuple[int, str]:
    """`systemctl --user <args>`,返回 (返回码, 输出)。失败不抛异常。"""
    exe = shutil.which("systemctl")
    if exe is None:
        return 127, "systemctl not found"
    try:
        proc = subprocess.run(
            [exe, "--user", *args],
            capture_output=True,
            text=True,
            timeout=_SYSTEMCTL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 1, "systemctl timed out"
    except OSError as e:
        return 1, str(e)
    output = (proc.stdout or "").strip()
    if proc.returncode != 0 and not output:
        output = (proc.stderr or "").strip()
    return proc.returncode, output


def _systemd_enabled() -> bool:
    """unit 是否处于 enabled 状态(注意:static/disabled 都不算)。"""
    if not _systemd_available():
        return False
    rc, output = _systemctl("is-enabled", SERVICE_UNIT)
    # "enabled" / "enabled-runtime" 都算开着;"masked" / "disabled" / "static" 不算。
    state = output.split()[:1]
    return rc == 0 and bool(state) and state[0].startswith("enabled")


def _xdg_enabled() -> bool:
    """XDG autostart 条目是否存在且未被禁用。

    读的是**文件本身**:有人可能用「启动应用程序」把它设成
    `X-GNOME-Autostart-enabled=false` 或 `Hidden=true`,那就算没自启。
    """
    path = autostart_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError as e:
        logger.warning("autostart: cannot read %s: %s", path, e)
        return False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "[")):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key, value = key.strip().lower(), value.strip().lower()
        if key == "hidden" and value == "true":
            return False
        if key == "x-gnome-autostart-enabled" and value == "false":
            return False
    return True


def is_enabled() -> bool:
    """开机自启现在到底开没开(两套后端取或)。"""
    return _xdg_enabled() or _systemd_enabled()


def backend() -> str:
    """当前真正生效的后端名字,给诊断报告用(和 reason() 一样都是给人看的)。"""
    if _systemd_enabled():
        return "systemd 用户服务"
    if _xdg_enabled():
        return "XDG autostart"
    return "未生效"


def supported() -> bool:
    """这台机器上开关能不能用(systemd 后端,或 autostart 目录可写)。"""
    if _systemd_available():
        return True
    directory = autostart_path().parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.debug("autostart: %s not usable: %s", directory, e)
        return False
    return os.access(directory, os.W_OK)


def reason() -> str:
    """开关不可用时给用户看的一句话(可用时返回空串)。"""
    if supported():
        return ""
    return _(
        "no systemd user service, and ~/.config/autostart is not writable"
    )


# ---- 生成 .desktop ----

def _quote(value: str) -> str:
    """desktop entry 的 Exec 参数引用(% 先转义成 %%,见 spec「值的转义」)。"""
    value = str(value).replace("%", "%%")
    if not value:
        return '""'
    if any(char in value for char in ' \t\n"\\`$'):
        value = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("`", "\\`")
            .replace("$", "\\$")
        )
        return f'"{value}"'
    return value


def _source_src_dir() -> Optional[Path]:
    """从仓库源码运行时返回 src/ 目录;装进 site-packages 时返回 None。

    判据是模块自己的落点:仓库里是 ``<repo>/src/doubao_input/…``,旁边还有
    ``pyproject.toml``;装过的则是 ``/usr/lib/python3/dist-packages/…``。
    """
    source = Path(__file__).resolve()
    src_dir = source.parents[1]  # .../src/doubao_input/autostart.py → .../src
    if src_dir.name == "src" and (src_dir.parent / "pyproject.toml").is_file():
        return src_dir
    return None


def exec_command() -> str:
    """登录时用来拉起应用的命令。

    * 源码运行 → 当前解释器 + ``PYTHONPATH`` 指回仓库的 src/(跑的就是这份);
    * 装过 .deb → ``/usr/bin/doubao-input`` 包装脚本(它会挑
      ``~/.local/share/doubao-input/.venv``,纯 Python 依赖都在那里面);
    * 兜底 → 当前解释器 ``-m doubao_input``。
    """
    src_dir = _source_src_dir()
    if src_dir is not None:
        env = shutil.which("env") or "/usr/bin/env"
        parts = (env, f"PYTHONPATH={src_dir}", sys.executable, "-m", "doubao_input")
        return " ".join(_quote(part) for part in parts)
    installed = shutil.which("doubao-input")
    if installed:
        return _quote(installed)
    return " ".join(_quote(part) for part in (sys.executable, "-m", "doubao_input"))


def _desktop_entry() -> str:
    # 用主题名(装过包 hicolor 里就有 doubao-input);源码运行时图标不存在,
    # 桌面会退回通用图标,但不影响自启本身。
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=Doubao Voice Input\n"
        "Name[zh_CN]=豆包语音输入法\n"
        "Name[zh_TW]=豆包語音輸入法\n"
        "Comment=Start automatically when you sign in\n"
        "Comment[zh_CN]=登录桌面后自动启动豆包语音输入法\n"
        "Comment[zh_TW]=登入桌面後自動啟動豆包語音輸入法\n"
        f"Exec={exec_command()}\n"
        f"Icon={_ICON_NAME}\n"
        "Terminal=false\n"
        "StartupNotify=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def _write_entry(errors: list[str]) -> None:
    path = autostart_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_desktop_entry(), encoding="utf-8")
    except OSError as e:
        logger.warning("autostart: cannot write %s: %s", path, e)
        errors.append(str(e))
        return
    logger.info("autostart: entry written (%s)", exec_command())


def _remove_entry(errors: list[str]) -> None:
    path = autostart_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as e:
        logger.warning("autostart: cannot remove %s: %s", path, e)
        errors.append(str(e))
        return
    logger.info("autostart: entry removed")


def _systemd(action: str) -> Optional[str]:
    """`systemctl --user <action> doubao-input.service`。

    返回 None = 成功(或这台机器没有要管的 unit),否则返回错误说明。
    """
    if not _unit_installed():
        return None
    if shutil.which("systemctl") is None:
        return _("systemctl is not available")
    rc, output = _systemctl(action, SERVICE_UNIT)
    if rc == 0:
        logger.info("autostart: systemctl --user %s ok", action)
        return None
    logger.warning("autostart: systemctl --user %s failed: %s", action, output or rc)
    return output or f"systemctl --user {action} failed (rc={rc})"


# ---- 开关 ----

def set_enabled(enabled: bool) -> tuple[bool, str]:
    """切换开机自启,返回 ``(是否成功, 失败原因)``。"""
    enabled = bool(enabled)
    errors: list[str] = []

    if enabled:
        if _systemd_available():
            # 上一次「关」可能用了 mask(见模块文档),先揭开再 enable。
            unmask_error = _systemd("unmask")
            if unmask_error:
                errors.append(unmask_error)
            error = _systemd("enable")
            if error is None:
                # 后端一个就够:顺手清掉可能遗留的 XDG 条目,免得登录时拉两次。
                _remove_entry(errors)
            else:
                errors.append(error)
                _write_entry(errors)  # enable 没成,总得留条能用的路
        else:
            _write_entry(errors)
    else:
        if _systemd_available():
            error = _systemd("disable")
            if error:
                errors.append(error)
            if _systemd_enabled():
                # disable 打了招呼却关不掉:多半是 .deb 装的时候被 debhelper
                # **全局** enable 到 /etc/systemd/user(root 的地盘)。用
                # 用户级 mask 盖住它,开关才真的关得掉。
                error = _systemd("mask")
                if error:
                    errors.append(error)
        # 两套都清:哪怕自启是别人(README 里的 systemctl)打开的也得关掉。
        _remove_entry(errors)

    if is_enabled() == enabled:
        return True, ""
    return False, errors[-1] if errors else _("autostart state did not change")
