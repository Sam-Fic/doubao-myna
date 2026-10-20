# 与 Myna 的体验对齐情况

> 目标:**除了后端语音识别(豆包 ASR)之外,应用体验尽量用 Myna 的设计**。
> 本文按维度逐项对照 Myna(`/home/sam/Desktop/myna`)与本项目,标注当前状态与剩余差距。
>
> 图例:✅ 已对齐 · 🟡 部分对齐 / 有意偏离 · ❌ 未移植 · ➖ 不适用(后端不同)

状态截至:界面改用 Myna + 触发可配置之后。

---

## 1. 触发与按键配置

| 设计点 | Myna | 本项目 | 状态 |
|---|---|---|---|
| 快捷键载体 | 桌面自定义快捷键(GNOME dconf / Xfce xfconf),命令是 `gdbus call … Dictation.Toggle` | 同样实现(`trigger/desktop_shortcut.py`,GNOME + Xfce) | ✅ |
| 可用按键 | 任意组合键,`<Super>j` 默认(需 Ctrl/Alt/Super 或功能键/媒体键,裸字母不收) | 同样规则(`control_window._on_capture_key`) | ✅ |
| 录入交互 | 键帽 + 「Set up / Change」按钮 → 捕获窗口(Esc 取消) | 键帽 + 「设置 / 更改」→ 捕获窗口 | ✅ |
| 物理键直连 | 无(只走桌面) | 额外支持 evdev 物理键(默认右 Ctrl,设置窗口可选 12 种) | 🟡 超集 |
| 触发模式 | **toggle**:按一下开始、再按一下结束 | 两种:`hold`(默认,豆包原生)/ `toggle`(Myna 语义),可在设置窗口切换 | 🟡 默认沿用 hold |
| 重复按键抑制 | `REPEAT_QUIET=800ms` + `REPEAT_FOLLOW=200ms` 判定长按重复 | evdev 直接忽略 `value==2` 的 autorepeat | ✅ 机制不同,效果一致 |
| 独占按键 | 不独占(桌面托管) | evdev 不做 `EVIOCGRAB`,事件照常传给前台应用 | ✅ |
| 按键可配持久化 | 桌面自己的设置 | `~/.config/doubao-input/settings.json`(`trigger_key` / `trigger_mode` / `desktop_shortcut`) | ✅ |
| 热插拔 | — | evdev 每秒重扫 `/dev/input/event*` | ✅ |

剩余差距:
- ❌ 未做**屏幕阅读器播报**(Myna 捕获按键时会 announce 状态与拒绝原因)。

> **冲突检测已做**:写键前查 5 个 GNOME schema + 其它自定义快捷键;桌面保留键
> (`-static`)提示"换一个",别人的自定义键弹 `Adw.AlertDialog`「替换?」(Replace 为 destructive)。

> **关于「焦点离开时结束」**:Myna 靠 IBus 精确知道目标字段;本项目走剪贴板,只能问桌面,
> 而 Wayland 下第三方进程**读不到别的窗口的焦点**(GNOME Shell 的 `Eval` 默认关闭)。
> 所以它是**可选开关且默认关闭**:X11 会话能真正生效;Wayland 下探测值可能抖动,
> 故加了"连续 2 次读到变化才认定"的去抖,仍建议只在确实需要时打开。

## 2. 会话生命周期与结束方式

| 设计点 | Myna | 本项目 | 状态 |
|---|---|---|---|
| 静音自动结束 | `silence-timeout`,默认 **30s**,`0`=不自动结束(0–600) | 已实现,同样默认 30s / 0–600,设置窗口 SpinRow | ✅ |
| 最长录音时长 | 同上(静音超时即上限) | 同上 | ✅ |
| 最短按压 | 无(按一下即开始) | `MIN_PRESS_DURATION=0.15s` 防误触 | 🟡 有意保留(误触保护) |
| 取消 | 无取消键:再按一次 / 焦点丢失 / 目标窗口关闭 | **ESC 取消**(键可配)、toggle 模式下再按一次、开启「焦点离开时结束」后焦点一走即取消 | ✅ 超集 |
| 停止后收尾 | `finalizing` 直到终稿或超时 | `STOPPING` + `STOP_SAFETY_TIMEOUT=1.0s` 兜底 | 🟡 机制不同(云端 ASR) |
| 空结果 | `notice`「No speech detected」(可恢复,不是错误) | 已实现:`on_empty_result` → notice「没有听到内容」 | ✅ |
| 焦点丢失结束 | 有(IBus 通道天然感知),丢弃本次文本 | 可选开关(默认关):`ui/focus_watch.py` best-effort 探测,连续 2 次读到焦点变了才结束并丢弃 | 🟡 默认关(见下) |
| 结束后的按键对齐 | `resync()` 防奇偶错位 | toggle 模式按 `recording_state` 判断 | ✅ |

