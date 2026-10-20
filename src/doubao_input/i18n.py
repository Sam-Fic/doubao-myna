"""界面多语言 —— 源码语言是英文,中文用翻译文件补充。

用法::

    from doubao_input.i18n import _

    menu.append(_("Run Setup Wizard…"), "win.onboarding")

机制:

* 翻译文件放在 ``locale/<语言>/LC_MESSAGES/doubao-input.po``(标准 gettext 格式);
* 运行时优先用编译好的 ``.mo``;没有(或 ``.po`` 更新过)就用本模块自带的纯 Python
  编译器现编一份 —— 优先写回 ``.po`` 旁边(源码运行时可写),不行就写用户缓存目录
  ``~/.cache/doubao-input/``。所以仓库里只提交 ``.po``,**不提交二进制**;
* 语言跟随系统(``LANGUAGE`` / ``LC_ALL`` / ``LC_MESSAGES`` / ``LANG``),没有对应
  翻译就按英文显示(GNOME 应用的标准行为);将来要在设置里加语言选择器,调
  :func:`switch` 即可。

试不同语言::

    LANGUAGE=zh_TW python -m doubao_input
    LANGUAGE=zh_CN python -m doubao_input
"""

from __future__ import annotations

import gettext
import logging
import os
import struct
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

#: gettext 域(也是翻译文件的名字)
DOMAIN = "doubao-input"

#: 源码语言:没有任何翻译时的显示语言
SOURCE_LANGUAGE = "en"

#: 支持的语言(代码 → 展示名,将来做设置里的语言选择器用)
LANGUAGES: dict[str, str] = {
    "en": "English",
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
}

#: gettext .mo 的魔数(小端 0x950412de)
_MO_MAGIC = 0x950412DE

_translation: Optional[gettext.NullTranslations] = None
_current: str = SOURCE_LANGUAGE


# ---- 对外接口 ----


def _(message: str) -> str:
    """翻译一个界面字符串(还没 init 就原样返回)。"""
    if _translation is None:
        return message
    return _translation.gettext(message)


def current() -> str:
    """当前生效的语言代码(如 ``zh_CN``)。"""
    return _current


def available() -> list[str]:
    """仓库里真的有翻译文件的语言(按 LANGUAGES 的顺序)。"""
    base = locale_dir()
    return [
        code
        for code in LANGUAGES
        if (base / code / "LC_MESSAGES" / f"{DOMAIN}.po").exists()
    ]


def init(languages: Optional[Iterable[str]] = None) -> str:
    """初始化翻译,返回实际生效的语言。

    `languages` 为空时跟随系统环境变量。
    """
    global _translation, _current
    candidates = _normalize(languages) if languages else _system_languages()
    lang = _pick(candidates)

    if lang is None:
        _translation = gettext.NullTranslations()
        _current = SOURCE_LANGUAGE
        logger.info("i18n: no matching translation, showing %s", SOURCE_LANGUAGE)
        return _current

    path = _mo_path(lang)
    if path is None:
        _translation = gettext.NullTranslations()
        _current = SOURCE_LANGUAGE
        logger.warning("i18n: no .mo for %s, showing %s", lang, SOURCE_LANGUAGE)
        return _current

    try:
        with open(path, "rb") as fh:
            _translation = gettext.GNUTranslations(fh)
        _current = lang
        logger.info("i18n: using %s (%s)", lang, path)
    except Exception as e:
        logger.warning("i18n: cannot load %s (%s); showing %s", path, e, SOURCE_LANGUAGE)
        _translation = gettext.NullTranslations()
        _current = SOURCE_LANGUAGE
    return _current


def switch(languages: Optional[Iterable[str]]) -> str:
    """运行时切换语言(给将来的语言选择器用;界面需要自己刷新)。"""
    return init(languages)


def locale_dir() -> Path:
    """翻译文件目录 —— 跟着包走,.deb 装进 dist-packages 后也照样在。"""
    return Path(__file__).resolve().parent / "locale"


# ---- 语言探测 ----


def _normalize(languages: Iterable[str]) -> list[str]:
    """'zh-CN' → 'zh_CN','zh_TW.UTF-8' → 'zh_TW';保持顺序去重。"""
    out: list[str] = []
    for raw in languages:
        code = str(raw).strip()
        # 去掉 ".UTF-8" / "@euro" 这类尾巴:locale 字符串长这样
        for separator in (".", "@"):
            if separator in code:
                code = code.split(separator, 1)[0]
        code = code.replace("-", "_")
        if code and code not in out:
            out.append(code)
    return out


def _system_languages() -> list[str]:
    """按 gettext 的优先级读环境变量(LANGUAGE 可以是冒号分隔的列表)。"""
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name)
        if value:
            return _normalize(value.split(":"))
    return []


