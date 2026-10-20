# 豆包语音输入法 Maya 界面版 for Linux

## 项目概述
本项目为基于豆包 Web 版语音识别能力开发的全局语音输入法，专为原生 Wayland 与 GNOME 桌面环境设计。旨在解决 `xdotool` 在 Wayland 下失效以及 `wtype` 依赖 virtual-keyboard 协议（Mutter 未实现）等兼容性问题。
本项目实现了豆包逆向逻辑（包括登录、WebSocket ASR、音频采集），并重构了触发、注入与 UI 交互机制。

> 本仓库为 [wurong98/doubao-input-for-linux](https://github.com/wurong98/doubao-input-for-linux) 的分支：[Sam-Fic/doubao-myna](https://github.com/Sam-Fic/doubao-myna)。
> 识别与注入逻辑沿用豆包方案，界面层替换为 [Myna](https://github.com/canonical/myna) 的图标、悬浮胶囊渲染器及 libadwaita 设置窗口风格。详细设计请参阅 [`docs/design.md`](docs/design.md)。

---

## 界面展示

**项目图标**
采用 Myna 图标（scalable SVG，安装至 hicolor `scalable/apps/`）：
![Logo](src/doubao_input/resources/logo.svg)

**控制窗口**
应用程序主面板（v1.1.0 起采用 libadwaita 三页布局：账号 / 输入 / 诊断）。
![Control window](docs/images/control-window.png)

---

## 核心特性
- **交互模式**：默认 Push-to-Hold（按住说话，松开输入），由物理右 Ctrl 键触发；可切换为 Myna 的「按一下开始 / 再按一下结束」。
- **快捷键可配**：支持写入桌面自定义快捷键（`<Super>j` 这类组合键，命令走 D-Bus `Toggle`，与 Myna 一致），也支持直接指定 evdev 物理键；静音 N 秒自动结束。
- **触发语义对齐 Myna**：静音自动结束（默认 30 秒，`0` 为不启用）、空识别结果给出「没有听到内容」的可恢复提示，而非静默失败。
- **Wayland 原生支持**：通过 `evdev` 监听按键，`uinput` 模拟输入，脱离 X11/XWayland 依赖。
- **中文输入优化**：采用剪贴板写入配合模拟 Ctrl+V 粘贴机制，避免逐键输入导致的延迟。
- **悬浮状态窗**：默认集成 Myna 的 `myna-hud`（libadwaita + GPU 波形渲染）。若未安装，自动降级为内置胶囊窗口（18px 圆角、呼吸透明度、流光闪烁动效，纯白粗体文本确保可读性）。
- **现代化设置界面**：基于 libadwaita 构建三页 PreferencesWindow（账号 / 输入 / 诊断），采用标准组件库。
- **后台常驻运行**：通过 `systemd --user` 实现开机自启，支持单实例运行及窗口唤起。
- **凭证本地持久化**：登录状态及凭证文件存储于 `~/.config/doubao-input/asr_params.json`，支持跨会话复用。
- **免 Root 运行**：仅需将当前用户加入 `input` 用户组（`.deb` 安装脚本自动处理）。

---

## 系统要求

| 组件 | 要求说明 |
|---|---|
| 操作系统 | Ubuntu 25.04 / GNOME 48 / Wayland（实测环境） |
| Python | 3.13 |
| 音频服务 | PipeWire 或 PulseAudio |
| 用户权限 | 当前用户需属于 `input` 组（以访问 `/dev/input/event*` 与 `/dev/uinput`） |
| GUI 依赖 | `gir1.2-adw-1` 与 `libadwaita-1-0`（缺失时自动降级为纯 GTK4 窗口） |
| 可选依赖 | `cargo`、`libgtk-4-dev`、`libadwaita-1-dev`（仅用于编译 Myna 的 `myna-hud`） |

---

## 安装指南

### 二进制包安装（推荐）
从 [`Releases`](https://github.com/wurong98/doubao-input-for-linux/releases) 下载 `.deb` 包，或在仓库根目录执行 `bash packaging/build-deb.sh` 构建。

```bash
# 1. 安装 .deb 包
sudo apt install ./doubao-input_1.0.2-1_all.deb
# 注：apt 将自动解析依赖。postinst 脚本会自动将当前用户加入 input 组，并创建用户级 venv 安装 PyPI 依赖。

# 2. 重新登录系统（使 input 组权限生效），随后启动
doubao-input
# 或配置开机自启
systemctl --user enable --now doubao-input.service
```

**系统级依赖清单**（`.deb` 自动处理）：
`python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `gir1.2-webkit-6.0`, `libgtk-4-1`, `libadwaita-1-0`, `libwebkitgtk-6.0-4`, `wl-clipboard`, `init-system-helpers`, `python3-pip`, `python3-venv`。

**Python 依赖**（由 `postinst` 自动安装至 `~/.local/share/doubao-input/.venv`）：
`websockets`, `sounddevice`, `evdev`。

> 注意：安装后必须重新登录系统，否则 `evdev` 与 `uinput` 将因权限不足导致应用启动失败。

### 源码编译安装

```bash
git clone https://github.com/wurong98/doubao-input-for-linux.git
cd doubao-input

# 1. 安装系统依赖
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 \
                 libgtk-4-1 libadwaita-1-0 libwebkitgtk-6.0-4 wl-clipboard

# 2. 配置用户组（需重新登录生效）
sudo usermod -aG input $USER

# 3. 配置 Python 虚拟环境
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 4. 启动应用
./start.sh
```

### 首次配置
首次启动会先弹出**设置向导**（对齐 Myna 的 onboarding）：欢迎 → 登录豆包（未登录无法继续）→ 设置快捷键（可跳过，之后在设置窗口配置）→ Myna 悬浮胶囊（可选，附安装命令）。向导只出现一次，之后可在设置窗口主菜单「运行设置向导…」重新打开。

在 WebView 中完成豆包网页登录后，内置 JS 拦截器将自动提取 Cookies、`device_id` 及 `web_id`，并写入 `~/.config/doubao-input/asr_params.json`。登录窗口随后自动关闭。

**操作逻辑**：
- **按住右 Ctrl**：唤起悬浮胶囊，实时显示识别文本。
- **松开右 Ctrl**：等待 1 秒超时以接收末尾结果，通过 `wl-copy` 写入剪贴板，并触发 `uinput` 模拟 Ctrl+Shift+V 粘贴至当前焦点输入框。
- **按压时间 < 150ms**：判定为误触，取消注入。
- **会话中按 ESC**：取消并丢弃本次内容。

---

## 界面集成（Myna 方案）

本项目在保留原有识别与注入逻辑的前提下，将 UI 层替换为 Myna 方案。

| 界面模块 | 实现方案 | 代码位置 |
|---|---|---|
| 设置/控制窗口 | libadwaita 三页布局（账号/输入/诊断） | `ui/control_window.py` |
| 悬浮状态胶囊 | Myna `myna-hud`（GTK4 + GPU 波形渲染） | `hud/` |

### 设置窗口
采用 `Adw.ApplicationWindow` 结合 `ToolbarView` 与 `HeaderBar`，内部通过 `Adw.ViewStack` 管理三个配置页。若系统缺失 libadwaita，自动降级为纯 GTK4 窗口。
- **账号页**：管理登录状态、凭证路径及重新登录操作。
- **输入页**：桌面快捷键（键帽展示 + 按键捕获，Esc 取消）、evdev 物理键、触发方式（按住 / 按一下）、静音自动结束秒数、焦点离开时结束（可选开关）、提示音开关、波形样式、粘贴快捷键（Ctrl+V / Ctrl+Shift+V）及悬浮窗组件选择。
- **诊断页**：提供麦克风自检、剪贴板链路测试、悬浮窗状态监控、最近错误记录（含时间），以及隐私安全的诊断报告（可刷新 / 复制；不含音频、识别文本或文件路径，路径一律替换为 `[redacted]`）。

### 触发配置（与 Myna 对齐）

| 项目 | Myna | 本项目 |
|---|---|---|
| 快捷键载体 | 桌面自定义快捷键（GNOME dconf / Xfce xfconf），命令为 `gdbus call … Dictation.Toggle` | 同（`trigger/desktop_shortcut.py`） |
| 可用按键 | 需带 Ctrl/Alt/Super，或功能键 / 媒体键；裸字母不收 | 同（设置窗口内按键捕获，Esc 取消） |
| 物理键直连 | 无 | 额外支持 evdev 物理键（默认右 Ctrl，可选 12 种） |
| 触发模式 | 按一下开始 / 再按一下结束 | 两种模式可选，默认仍为按住说话 |
| 静音自动结束 | `silence-timeout`，默认 30 秒，`0` 为不启用 | 同（0–600 秒可调） |
| 焦点丢失结束 | 始终开启（IBus 通道可感知） | 设为**可选开关，默认关闭**（见下方说明） |
| 空结果 | `notice`「No speech detected」 | 同（「没有听到内容」） |

持久化键位于 `~/.config/doubao-input/settings.json`：`desktop_shortcut`、`trigger_key`、`trigger_mode`、`silence_timeout`、`hud_style`。

### 悬浮胶囊与 D-Bus 集成
悬浮胶囊作为独立进程运行，通过 D-Bus 属性接收状态更新。
- **接口定义**：`com.canonical.Myna.Dictation`（包含 State, StatusMessage, AudioRms, AudioPeak, HudStyle）。
- **状态映射**：
  - `loading`：连接 WebSocket 中。
  - `recording`：录音中，显示实时识别文本或“聆听中…”。
  - `finalizing`：等待最终识别结果。
  - `error` / `notice`：显示错误提示或通知。
  - `idle`：隐藏胶囊。
- **数据推送**：音频电平（RMS）以 20Hz 频率推送，并进行插值平滑处理。

**启用 Myna 渲染器**：
```bash
# 1. 编译渲染器
bash scripts/build-myna-hud.sh

# 2. 启动应用（默认开启“使用 Myna 悬浮胶囊”）
./start.sh
```
若渲染器未安装或启动失败，系统将静默降级至内置悬浮窗（`ui/overlay.py`）。

### GNOME Shell 扩展集成（原生定位）
Myna 的窗口定位**完全由 GNOME 扩展完成**，`myna-hud` 自己在 Wayland 下从不定位
（Myna 源码 `extensions/myna-shell/place.js` 的注释写得很直白：*on Wayland a client
cannot position itself, so the host computes the frame position and applies it with
`move_frame`*）。所以想要原版定位，必须让 shell 加载这个扩展：

```bash
# 1. 安装扩展（会自动给 resolve.js 打补丁：优先用 ~/.local/bin/myna-hud，不经 snap）
bash scripts/install-gnome-extension.sh

# 2. 注销并重新登录一次（GNOME Shell 只在登录时读取 ~/.local/share/gnome-shell/extensions）
#    重登后扩展自动启用；也可以手动确认：
gnome-extensions enable myna-shell@canonical.com
```

之后由扩展负责拉起 `myna-hud` 并把窗口摆到「当前有焦点窗口的显示器」底部居中
（距工作区底边 24px、避开 panel 与 dash-to-dock、点击穿透、崩溃自动重启）。
本项目检测到扩展启用（`org.gnome.shell enabled-extensions`）就不再自己拉进程，
不会出现两个胶囊；万一扩展 5 秒内没把渲染器拉起来，会自己拉一个兜底
（那时位置由混成器决定）。

> ⚠️ **不装扩展会怎样**：`myna-hud` 是一个普通窗口，位置由混成器决定
> （GNOME 上大致是屏幕中间）—— **Myna 自己不装扩展时也是这样**，不是本项目的 bug。
安装脚本会自动配置 `MYNA_HUD_BINARY` 环境变量，使扩展直接调用本地编译的二进制文件，无需依赖 Snap。

**环境兼容性与排查**：
- X11 或非 GNOME 环境下，扩展自动休眠，渲染器以普通窗口模式启动（支持 EWMH 定位与点击穿透）。
- 若出现双进程冲突，请检查扩展启用状态，或将 `config.py` 中的 `HUD_AUTO_LAUNCH` 设为 `False`。

---

## 配置参数
核心配置文件位于 `src/doubao_input/doubao/config.py`：

| 常量 | 默认值 | 说明 |
|---|---|---|
| `HUD_ENABLED` | `True` | 是否优先使用 Myna 胶囊（用户设置存储于 `settings.json`） |
| `HUD_AUTO_LAUNCH` | `True` | 是否自动拉起 `myna-hud` 进程 |
| `HUD_STYLE` | `"ribbon"` | 波形渲染样式（bar / ribbon / vumeter / progress） |
| `HUD_SHOW_TRANSCRIPT` | `True` | 是否在胶囊中显示实时识别文本 |
| `HUD_STATUS_MAX_CHARS` | `30` | 状态文案最大字符数 |
| `HUD_LEVEL_HZ` | `20` | 音频电平推送频率 |
| `INJECT_USE_SHIFT` | `True` | 是否使用 Ctrl+Shift+V 进行粘贴 |
| `TRIGGER_KEY_NAME` | `"KEY_RIGHTCTRL"` | evdev 物理键名 |
| `TRIGGER_MODE` | `"hold"` | 触发模式：`hold`（按住说话）/ `toggle`（Myna 语义） |
| `SILENCE_TIMEOUT_SECS` | `30` | 静音自动结束秒数，`0` 为不启用 |
| `SOUNDS_ENABLED` | `True` | 开始 / 结束 / 错误时播放提示音（系统 freedesktop 事件音） |
| `CANCEL_KEY_NAME` | `"KEY_ESC"` | 会话中按该键取消并丢弃本次内容；设为空串则不接取消键 |
| `STOP_ON_FOCUS_LOSS` | `False` | 焦点离开目标窗口即结束并丢弃本次内容（对齐 Myna），默认关闭 |
| `FOCUS_CONFIRM_TICKS` | `2` | 连续几次读到焦点变化才认定（防 X11/XWayland 抖动误伤） |
| `DESKTOP_SHORTCUT` | `""` | 桌面自定义快捷键，如 `"<Super>j"` |

> 以上均为默认值；用户在设置窗口中的选择保存在 `~/.config/doubao-input/settings.json`。
> 与 Myna 的逐项体验对照（含未移植项）见 [`docs/myna-parity.md`](docs/myna-parity.md)。

---

## 开发指南

### 项目结构
```text
src/doubao_input/
├── __main__.py            # 程序入口
├── app.py                 # GtkApplication 生命周期管理
├── doubao/                # 豆包逆向核心（ASR、音频采集、凭证管理）
├── trigger/evdev_ptt.py   # 物理按键监听（evdev，键可配）
├── trigger/desktop_shortcut.py  # 桌面自定义快捷键（GNOME/Xfce，走 D-Bus Toggle）
├── inject/injector.py     # 剪贴板与 uinput 注入
├── hud/                   # Myna 悬浮窗 D-Bus 桥接与进程管理
└── ui/                    # GTK4/libadwaita 界面实现
```

### 探针测试
`tests/probe/` 目录包含用于验证核心链路可用性的独立测试脚本：
- `P5_login.py`：验证豆包登录与凭证写入。
- `P6_asr.py`：验证 WebSocket 连接与 ASR 识别。

### 日志调试
默认日志级别为 `INFO`，输出到 stderr：

```bash
./start.sh --verbose        # 或 -v，打印 DEBUG（evdev 设备扫描、D-Bus 细节等）
./start.sh --quiet          # 只看 WARNING 及以上
./start.sh --show           # 唤起控制窗口（.desktop 的 show-control action）
./start.sh --log-file ~/doubao-input.log   # 同时写入文件
```

---

## 打包发布
项目提供基于 `debian/` 目录的 `.deb` 打包脚本及 systemd user service 配置。

```bash
# 构建 .deb 包
bash packaging/build-deb.sh

# 安装与自启
sudo dpkg -i doubao-input_*.deb
systemctl --user enable --now doubao-input.service
```

---

## 已知限制
1. **粘贴快捷键兼容性**：默认使用 Ctrl+Shift+V 以兼容终端环境，部分 GUI 应用仅支持 Ctrl+V，需在设置界面手动切换。
2. **默认悬浮窗定位**：未安装 GNOME 扩展时，`myna-hud` 作为普通窗口运行，位置由混成器分配，无法实现原生底部居中与防遮挡。
3. **系统托盘可见性**：GNOME 48 默认隐藏 StatusNotifierItem，需安装 AppIndicator 扩展方可显示托盘图标。
4. **接口稳定性**：依赖豆包 Web 版非公开接口，若官方变更 API，可能导致 ASR 失效。
5. **剪贴板占用**：输入过程会覆盖系统剪贴板当前内容。
6. **「焦点离开时结束」为 best-effort**：Myna 通过 IBus 精确感知目标字段，本项目走剪贴板只能询问桌面。
   X11 会话可真正生效；Wayland 下第三方进程读不到其它窗口的焦点（GNOME Shell 的 `Eval` 默认关闭），
   该开关会置灰并说明原因，即使可用也建议先试用再长期开启（已内置“连续两次读到变化才认定”的去抖）。

---

## 安全与隐私说明
- **凭证存储**：豆包登录 cookies 存于 `~/.config/doubao-input/asr_params.json`，
  文件权限 0600、配置目录 0700，仅当前用户可读。明文 JSON 仍是安全边界以内的
  折衷，介意者可在退出登录后确认文件已删除（退出登录会自动删除）。
- **`input` 用户组的代价**：免 root 依赖把用户加入 `input` 组，该组成员可以
  读取系统上**所有**键盘/鼠标事件流（也意味着具备键盘嗅探能力）。这是 evdev
  方案的必然要求，请知悉后再安装。
- **识别文本**：识别结果只写入剪贴板并模拟粘贴，注入成功后 1.5 秒内会自动
  清空剪贴板；日志只记录文本长度，不记录内容。但剪贴板管理器（如 GPaste）
  可能在清空之前已保存历史，对隐私敏感的语音请自行评估。
- **ASR 通道**：音频经 WSS（TLS）直达 `ws-samantha.doubao.com`，本机无代理
  中转、无第三方上报。

---

## 更新日志
完整记录请参阅 [`debian/changelog`](debian/changelog)。

### v1.1.0 (2026-10-21)
- 重构设置界面，采用 libadwaita 三页布局。
- 集成 Myna `myna-hud` 渲染器及 D-Bus 状态同步机制。
- 替换应用图标为 Myna 官方 SVG 图标。
- 修复 `myna-hud` 异常终止导致的 GLib 断言警告及 `EvdevPtt` 异常阻断启动的问题。
- 统一偏好设置存储至 `~/.config/doubao-input/settings.json`。
- 新增可配置触发：桌面自定义快捷键（组合键）、evdev 物理键选择、Myna 式 toggle 触发、静音自动结束。
- 空识别结果改为可恢复提示（对齐 Myna 的 “No speech detected”）。
- 新增桌面通知兜底：胶囊不可用时状态走单条原地替换的通知（文案不含识别文本）。
- 新增提示音（开始 / 结束 / 错误，走系统事件音）与 ESC 取消。
- 新增快捷键冲突检测（桌面保留键提示更换，自定义键弹「替换?」）与最近错误记录（诊断页 + D-Bus `LastError*`）。
- 命令行支持 `-v/--verbose`、`--quiet`、`--show`（后者让 `.desktop` 的 show-control action 真正生效）。
- 内置悬浮窗跟随系统「减弱动效」设置。
- 新增隐私诊断报告（刷新 / 复制，对齐 Myna 的“不含音频、识别文本、文件路径”承诺）。
- 修复：每次粘贴完成后设置窗口会闪一下（无条件隐藏+恢复 → 改为仅在自己抢到焦点时才躲）。
- 新增首次运行向导（欢迎 → 登录 → 快捷键 → Myna 胶囊）与设置窗口主菜单（运行向导 / 关于）。
- 新增 `--log-file` 文件日志；内置悬浮窗支持高对比度。
- 新增 `docs/myna-parity.md`，逐项记录与 Myna 体验设计的对齐情况。

### v1.0.2 (2026-06-21)
- 替换应用图标为 RGBA 真透明版本，消除白色背景边框。

### v1.0.1 (2026-06-21)
- 升级内置悬浮窗视觉效果（圆角、呼吸透明度、流光动效）。
- 修复 Pango 文本渲染及 GTK Overlay 布局相关的排版缺陷。
- 修复 `.desktop` 图标缓存导致的启动图标不更新问题。

### v1.0.0 (2026-06-21)
- 初始版本发布，实现全局 Push-to-Hold 语音输入及 `.deb` 打包支持。

---

## 致谢
- **[Myna](https://github.com/canonical/myna)** (AGPL-3.0-or-later)：提供应用图标、`myna-hud` 渲染器、GNOME Shell 扩展方案及 libadwaita UI 规范。本项目通过本地编译与 D-Bus 属性进行集成。
- **[doubao-murmur](https://github.com/yourname/doubao-murmur)** (MIT)：提供豆包逆向逻辑（登录、WebSocket ASR、音频采集）的 Linux 移植基础。
- **[wurong98/doubao-input-for-linux](https://github.com/wurong98/doubao-input-for-linux)** (MIT)：上游项目，提供 Push-to-Hold 交互、evdev/uinput 注入及 WebKit 登录窗口实现。
- **豆包 (Doubao)**：提供底层 Web 版流式 ASR 服务（本项目为非官方逆向实现，与字节跳动无关联）。
- **开源社区**：感谢 `evdev`、`uinput`、`wl-clipboard`、GTK4、libadwaita 及 PortAudio 等基础组件的支持。

---

## 许可证
本项目基于 AGPL-3.0-or-later 许可证开源，详见 [`LICENSE`](LICENSE)。
第三方组件归属及 Myna AGPL 协议说明详见 [`NOTICE`](NOTICE)。