## 3. 注入

| 设计点 | Myna | 本项目 | 状态 |
|---|---|---|---|
| 通道 | **IBus**(`CommitText` / 可选 preedit) | 剪贴板(`wl-copy`) + uinput 合成 `Ctrl(+Shift)+V` | ➖ 有意不同:IBus 不支持中文逐字输入 |
| 目标固定 | 会话开始时捕获目标,不重定向 | 无所谓"目标":注入到当前焦点窗口 | ➖ |
| **密码框 / 安全字段拒绝** | 有(`PURPOSE_PASSWORD/PIN`、`HINT_HIDDEN_TEXT`,提交前再查一次) | ❌ **完全没有** | ❌ 隐私风险,值得补 |
| 失败降级 | `Unavailable` 时重连一次;失败作为本次错误上报(不静默丢字) | 失败时给出提示「粘贴失败,文字仍在剪贴板,可手动 Ctrl+Shift+V」+ Toast | 🟡(不重连) |
| 按键组合可配 | — | `inject_shift`(Ctrl+Shift+V ↔ Ctrl+V),设置窗口开关 | ✅ |
| 只发字面文本 | 是(绝不合成 Tab / Super / 功能键) | 是(只合成粘贴快捷键) | ✅ |

## 4. 指示器 / 悬浮胶囊

| 设计点 | Myna | 本项目 | 状态 |
|---|---|---|---|
| 渲染器 | `myna-hud`(Rust/GTK4/GLSL) | 同一个渲染器,从源码编译 | ✅ |
| 接缝 | `com.canonical.Myna.Dictation` 属性 | 同(State / StatusMessage / AudioRms / AudioPeak / HudStyle) | ✅ |
| 状态取值 | idle/loading/recording/transcribing/finalizing/notice/error | 同(`transcribing` 未用:云端流式在 recording 期间就出字) | 🟡 |
| 电平 | 15–20Hz,**从不去重** | 20Hz + 插值平滑(麦克风 RMS 只有 ~4Hz) | ✅ |
| hud-style | GSettings `hud-style`:bar / ribbon / vumeter | 设置窗口下拉(`settings.json` 的 `hud_style`),实时生效 | ✅ |
| 提示停留 | notice 8–15s(按字数)、error 不自动消失 | notice 6s / error 10s(可在 `config.py` 改) | 🟡 |
| 无渲染器时 | 桌面通知兜底(单条原地替换,Urgency=Normal) | 已实现(`ui/notifier.py`:单 id 原地替换、错误用 Urgent、notice 8–15s 自隐、文案不含转写) | ✅ |
| 转写文本上屏 | 契约禁止(C3) | 有意偏离:`HUD_SHOW_TRANSCRIPT` 把最新一段文本放进 StatusMessage | 🟡 有意 |
| 定位 | 扩展用 `Meta.WaylandClient` 收编 → 底部居中、避 dock | 装 `myna-shell` 扩展即一致;未装则由混成器摆位 | 🟡 见 README |

## 5. 设置窗口

| 设计点 | Myna Settings | 本项目 | 状态 |
|---|---|---|---|
| 壳 | Adw.ApplicationWindow + ToolbarView + HeaderBar + ViewSwitcher + ToastOverlay | 同 | ✅ |
| 页签 | General / Model / Diagnostics | 账号 / 输入 / 诊断(Model 不适用:没有本地模型) | 🟡 |
| 设置项由 schema 推导 | 是 | 手写行(键少,可接受) | 🟡 |
| 声音开关 / 音色 / 预览 | 有(7 种音色 + 预览按钮) | ❌ 无提示音 | ❌ |
| 「When to transcribe」(流式/整段) | 有 | ➖ 云端流式,始终边说边出字 | ➖ |
| 语言选择 | 有 | ➖ 豆包固定中文 | ➖ |
| 诊断页 | 隐私诊断报告 + 复制按钮 + 性能告警 | 已有隐私报告(刷新 / 复制,路径一律 `[redacted]`,不含音频与识别文本)+ 最近错误;**无**性能告警 | 🟡 |

## 6. 声音 / 通知 / 无障碍

