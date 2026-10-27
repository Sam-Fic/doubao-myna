"""`com.canonical.Myna.Dictation` 线协议常量。

这是本项目里唯一知道 Myna 词汇表的地方,豆包侧的逻辑只说"开始录音了"
"识别到字了",由 bridge 翻译成这里的 State/StatusMessage/AudioRms/AudioPeak。

契约: ~/Desktop/myna/specs/004-gnome-shell-indicator/contracts/dbus-interface.md
"""

from __future__ import annotations

import unicodedata

# --- 总线拓扑 ---

BUS_NAME = "com.canonical.Myna.Dictation"
OBJECT_PATH = "/com/canonical/Myna/Dictation"
INTERFACE = "com.canonical.Myna.Dictation"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"

# --- State 取值(可加性枚举,C8:未知值必须降级而不是崩) ---

IDLE = "idle"                # 没有会话,胶囊隐藏
LOADING = "loading"          # 正在连接(冷启动窗口)
RECORDING = "recording"      # 正在收音
TRANSCRIBING = "transcribing"
FINALIZING = "finalizing"    # 已松手,等最后结果
NOTICE = "notice"            # 可恢复的小问题,会自动消失
ERROR = "error"              # 严重错误

# --- 状态文案(发布端拥有的、不含识别内容的固定标签,C3) ---

STATUS_CONNECTING = "正在连接…"
STATUS_LISTENING = "聆听中…"
STATUS_FINALIZING = "识别中…"
STATUS_NOT_LOGGED_IN = "请先登录豆包"
STATUS_EMPTY = "没有听到内容"

# --- 接口自省 XML ---

INTROSPECTION_XML = """
<node>
  <interface name="com.canonical.Myna.Dictation">
    <property name="State" type="s" access="read"/>
    <property name="StatusMessage" type="s" access="read"/>
    <property name="AudioRms" type="d" access="read"/>
    <property name="AudioPeak" type="d" access="read"/>
    <property name="HudStyle" type="s" access="read"/>
    <property name="LastError" type="s" access="read"/>
    <property name="LastErrorDetail" type="s" access="read"/>
    <property name="LastErrorTime" type="x" access="read"/>
    <method name="Start">
      <arg type="b" name="ok" direction="out"/>
      <arg type="s" name="error" direction="out"/>
    </method>
    <method name="Stop"/>
    <method name="Toggle"/>
    <method name="RegisterClient">
      <arg type="u" name="count" direction="out"/>
    </method>
    <method name="UnregisterClient">
      <arg type="u" name="count" direction="out"/>
    </method>
  </interface>
  <interface name="org.freedesktop.DBus.Properties">
    <method name="Get">
      <arg type="s" name="interface_name" direction="in"/>
      <arg type="s" name="property_name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="GetAll">
      <arg type="s" name="interface_name" direction="in"/>
      <arg type="a{sv}" name="properties" direction="out"/>
    </method>
    <method name="Set">
      <arg type="s" name="interface_name" direction="in"/>
      <arg type="s" name="property_name" direction="in"/>
      <arg type="v" name="value" direction="in"/>
    </method>
    <signal name="PropertiesChanged">
      <arg type="s" name="interface_name"/>
      <arg type="a{sv}" name="changed_properties"/>
      <arg type="as" name="invalidated_properties"/>
    </signal>
  </interface>
</node>
"""


#: 一个“等宽单位”的宽度,单位是 Pango 的 ``approximate_char_width``(≈7.05px
#: at Sans 11pt)。实测各字符占多少单位,向上取整(宁可保守,因为溢出就意味着
#: 胶囊换行、整个 HUD 长高一截):
#:
#:   ``i l . 空格``        0.57  -> 1
#:   ``a 0``               1.14  -> 2
#:   ``A``                 1.28  -> 2
#:   ``W m M``             2.0   -> 2
#:   中文 / 全角标点 / —   2.13  -> 3
#:
#: 注意 `width` 不是 Pango 的 `wcwidth`:后者会给 ``a`` 算 1,而实际渲染要
#: 1.14 个单位,28 个 ``a`` 就溢出到 228px(bug 现场)。所以半角一律按 2 算。
_WIDTH_NARROW = 1     # i / l / . / 空格:实际 0.57,取 1 足够
_WIDTH_NORMAL = 2     # a / A / 0 / W / m:实际 1.1~2.0
_WIDTH_WIDE = 3       # 中文、全角标点、破折号:实际 2.13

#: 这些字符窄到 1 个单位就够(实测 0.57)。
_NARROW_CHARS = frozenset(" .:;,|!il'`-()[]{}/\\")


def _char_width(char: str) -> int:
    """单个字符占几个等宽单位(保守取整)。"""
    if unicodedata.east_asian_width(char) in ("W", "F"):
        return _WIDTH_WIDE
    if char in _NARROW_CHARS:
        return _WIDTH_NARROW
    return _WIDTH_NORMAL


def display_width(text: str) -> int:
    """估算一段文本在胶囊标签里的宽度,单位是 Pango 的“等宽字符数”。

    胶囊是另一个进程,发布端拿不到 Pango 的 layout 上下文,所以只能按字符
    类别估算。取值见 :data:`_WIDTH_NARROW` 那段的实测表。

    混合中英文时这个估算直接相加即可,不需要启动 GTK。
    """
    return sum(_char_width(char) for char in text)


def fit_tail(text: str, max_width: int) -> str:
    """从尾部保留一段不超过 *max_width* 个等宽单位的文本。

    胶囊不换行的前提是**显示宽度**达标,而不是
    字符数达标。超出时前面接一个“…”,表示“更早的话被滚走了”。

    ``max_width`` 用的单位与 :func:`display_width` 一致(2 = 一个中文字)。
    """
    text = text.strip()
    if max_width <= 0:
        return ""
    if display_width(text) <= max_width:
        return text
    # 省略号本身实测 12px = 1.70 单位,按 _WIDTH_NORMAL(2)留出来。
    budget = max_width - _char_width("…")
    kept: list[str] = []
    used = 0
    for char in reversed(text):
        w = _char_width(char)
        if used + w > budget:
            break
        kept.append(char)
        used += w
    return "…" + "".join(reversed(kept))
