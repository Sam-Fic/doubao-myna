"""Myna HUD front-end for doubao-input.

豆包的识别/注入逻辑保持不变,桌面上的悬浮胶囊改由 Myna 的 `myna-hud`
渲染器绘制:Rust + GTK4/libadwaita + GPU 波形丝带。

三者关系是单向的,互不侵入:

    doubao 逻辑 (本项目)
        └─ hud.bridge.MynaHudBridge     状态机 → 线状态映射
            └─ hud.publisher.DictationPublisher   发布 com.canonical.Myna.Dictation
                └─ myna-hud (独立进程,GTK4)       只消费属性,拥有全部像素

发布端与渲染端之间只有 D-Bus 属性,没有 GTK、没有共享内存、没有 snap:
`myna-hud` 直接从 ~/Desktop/myna/client 用 cargo 编出来即可。

线协议见 ~/Desktop/myna/specs/004-gnome-shell-indicator/contracts/dbus-interface.md。
"""

from doubao_input.hud.bridge import MynaHudBridge

__all__ = ["MynaHudBridge"]