| 设计点 | Myna | 本项目 | 状态 |
|---|---|---|---|
| 开始/结束/错误提示音 | 有(`sounds` + `sound-set`) | 有开关(`ui/sounds.py`),播系统 freedesktop 事件音,不搬运 Myna 的音频资源 | 🟡 音色不可选 |
| 桌面通知兜底 | 有 | 有(`ui/notifier.py`) | ✅ |
| 减弱动效 | 跟随 `gtk-interface-reduced-motion` | Myna 胶囊自动跟随;内置悬浮窗也跟随(`ui/overlay.py`,只读运行时属性,不碰 a11y schema) | ✅ |
| 高对比 / 深浅色 | 跟随 Adw.StyleManager | 胶囊跟随;内置悬浮窗是写死的暗色胶囊 | 🟡 |
| 屏幕阅读器播报 | 状态变化可感知、捕获按键 announce | ❌ 无 | ❌ |

## 7. 首次运行引导

| 设计点 | Myna | 本项目 | 状态 |
|---|---|---|---|
| Onboarding 向导 | 3 步:Welcome → 安装组件 → 设置快捷键 | ❌ 无(直接弹控制窗口 + 一条启动提示) | ❌ |
| 引导即隐私承诺 | "Dictation runs locally…" | ➖ 本项目是云端 ASR,不适用 | ➖ |
| 登录流程 | 无(本地模型) | WebKitGTK 登录豆包(本项目必需) | ➖ |

## 8. 诊断与日志

| 设计点 | Myna | 本项目 | 状态 |
|---|---|---|---|
| 最近错误(LastError/Detail/Time) | D-Bus 三属性 + 诊断页展示 | 已实现:契约顺序 Detail→Time→Error,诊断页显示「标题(时间)」 | ✅ |
| 丢包计数 | `AudioDroppedNotActive` | ❌ 无 | ❌ |
| 麦克风健康度 | 每次会话上报 offset / noise floor / speech 电平 | 只有「检查麦克风」手动按钮(输出 peak/avg) | 🟡 |
| 日志开关 | `--verbose` 等 | `-v / --verbose`、`--quiet`(`do_command_line`);仍无文件日志 | 🟡 |

---

## 剩下的活(按优先级)

**P0(体验/隐私)**
1. **注入前判断安全字段**:至少能识别 `Gtk.Entry` 的 `visibility=false` / `input-purpose=password`?本项目走剪贴板,拿不到目标字段属性 —— 更现实的做法是:注入前检查焦点窗口是否是我们自己的窗口(已有),并在应用黑名单(`1Password`/`KeePass` 等)里跳过 + 提示。
2. **注入失败要有用户可见提示**(现在是静默失败),并保留文字到剪贴板供手动粘贴。
3. **桌面通知兜底**:渲染器不可用时用 `Gio.Notification` 显示状态(文案不含转写内容,对齐 Myna 的 N8)。

**P1(补齐 Myna 的交互)**
4. ~~快捷键冲突检测~~ ✅ 已做(桌面保留键提示换一个,自定义键弹「替换?」)。
5. ~~提示音~~ ✅ 已做(`sounds` 开关,系统 freedesktop 事件音)。
6. ~~取消~~ ✅ 已做(ESC 取消,键可配)。
7. ~~错误历史~~ ✅ 已做(D-Bus `LastError*` 三属性 + 诊断页显示)。

**P2(完整度)**
8. Onboarding 向导(3 步),至少覆盖"登录豆包 + 设置快捷键 + 装 Myna 胶囊"。
9. ~~诊断页隐私报告~~ ✅ 已做(刷新 / 复制,路径脱敏,不含音频与识别文本);**性能告警**仍未做。
10. ~~日志级别~~ ✅ 已做(`-v` / `--quiet`);**文件日志**仍未做。
11. ~~内置悬浮窗跟随 `reduced-motion`~~ ✅ 已做;**`high-contrast`** 仍未做。

## 有意保留的偏离(不是缺陷)

- **后端不同**:豆包是云端流式 ASR,所以没有"模型/引擎/算力"那页,也不需要"本地推理"的隐私承诺。
- **注入通道不同**:IBus 无法逐字输入中文,继续用剪贴板 + uinput(这是上游 doubao-input 的选择)。
- **`HUD_SHOW_TRANSCRIPT`**:Myna 契约禁止把转写文本放上 D-Bus;本项目为了"边说边出字"主动偏离,可用常量关掉。
- **最短按压 0.15s**:Myna 没有;这是 push-to-hold 的误触保护。
