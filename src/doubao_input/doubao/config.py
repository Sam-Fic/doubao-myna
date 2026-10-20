"""Constants and configuration for Doubao Murmur Linux port.

Mirrors the fixed parameters from the macOS DoubaoASRClient.swift.
"""

import os
from pathlib import Path

# --- Doubao ASR WebSocket ---

WSS_BASE_URL = "wss://ws-samantha.doubao.com/samantha/audio/asr"

FIXED_QUERY_PARAMS = {
    "version_code": "20800",
    "language": "zh",
    "device_platform": "web",
    "aid": "497858",
    "real_aid": "497858",
    "pkg_type": "release_version",
    "pc_version": "3.12.3",
    "region": "",
    "sys_region": "",
    "samantha_web": "1",
    "use-olympus-account": "1",
    "format": "pcm",
}

ORIGIN = "https://www.doubao.com"
LOGIN_URL = "https://www.doubao.com/chat"

# --- Audio capture ---

AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_DTYPE = "int16"
AUDIO_BLOCKSIZE = 4096  # samples per callback (~256ms at 16kHz)

# --- Auth error detection ---

AUTH_ERROR_CODE = 709599054
AUTH_ERROR_KEYWORDS = [
    "cookie", "auth", "login", "session", "unauthorized", "expired",
]

# --- Paths ---

CONFIG_DIR_NAME = "doubao-input"
PARAMS_FILE = "asr_params.json"
KEYBOARD_FILE = "keyboard.json"


def get_config_dir() -> Path:
    """Get the XDG config directory for the app."""
    config_home = os.environ.get(
        "XDG_CONFIG_HOME", str(Path.home() / ".config")
    )
    app_dir = Path(config_home) / CONFIG_DIR_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_params_path() -> Path:
    """Get the path to the ASR params JSON file."""
    return get_config_dir() / PARAMS_FILE


def get_keyboard_config_path() -> Path:
    """Get the path to the on-screen keyboard geometry JSON file."""
    return get_config_dir() / KEYBOARD_FILE


# --- Timeouts ---

STOP_SAFETY_TIMEOUT = 1.0  # seconds
DEBOUNCE_INTERVAL = 0.3  # seconds
PASTE_DELAY = 0.05  # seconds between copy and paste simulation
AUTH_EXPIRY_DELAY = 2.0  # seconds before resetting after auth error

# --- Paste shortcut ---
# True  -> synthesize Ctrl+Shift+V. Works in GNOME Terminal, Konsole,
#          Alacritty, kitty, xfce4-terminal, VSCode, gedit, Chromium, ...
# False -> synthesize Ctrl+V. Works in GUI apps (VSCode, gedit, browser)
#          but NOT in terminals (terminals treat Ctrl+V as the tty "lnext"
#          literal-next-char escape, inherited from readline's history).
# Default is True because we inject plain text and Ctrl+Shift+V is the
# Wayland/GNOME convention; flip to False if a specific GUI app refuses
# to accept the paste.
INJECT_USE_SHIFT = True

# --- Overlay UI ---

OVERLAY_WIDTH = 760
OVERLAY_HEIGHT = 88
# Transcription text wraps within this many "characters" (Pango's average
# char-width unit ~= the old 760px text column) and the overlay grows in
# height up to OVERLAY_MAX_LINES before the oldest words scroll off.
OVERLAY_TEXT_CHARS = 88
OVERLAY_MAX_LINES = 5
PTT_BUTTON_SIZE = 60

# --- 触发(按键) ---
# 物理键:evdev 键名(见 `python -c "import evdev; print(sorted(evdev.ecodes.KEY))"`)。
TRIGGER_KEY_NAME = "KEY_RIGHTCTRL"
# hold   = 按住说话,松开即结束(豆包原生交互)
# toggle = 按一下开始、再按一下结束(**Myna 的交互**)
TRIGGER_MODE = "hold"
# 静音多久自动结束(秒);0 = 永不自动结束。对齐 Myna 的 silence-timeout(默认 30)。
SILENCE_TIMEOUT_SECS = 30
# 判定"有人声"的 RMS 门限(0~1)。低于它就算静音。
SILENCE_RMS_THRESHOLD = 0.02
# 桌面自定义快捷键(GNOME / Xfce),走 D-Bus Toggle —— 这是 Myna 的做法,
# 于是 <Super>j 这类组合键也能用(evdev 只认得物理单键)。空 = 未绑定。
DESKTOP_SHORTCUT = ""  # 例如 "<Super>j"
TOGGLE_COMMAND = (
    "gdbus call --session --dest com.canonical.Myna.Dictation "
    "--object-path /com/canonical/Myna/Dictation "
    "--method com.canonical.Myna.Dictation.Toggle"
)

# --- Myna HUD (桌面悬浮胶囊) ---
# 启用后,桌面的悬浮指示器改用 Myna 的 `myna-hud` 渲染器(GTK4/libadwaita
# + GPU 波形丝带),豆包的识别/注入逻辑完全不变。渲染器经
# com.canonical.Myna.Dictation 只消费"状态 + 电平"。
HUD_ENABLED = True              # 也可以在控制窗口里实时开关(记在 hud.json)
HUD_AUTO_LAUNCH = True          # 自动拉起 myna-hud 进程
HUD_STYLE = "ribbon"            # bar | ribbon | vumeter | progress
# Myna 的胶囊只显示状态标签(契约 C3 不传识别内容)。豆包的卖点是边说边出字,
# 所以这里把最新一段识别文本放进 StatusMessage —— 这是一处有意的偏离,
# 关掉它就退回"聆听中…"这类固定文案。
HUD_SHOW_TRANSCRIPT = True
HUD_STATUS_MAX_CHARS = 30       # 与 myna-hud 的 LABEL_MAX_CHARS 一致
HUD_LEVEL_HZ = 20               # 契约 C4 的 15~20Hz
HUD_NOTICE_HOLD_MS = 6000       # 可恢复提示停留时长
HUD_ERROR_HOLD_MS = 10000       # 错误提示停留时长

# --- User-Agent for WebView ---

WEBVIEW_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
