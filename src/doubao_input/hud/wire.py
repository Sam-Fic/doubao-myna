"""`com.canonical.Myna.Dictation` 线协议常量。

这是本项目里唯一知道 Myna 词汇表的地方,豆包侧的逻辑只说"开始录音了"
"识别到字了",由 bridge 翻译成这里的 State/StatusMessage/AudioRms/AudioPeak。

契约: ~/Desktop/myna/specs/004-gnome-shell-indicator/contracts/dbus-interface.md
"""

from __future__ import annotations

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


def tail(text: str, max_chars: int) -> str:
    """把文本裁到 max_chars,保留**最新**的一段(说话时新字在尾部)。

    Myna 的胶囊标签最多 30 字(超出会换行把胶囊撑大),所以长文本只留尾巴。
    """
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return "…" + text[-(max_chars - 1):]
