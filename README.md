# 豆包语音输入法 for Linux

> 在 Ubuntu / GNOME / Wayland 上,**按住右 Ctrl 说话,松开就把识别出的文字输入到当前输入框**。

本项目把豆包(Doubao)Web 版的语音识别能力做成一个常驻的全局语音输入法,
专为原生 Wayland / GNOME 设计,避开 xdotool 在 Wayland 下失效、`wtype` 依赖 virtual-keyboard 协议
(Mutter 不实现)等问题。本项目从零实现豆包逆向逻辑(登录、WebSocket ASR、音频采集)以及触发、注入与 UI。

> **本仓库**是 [wurong98/doubao-input-for-linux](https://github.com/wurong98/doubao-input-for-linux)
> 的 fork:[**Sam-Fic/doubao-myna**](https://github.com/Sam-Fic/doubao-myna)。
> 识别与注入逻辑仍是豆包那套,界面层换成了 [Myna](https://github.com/canonical/myna) 的
> 图标、悬浮胶囊渲染器和 libadwaita 设置窗口风格 —— 详见文末[致谢](#-致谢)。

详细设计见 [`docs/design.md`](docs/design.md)。

---

## 📸 截图

**项目图标** —— 直接用 Myna 的图标(scalable SVG,安装到 hicolor `scalable/apps/`):

![Logo](src/doubao_input/resources/logo.svg)

**控制窗口** —— 启动 app 后的主面板(v1.1.0 起是 libadwaita 三页:账号 / 输入 / 诊断)。

![Control window](docs/images/control-window.png)

> 图标 + 启动 app 界面均来自 v1.0.1 真实运行环境(已在 Ubuntu 25.04 / GNOME 48 / Wayland 实测);
> 三页设置窗口是 v1.1.0 的新界面,截图待补。

---

## ✨ 特性

- **按住即说,松手即输** —— push-to-hold 交互,右 Ctrl 物理键触发。
- **GNOME / Wayland 原生可用** —— 用 `evdev` 监听 + `uinput` 模拟,不依赖 X11/XWayland。
- **中文 OK** —— 走剪贴板 + 模拟 Ctrl+V,不靠逐键输入。
- **圆角胶囊悬浮窗** —— 默认用 Myna 的 `myna-hud`(libadwaita + GPU 波形丝带),
  未安装时自动退回内置胶囊:18px 圆角 + 1.5px 白边 + 呼吸 alpha(0.78~0.98 / 2.4s 周期)
  + 每识别出新字触发 220ms 流光闪烁;文字始终纯白粗体不参与动效,保证可读。
- **Myna 风格设置窗口** —— libadwaita 三页(账号 / 输入 / 诊断)PreferencesWindow,
  与 Myna Settings 同一套 Adw.PreferencesGroup / ActionRow / SwitchRow。
- **会话常驻** —— `systemd --user` 自启;再次启动唤起控制窗口(单实例)。
- **凭证本地化** —— 登录一次,凭证写在 `~/.config/doubao-input/asr_params.json`,复用至下次。
- **零 sudo 运行** —— 仅需把用户加入 `input` 组(`.deb` 的 `postinst` 自动处理)。

---

## 📦 系统要求

| 组件 | 要求 |
|---|---|
| 操作系统 | Ubuntu 25.04 / GNOME 48 / Wayland(已在该环境实测) |
| Python | 3.13 |
| 音频 | PipeWire / PulseAudio(系统自带) |
| 用户组 | 当前用户需在 `input` 组(访问 `/dev/input/event*` 与 `/dev/uinput`) |
| libadwaita | 设置窗口需要 `gir1.2-adw-1` + `libadwaita-1-0`(缺失时自动退回纯 GTK4 窗口) |
| 可选(胶囊) | `cargo` + `libgtk-4-dev` + `libadwaita-1-dev` —— 只为编 Myna 的 `myna-hud`;不编就用内置悬浮窗 |

---

## 🛠️ 安装

### 普通用户(用 .deb)

`.deb` 在 [`Releases`](https://github.com/wurong98/doubao-input-for-linux/releases)
下载,或在仓库根跑 `bash packaging/build-deb.sh` 自打。**只需两步**:

```bash
# 1. 装 .deb
sudo apt install ./doubao-input_1.0.2-1_all.deb
#   apt 会自动从 Depends 拉所有系统包(下面"完整依赖清单")
#   postinst 会自动:
#     - 把当前 sudo 用户加进 input 组
#     - 创建用户级 venv 并 pip install 3 个 PyPI-only 包

# 2. 重新登录(让 input 组生效)→ 然后跑
doubao-input
# 或开机自启:
systemctl --user enable --now doubao-input.service
```

**完整 apt 依赖清单**(ubuntu 25.04+ 仓库,`.deb` 的 `Depends` 字段):

| 包 | 用途 |
|---|---|
| `python3-gi` | PyGObject(GTK 绑定) |
| `gir1.2-gtk-4.0` | GTK 4 typelib |
| `gir1.2-adw-1` | libadwaita typelib(设置窗口) |
| `gir1.2-webkit-6.0` | WebKitGTK 6.0 typelib(登录窗口) |
| `libgtk-4-1` | GTK 4 运行时 |
| `libadwaita-1-0` | libadwaita 运行时(设置窗口) |
| `libwebkitgtk-6.0-4` | WebKitGTK 6.0 运行时 |
| `wl-clipboard` | `wl-copy` / `wl-paste`(剪贴板读写) |
| `init-system-helpers` | systemd 工具 |
| `python3-pip` *(Recommends)* | postinst 装 venv 用 |
| `python3-venv` *(Recommends)* | postinst 创建 venv 用 |

**3 个 PyPI-only 依赖**(不在 apt,postinst 自动装到 `~/.local/share/doubao-input/.venv`):
`websockets` / `sounddevice` / `evdev`

> ⚠️ **必须重新登录**让 `input` 组生效,否则 evdev 读不到 `/dev/input/event*`、uinput 写不到 `/dev/uinput`,app 启动会立即报错。

### 开发(从源码)

```bash
git clone https://github.com/wurong98/doubao-input-for-linux.git
cd doubao-input

# 1. 系统依赖(同 .deb 依赖,这里要手动装)
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 \
                 libgtk-4-1 libadwaita-1-0 libwebkitgtk-6.0-4 wl-clipboard

# 2. 进 input 组
sudo usermod -aG input $USER
#   ⚠️ 重登

# 3. venv + Python 依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
#   requirements.txt 内容: websockets, sounddevice, evdev

# 4. 跑
./start.sh
#   等价于 PYTHONPATH=src .venv/bin/python -m doubao_input
```

### 首次使用

启动后弹出**登录窗口**,用 WebKitGTK 加载豆包网页;在 WebView 里登录成功后,
JS 拦截到登录态,自动从 `/alice/profile/self` 抓 cookies + 从 `localStorage` 抓 `device_id` / `web_id`,
写入 `~/.config/doubao-input/asr_params.json`,登录窗口自动关闭。

之后按下右 Ctrl 即可:

- **按下**:弹出悬浮胶囊(Myna 的 `myna-hud`,没装则用内置胶囊),实时显示识别文字
- **松开**:等待 1s 安全超时(收齐末尾识别结果),把文字 `wl-copy` 写剪贴板 + `uinput` 发 Ctrl+Shift+V → 落入当前输入框
- **按住 <150ms**:视为误触,取消,不注入

---

## 🎨 界面:用 Myna 那套

界面分两处,都换成了 Myna 的样子;**识别、注入、登录的逻辑一行没动**。

| 界面 | 现在是谁画 | 代码 |
|---|---|---|
| 设置 / 控制窗口 | libadwaita 三页设置窗口(Myna Settings 同款) | `ui/control_window.py` |
| 录音时的悬浮胶囊 | Myna 的 `myna-hud`(GTK4 + GPU 波形丝带) | `hud/` |

### 设置窗口

`Adw.ApplicationWindow` + `ToolbarView` + `HeaderBar`(内嵌 `Adw.ViewSwitcher`)
+ `Adw.ViewStack` 三页,页内是 Myna Settings 那套 `Adw.PreferencesGroup` /
`Adw.ActionRow` / `Adw.SwitchRow`,短暂提示走 `Adw.ToastOverlay`:

- **账号** —— 登录状态(带图标)、登录 / 重新登录、凭证文件路径
- **输入** —— 触发方式、最短按压、「使用 Ctrl+Shift+V」开关、「使用 Myna 悬浮胶囊」开关、使用说明
- **诊断** —— 麦克风自检(输出 RMS)、粘贴链路自检、悬浮窗实时状态、退出

系统里没有 libadwaita(`gi.require_version('Adw', '1')` 失败)时,自动退回原来
那个纯 GTK4 窗口,功能完全一致。

### 悬浮胶囊是怎么接上去的

和上面不同,胶囊是另一个进程画的:可以换成 **Myna** 的 `myna-hud`
(GTK4/libadwaita + GPU 波形丝带),豆包这边只负责把状态发出去:

```
豆包逻辑(Python) ──D-Bus 属性──> myna-hud(Rust/GTK4)
   状态 + 电平                      只消费属性,拥有全部像素
```

接口就是 Myna 的 `com.canonical.Myna.Dictation`(`State`/`StatusMessage`/
`AudioRms`/`AudioPeak`/`HudStyle`),契约见
`~/Desktop/myna/specs/004-gnome-shell-indicator/contracts/dbus-interface.md`。
**不经过 snap**:`myna-hud` 直接从源码编出来跑。

| 豆包这边发生什么 | 线上 State | 胶囊显示 |
|---|---|---|
| 按下右 Ctrl、WSS 还没连上 | `loading` | 正在连接… |
| 正在录音 | `recording` | 最新一段识别文本(默认;`HUD_SHOW_TRANSCRIPT=False` 则显示「聆听中…」) |
| 松开、等最后结果 | `finalizing` | 识别中… |
| 出错 / 需要登录 | `error` / `notice` | 错误文案,几秒后自动消失 |
| 空闲 | `idle` | 胶囊隐藏 |

电平按 20Hz 推送(麦克风 RMS 每 256ms 才来一次,中间做了插值平滑)。

---

### 一分钟接上(默认路径)

```bash
# 1) 编出渲染器(需要 cargo + libgtk-4-dev + libadwaita-1-dev)
bash scripts/build-myna-hud.sh          # → ~/.local/bin/myna-hud

# 2) 启动;「输入」页的「使用 Myna 悬浮胶囊」默认就是开的
#    (开关状态记在 ~/.config/doubao-input/settings.json)
./start.sh

# 3) 按住右 Ctrl 看胶囊;同时可以在外部读线上状态
gdbus call --session -d com.canonical.Myna.Dictation \
  -o /com/canonical/Myna/Dictation \
  -m org.freedesktop.DBus.Properties.GetAll com.canonical.Myna.Dictation
```

渲染器没装 / 崩了 / 起不来,都静默退回内置悬浮窗(`ui/overlay.py`),录音和注入照常工作。

---

### 让胶囊获得 Myna 原版的定位(GNOME / Wayland)

上面这条默认路径里,`myna-hud` 是**本项目自己拉起**的一个普通窗口,位置由混成器
决定(大致屏幕中间)。Myna 原版不是这样:它的 `myna-shell` GNOME 扩展用
`Meta.WaylandClient` 把渲染器窗口收编成 overlay,于是胶囊会

- 落在**当前正在打字的那个显示器**的底部居中(不是主显示器);
- 避开顶部 panel 和 dash-to-dock(包括自动隐藏的 dock);
- 永不吃焦点(click-through),打字不被打断;
- 崩溃后由扩展自动重启(带退避策略)。

要拿到这套定位,装扩展即可,**依旧不经 snap**:

```bash
# 1) 装扩展(脚本会先确保 ~/.local/bin/myna-hud 存在,不存在就自动编)
bash scripts/install-gnome-extension.sh

# 2) 注销并重新登录(关键,原因见下)

# 3) 启用
gnome-extensions enable myna-shell@canonical.com
```

`install-gnome-extension.sh` 做了三件事:

1. 把 `~/Desktop/myna/extensions/myna-shell` 拷到
   `~/.local/share/gnome-shell/extensions/myna-shell@canonical.com/`
   (纯 JS,不需要编译 gresource);
2. 写 `~/.config/environment.d/10-myna-hud.conf`:
   ```
   MYNA_HUD_BINARY=/home/<你>/.local/bin/myna-hud
   ```
   因为扩展的 `resolve.js` 只认两条路 —— `$MYNA_HUD_BINARY` 或
   `snap run myna.hud`。设了这个变量,snap 那条分支根本不会走到;
3. 打印后续的启用 / 验证命令。

> **为什么必须注销重登**:`~/.config/environment.d/*.conf` 只在**登录时**由
> systemd --user 导入 gnome-shell 的环境。不重登,gnome-shell 看不到
> `MYNA_HUD_BINARY`,扩展会回退去找 `snap run`,于是呆在那儿什么都不做。

启用后确认:

```bash
gnome-extensions info myna-shell@canonical.com | grep -i state   # State: ENABLED
pgrep -a myna-hud                                                # 应该有进程
gdbus call --session -d com.canonical.Myna.Dictation \
  -o /com/canonical/Myna/Dictation \
  -m org.freedesktop.DBus.Properties.Get com.canonical.Myna.Dictation State
```

**不会被拉起两个**:`hud/launcher.py` 的 `extension_enabled()` 读
`org.gnome.shell enabled-extensions`,发现扩展已启用就让位 —— 拉起和监管都交给
扩展,本项目只发布状态。

**手动装(不想用脚本)**

```bash
mkdir -p ~/.local/share/gnome-shell/extensions
cp -r ~/Desktop/myna/extensions/myna-shell \
      ~/.local/share/gnome-shell/extensions/myna-shell@canonical.com
rm -rf ~/.local/share/gnome-shell/extensions/myna-shell@canonical.com/test
mkdir -p ~/.config/environment.d
printf 'MYNA_HUD_BINARY=%s/.local/bin/myna-hud\n' "$HOME" \
  > ~/.config/environment.d/10-myna-hud.conf
# 注销重登 →
gnome-extensions enable myna-shell@canonical.com
```

**X11 会话 / 非 GNOME 桌面**

扩展用的是 `Meta.WaylandClient`(Wayland-only),X11 会话下扩展直接休眠不干活。
这时本项目会以 `myna-hud --host x11` 启动,让渲染器自己托管窗口(EWMH 定位 +
点击穿透),Xfce / Unity / X11 都适用 —— 会话类型由 `hud/launcher.py` 自动判断,
无需配置。想知道自己是哪一种:`echo $XDG_SESSION_TYPE`。

**排查**

| 现象 | 查什么 |
|---|---|
| 胶囊完全不出现 | `pgrep -a myna-hud`;设置窗口里的开关;日志中的 `Myna HUD ready` / `myna-hud not found` |
| 出现了,但位置在屏幕中间 | Wayland 下说明扩展没启用:`gnome-extensions info myna-shell@canonical.com` |
| 装了扩展还是没反应 | 有没有**注销重登**;`gnome-extensions info` 的 State 是否为 ENABLED |
| 胶囊闪烁 / 出现两个 | 扩展与自拉起打架:确认扩展启用状态,或把 `config.py` 的 `HUD_AUTO_LAUNCH` 设为 `False` |
| 扩展说版本不支持 | `gnome-shell --version` 要落在 `metadata.json` 的 `shell-version`(46~51)里 |
| 多显示器时位置不对 | 这是设计行为:胶囊跟随**有焦点窗口**的显示器,不是主显示器 |

**关掉 / 回退**

```bash
gnome-extensions disable myna-shell@canonical.com     # 或删掉扩展目录后重登
```

扩展一关,`extension_enabled()` 就检测不到,本项目自动接管、自己拉起渲染器。
想彻底用回内置胶囊,在设置窗口「输入」页关掉「使用 Myna 悬浮胶囊」即可。

---

### 相关配置

`src/doubao_input/doubao/config.py`:

| 常量 | 默认 | 含义 |
|---|---|---|
| `HUD_ENABLED` | `True` | 悬浮窗是否优先用 Myna 胶囊(开关状态存在 `~/.config/doubao-input/settings.json`) |
| `HUD_AUTO_LAUNCH` | `True` | 是否自动拉起 `myna-hud`(扩展启用时自动让位) |
| `HUD_STYLE` | `"ribbon"` | 波形样式:`bar` / `ribbon` / `vumeter` / `progress` |
| `HUD_SHOW_TRANSCRIPT` | `True` | 胶囊里显示最新一段识别文本(关掉则显示「聆听中…」) |
| `HUD_STATUS_MAX_CHARS` | `30` | 胶囊文案上限(与 myna-hud 的 `LABEL_MAX_CHARS` 对齐) |
| `HUD_LEVEL_HZ` | `20` | 电平推送频率(契约要求 15~20Hz) |
| `HUD_NOTICE_HOLD_MS` / `HUD_ERROR_HOLD_MS` | `6000` / `10000` | 提示 / 错误的停留时长 |
| `INJECT_USE_SHIFT` | `True` | 粘贴用 Ctrl+Shift+V(设置窗口里可实时改) |

### 代码在哪

```
src/doubao_input/hud/
├── bridge.py      AppState 信号 → 线上 State/StatusMessage + 20Hz 电平泵
├── publisher.py   用 PyGObject/Gio 发布 com.canonical.Myna.Dictation(零新增 pip 依赖)
├── launcher.py    拉起 / 看护 myna-hud;扩展启用时让位
├── wire.py        线协议常量 + D-Bus 自省 XML
└── settings.py    偏好持久化(~/.config/doubao-input/settings.json)
```

## 🧑‍💻 开发

### 项目结构

```
src/doubao_input/
├── __main__.py            入口 (`python -m doubao_input`)
├── app.py                 GtkApplication 生命周期 + 组件编排
│
├── doubao/                豆包逆向逻辑核心模块
│   ├── asr_client.py       WSS 客户端
│   ├── audio_capture.py     sounddevice 16kHz/mono/int16 采集 + RMS 回调
│   ├── params_store.py      凭证持久化 (JSON)
│   ├── config.py            固定参数、路径、超时
│   ├── app_state.py         GObject 可观察状态
│   ├── login_window.py      WebKitGTK 登录 + JS 拦截凭证
│   └── host_tools.py        wl-copy / xclip 候选命令
│
├── trigger/evdev_ptt.py   ← 自研:右 Ctrl 物理键监听
├── inject/injector.py     ← 自研:wl-copy + uinput Ctrl+V
├── login/resources/        注入到 WebView 的 JS
├── hud/                   ← 自研:Myna 悬浮胶囊前端
│   ├── bridge.py           豆包状态机 → Myna 线状态
│   ├── publisher.py        发布 com.canonical.Myna.Dictation(D-Bus)
│   ├── launcher.py         拉起/看护 myna-hud 进程(不经 snap)
│   ├── wire.py             线协议常量
│   └── settings.py         偏好持久化 (~/.config/doubao-input/settings.json)
└── ui/                    ← 自研:界面
    ├── overlay.py          顶部波形胶囊悬浮窗(Myna 胶囊不可用时的回退)
    └── control_window.py   libadwaita 三页设置窗口(账号 / 输入 / 诊断)
```

### 模块分工

`trigger/`、`inject/`、`ui/`、`doubao/`、`app.py`、`__main__.py` 是本项目原创模块,各司其职。

### 探针测试

`tests/probe/` 是验证豆包登录与 ASR 链路是否仍可用的最小探针(非产品代码):

```bash
# P5: 登录豆包,写凭证
.venv/bin/python tests/probe/P5_login.py

# P6: 用凭证连 WSS,录 5 秒,看是否返回 result.Text
.venv/bin/python tests/probe/P6_asr.py
```

每个高风险环节(依赖、evdev、uinput、音频、剪贴板、登录、ASR)在
[`docs/design.md`](docs/design.md) §9 都有验证方法。开发期应先跑通 P5/P6 再动产品代码。

### 日志

启动时 `INFO` 级别,关键事件都有日志:

```
on_activate: setup_done=False
build complete
EvdevPtt started on N device(s)
WS open, 开始录…
result: 今天天气怎么样
clipboard: wl-copy ok
paste: uinput ok (shift=False, gap=12ms)
```

调试:把 `logging.basicConfig(level=logging.DEBUG)` 改成 DEBUG 即可看到 evdev 设备扫描等细节。

---

## 📤 打包

提供 `.deb` 包 + systemd user service 常驻,版本号见
[`debian/changelog`](debian/changelog)。

```bash
# 打包(在仓库根)
bash packaging/build-deb.sh
# → 生成 doubao-input_<version>_all.deb

# 安装
sudo dpkg -i doubao-input_*.deb
# postinst 会自动:
#   - 把当前用户加入 input 组(需要重新登录)
#   - 创建用户级 venv: ~/.local/share/doubao-input/.venv
#   - 装 Python 依赖: websockets / sounddevice / evdev
#   - 拷贝头像到 hicolor 图标主题
#   - 拷贝 .desktop / .service

# 启动
doubao-input                          # 直接跑
systemctl --user enable --now doubao-input.service  # 开机自启
```

打包细节见 [`docs/design.md`](docs/design.md) §7。

---

## ⚠️ 已知限制

- **粘贴快捷键二选一**:默认 Ctrl+Shift+V(终端也能用),但少数 GUI 应用只认 Ctrl+V;
  设置窗口「输入」页可随时切换,选择记在 `~/.config/doubao-input/settings.json`。
- **胶囊定位(默认路径)**:不装 GNOME 扩展时,`myna-hud` 是一个普通窗口,位置由混成器决定
  (大致屏幕中间),没有 Myna 原版的"底部居中 + 避 dock"。要原版定位就装扩展,
  见上文「让胶囊获得 Myna 原版的定位」。
- **托盘在 GNOME 48 默认不可见**:GNOME 48 默认不显示 StatusNotifierItem 托盘,
  需 AppIndicator 扩展;否则静默降级,功能不受影响,引导用控制窗口。
- **豆包接口变动风险**:豆包 Web 版接口一旦变更,ASR 会失效;凭证失效会触发自动重登。
- **剪贴板被覆盖**:每次粘贴覆盖系统剪贴板。

---

## 📝 变更历史

完整历史见 [`debian/changelog`](debian/changelog)。近期主要变更:

### v1.1.0(未发布,2026-10-21)

- **设置窗口换成 libadwaita 三页** —— 与 Myna Settings 同款
  (Adw.ApplicationWindow + ToolbarView + HeaderBar/ViewSwitcher + PreferencesPage),
  分账号 / 输入 / 诊断三页,新增「使用 Ctrl+Shift+V」「使用 Myna 悬浮胶囊」两个开关,
  短暂结果用 Adw.Toast 提示;缺 libadwaita 时退回原 GTK4 窗口。
- **悬浮胶囊可换成 Myna 的 `myna-hud`** —— 新增 `hud/`:发布
  `com.canonical.Myna.Dictation` 驱动 Myna 的渲染器(不经 snap,
  `scripts/build-myna-hud.sh` 编译安装),GNOME 上还可装
  `scripts/install-gnome-extension.sh` 拿到原版定位。
- **应用图标换成 Myna 的** —— 直接用 Myna 的
  `com.canonical.Myna.svg`(scalable SVG,不再有 PNG),由 `.deb` 装到
  `/usr/share/icons/hicolor/scalable/apps/doubao-input.svg`。
- **修复** —— `myna-hud` 被信号杀死时的 GLib 断言告警;`EvdevPtt.start()`
  抛异常(缺 evdev)会中断整个启动、控制窗口弹不出来。
- 偏好持久化统一到 `~/.config/doubao-input/settings.json`(旧的 `hud.json` 仍可读)。

### v1.0.2(2026-06-21)

- **Logo 透明背景** — 把白底的 logo.png / logo-128.png 替换为
  RGBA 真透明版本(角点 alpha=0)。launcher 图标不再有
  白色方框,README 头像不再有白色描边。版本号 bump 因为
  这是用户视觉层的修复,虽然不是功能改动。

### v1.0.1(2026-06-21)

- **PttOverlay 视觉升级** — 18px 圆角 + 半透明深色面板 + 1.5px 白边 +
  呼吸 alpha(2.4s 周期,0.78~0.98)+ 敲击触发 220ms 流光闪烁。
  文字高对比度、纯白粗体,动效不作用于文字。
- **5 个排版 bug 修复** —
  - 锁 label 硬宽 360px,修「你好依旧两行」(Pango 0 字符宽时单字一行 bug)
  - 改 box 为 VERTICAL,修「文字偏右」(之前 HORIZONTAL,label 跟在 wave 右边)
  - 删 set_ellipsize(START),修「整行变 …」(wrap+ellipsize+CJK Pango bug)
  - 退回单 widget 树,修「文字看不到」(Gtk.Overlay.add_overlay 位置 bug)
  - box 撑满 window + CSS `window { background: none }`,修「白方块背景」
- **launcher 图标修复** — `.desktop` 的 `Icon=` 改用绝对路径,绕过
  GNOME Shell 的 per-session icon-theme cache,launcher 立即生效
  无需重登。

### v1.0.0(2026-06-21)

- 初版发布。push-to-hold 全局语音输入法(.deb + systemd user service)。

---

## 🙏 致谢

### [Myna](https://github.com/canonical/myna) — 界面来自这里

Canonial 的离线语音转文字项目(**AGPL-3.0-or-later**)。这个项目把它的整套桌面
界面搬了过来,而 Myna 自己完全不知道这件事:

| 用到了什么 | 出处 |
|---|---|
| **应用图标** | `client/data/icons/hicolor/scalable/apps/com.canonical.Myna.svg`(原样使用,见 `resources/logo.svg`) |
| **悬浮胶囊渲染器** | `myna-hud`(`client/myna-hud`,Rust + GTK4 + GLSL 波形),经 `com.canonical.Myna.Dictation` 驱动 |
| **胶囊定位** | `myna-shell` GNOME Shell 扩展(`extensions/myna-shell`),`Meta.WaylandClient` 收编窗口 |
| **设置窗口风格** | `myna-config`(`client/myna-config`)的 libadwaita / Adw.PreferencesPage 视觉规范 |
| **协议契约** | `specs/004-gnome-shell-indicator/contracts/dbus-interface.md`,本项目的 `hud/` 严格照它实现 |

没有链接、没有编译 Myna 的代码:`myna-hud` 与 GNOME 扩展都是**独立进程**,由
`scripts/build-myna-hud.sh` / `scripts/install-gnome-extension.sh` 从 Myna 源码树
本地构建安装,本项目只发 D-Bus 属性。设置窗口是照着风格重写的实现,不是拷贝。

### [doubao-murmur](https://github.com/yourname/doubao-murmur) — 豆包逆向逻辑

MIT。`src/doubao_input/doubao/`(登录、WebSocket ASR、音频采集、凭证、状态机)
来自它的 Linux 移植版,改动见 [`NOTICE`](NOTICE)。

### [wurong98/doubao-input-for-linux](https://github.com/wurong98/doubao-input-for-linux) — 上游

MIT。**本仓库就是它的 fork**:push-to-hold 交互、右 Ctrl 触发(evdev)、
剪贴板 + uinput 注入、WebKit 登录窗口、`.deb` 打包与 systemd user service
都来自上游。上面这些 Myna 相关的改造是本 fork 加的。

### 豆包(Doubao)

字节跳动的 AI 产品,提供本项目使用的 Web 版流式 ASR。本项目是**非官方**的逆向
实现,与字节跳动没有任何关联;接口随时可能变动。

### 还要谢谢

`evdev` / `uinput`(Wayland 下不依赖 X11 的关键)、`wl-clipboard`、
GTK4 与 libadwaita、PortAudio、`websockets`,以及 GNOME / Mutter 对
Wayland 原生输入栈的坚持。

---

## 📄 许可证

MIT — 见 [`LICENSE`](LICENSE)。

上游与第三方归属(含 Myna 的图标与 AGPL 说明)见 [`NOTICE`](NOTICE)。