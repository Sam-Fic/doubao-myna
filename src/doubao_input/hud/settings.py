"""用户偏好的持久化(~/.config/doubao-input/settings.json)。

目前两个键:
  hud_enabled   悬浮窗用 Myna 胶囊还是内置悬浮窗
  inject_shift  粘贴是 Ctrl+Shift+V 还是 Ctrl+V

旧的 hud.json(只有 hud_enabled)会被自动读进来,不破坏已有配置。
"""

from __future__ import annotations

import json
import logging

from doubao_input.doubao.config import HUD_ENABLED, INJECT_USE_SHIFT, get_config_dir

logger = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"
LEGACY_FILE = "hud.json"


def _path():
    return get_config_dir() / SETTINGS_FILE


def load_all() -> dict:
    try:
        with open(_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("settings unreadable (%s), using defaults", e)
        return {}
    # 兼容早期只写 hud.json 的安装
    try:
        with open(get_config_dir() / LEGACY_FILE, "r", encoding="utf-8") as fh:
            legacy = json.load(fh)
        if isinstance(legacy, dict) and "enabled" in legacy:
            return {"hud_enabled": bool(legacy["enabled"])}
    except Exception:
        pass
    return {}


def get(key: str, default):
    value = load_all().get(key, default)
    return value


def set_value(key: str, value) -> None:
    data = load_all()
    data[key] = value
    try:
        with open(_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except Exception as e:
        logger.warning("could not persist %s: %s", key, e)


def load_enabled() -> bool:
    return bool(get("hud_enabled", HUD_ENABLED))


def save_enabled(enabled: bool) -> None:
    set_value("hud_enabled", bool(enabled))


def load_inject_shift() -> bool:
    return bool(get("inject_shift", INJECT_USE_SHIFT))


def save_inject_shift(enabled: bool) -> None:
    set_value("inject_shift", bool(enabled))
