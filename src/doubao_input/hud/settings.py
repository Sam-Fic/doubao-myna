"""用户偏好的持久化(~/.config/doubao-input/settings.json)。

键一览:
  inject_shift         粘贴是 Ctrl+Shift+V 还是 Ctrl+V
  trigger_key / trigger_mode / silence_timeout   触发相关
  sounds               提示音开关
  stop_on_focus_loss   焦点离开时结束
  desktop_shortcut     桌面自定义快捷键
  hud_style            Myna 胶囊波形样式
  language             界面语言(空串 = 跟随系统)
  onboarding_done      首次运行向导是否已完成

旧的 hud.json(只有 hud_enabled)仍会被读进来 —— 那个键现在没有意义
(Myna 胶囊是唯一外观),但不要因为它是旧的就把整个配置丢掉。
"""

from __future__ import annotations

import json
import logging

from doubao_input.doubao.config import (
    DESKTOP_SHORTCUT,
    HUD_STYLE,
    INJECT_USE_SHIFT,
    SILENCE_TIMEOUT_SECS,
    SOUNDS_ENABLED,
    STOP_ON_FOCUS_LOSS,
    TRIGGER_KEY_NAME,
    TRIGGER_MODE,
    get_config_dir,
)

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


def load_inject_shift() -> bool:
    return bool(get("inject_shift", INJECT_USE_SHIFT))


def save_inject_shift(enabled: bool) -> None:
    set_value("inject_shift", bool(enabled))


def load_trigger_key() -> str:
    return str(get("trigger_key", TRIGGER_KEY_NAME))


def save_trigger_key(name: str) -> None:
    set_value("trigger_key", str(name))


def load_trigger_mode() -> str:
    mode = str(get("trigger_mode", TRIGGER_MODE)).lower()
    return "toggle" if mode == "toggle" else "hold"


def save_trigger_mode(mode: str) -> None:
    set_value("trigger_mode", "toggle" if mode == "toggle" else "hold")


def load_sounds() -> bool:
    return bool(get("sounds", SOUNDS_ENABLED))


def save_sounds(enabled: bool) -> None:
    set_value("sounds", bool(enabled))


def load_stop_on_focus_loss() -> bool:
    return bool(get("stop_on_focus_loss", STOP_ON_FOCUS_LOSS))


def save_stop_on_focus_loss(enabled: bool) -> None:
    set_value("stop_on_focus_loss", bool(enabled))


def load_silence_timeout() -> int:
    try:
        value = int(get("silence_timeout", SILENCE_TIMEOUT_SECS))
    except (TypeError, ValueError):
        value = SILENCE_TIMEOUT_SECS
    return max(0, min(600, value))


def save_silence_timeout(seconds: int) -> None:
    set_value("silence_timeout", max(0, min(600, int(seconds))))


def load_desktop_shortcut() -> str:
    return str(get("desktop_shortcut", DESKTOP_SHORTCUT))


def save_desktop_shortcut(accelerator: str) -> None:
    set_value("desktop_shortcut", str(accelerator))


def load_hud_style() -> str:
    return str(get("hud_style", HUD_STYLE))


def save_hud_style(nick: str) -> None:
    set_value("hud_style", str(nick))


def load_onboarding_done() -> bool:
    return bool(get("onboarding_done", False))


def save_onboarding_done(done: bool = True) -> None:
    set_value("onboarding_done", bool(done))


def load_language() -> str:
    """界面语言代码(如 zh_CN);空串 = 跟随系统。"""
    return str(get("language", "")).strip()


def save_language(code: str) -> None:
    set_value("language", str(code))