def _pick(candidates: list[str]) -> Optional[str]:
    """挑一个真的有翻译的语言。

    "zh" 这种泛语言代码,按 LANGUAGES 的顺序取第一个匹配的(zh → zh_CN)。
    """
    have = available()
    if not have:
        return None
    for code in candidates:
        if code in have:
            return code
        for lang in have:
            if lang.split("_")[0] == code.split("_")[0]:
                return lang
    return None


# ---- .po → .mo ----


def _fresh(mo: Path, po: Path) -> bool:
    try:
        return mo.exists() and mo.stat().st_mtime >= po.stat().st_mtime
    except OSError:
        return False


def _cache_mo(lang: str) -> Path:
    root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(root) / DOMAIN / "locale" / lang / "LC_MESSAGES" / f"{DOMAIN}.mo"


def _mo_path(lang: str) -> Optional[Path]:
    """确保有可用的 .mo,返回它的路径。"""
    base = locale_dir() / lang / "LC_MESSAGES"
    po = base / f"{DOMAIN}.po"
    if not po.exists():
        return None
    mo = base / f"{DOMAIN}.mo"
    if _fresh(mo, po):
        return mo
    try:
        data = compile_po(po.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("i18n: cannot compile %s (%s)", po, e)
        return mo if mo.exists() else None
    # 先试着写回 .po 旁边(源码运行时可写);装了只读的系统目录就用缓存目录。
    for target in (mo, _cache_mo(lang)):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return target
        except OSError:
            continue
    return None


#: .po 里的转义序列
_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\",
    "a": "\a", "b": "\b", "f": "\f", "v": "\v", "0": "\0",
}


def _unquote(text: str) -> str:
    """去掉字符串字面量的引号并反转义。"""
    body = text.strip()
    if body.startswith('"') and body.endswith('"') and len(body) >= 2:
        body = body[1:-1]
    out: list[str] = []
    i = 0
    while i < len(body):
        char = body[i]
        if char == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
                continue
        out.append(char)
        i += 1
    return "".join(out)


def parse_po(text: str) -> dict[str, str]:
    """解析 .po,返回 {msgid: msgstr}(跳过 fuzzy 和空译文)。"""
    entries: dict[str, str] = {}
    fuzzy = False
    mode: Optional[str] = None
    parts: dict[str, list[str]] = {"id": [], "str": []}

    def flush() -> None:
        nonlocal fuzzy, mode, parts
        if parts["id"]:
            key = "".join(parts["id"])
            value = "".join(parts["str"])
            if not fuzzy and value:
                entries[key] = value
        fuzzy = False
        mode = None
        parts = {"id": [], "str": []}

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            # 条目上方的标记行:#, fuzzy / #, python-format ...
            if line.startswith("#,") and "fuzzy" in line:
                fuzzy = True
            continue
        if line.startswith("msgid "):
            flush()
            parts["id"].append(_unquote(line[6:]))
            mode = "id"
        elif line.startswith("msgstr "):
            parts["str"].append(_unquote(line[7:]))
            mode = "str"
        elif line.startswith("msgctxt "):
            # 不支持上下文,整条跳过
            flush()
            mode = "skip"
        elif line.startswith('"') and mode in ("id", "str"):
            parts[mode].append(_unquote(line))
    flush()
    return entries


def compile_po(po_text: str) -> bytes:
    """把 .po 文本编译成 .mo 二进制(gettext 的默认小端格式)。"""
    entries = parse_po(po_text)
    header = entries.pop("", "") or (
        'Content-Type: text/plain; charset=UTF-8\nContent-Transfer-Encoding: 8bit\n'
    )

    # 头条目(msgid "")必须排在最前
    catalog = [("", header)] + sorted(entries.items())
    count = len(catalog)

    ids_pool = b"".join(key.encode("utf-8") + b"\x00" for key, _ in catalog)
    strs_pool = b"".join(value.encode("utf-8") + b"\x00" for _, value in catalog)

    offset_originals = 7 * 4
    offset_translations = offset_originals + 8 * count
    offset_ids = offset_translations + 8 * count
    offset_strs = offset_ids + len(ids_pool)

    out = bytearray(
        struct.pack(
            "<IIIIIII", _MO_MAGIC, 0, count,
            offset_originals, offset_translations, 0, 0,
        )
    )

    position = 0
    for key, _value in catalog:
        size = len(key.encode("utf-8"))
        out += struct.pack("<II", size, offset_ids + position)
        position += size + 1
    position = 0
    for _key, value in catalog:
        size = len(value.encode("utf-8"))
        out += struct.pack("<II", size, offset_strs + position)
        position += size + 1

    out += ids_pool
    out += strs_pool
    return bytes(out)
