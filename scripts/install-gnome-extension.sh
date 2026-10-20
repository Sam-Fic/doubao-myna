#!/usr/bin/env bash
# 可选:在 GNOME/Wayland 上装 Myna 的 myna-shell 扩展。
#
# 不装也能用 —— 本项目自己会拉起 myna-hud,只是胶囊由混成器随手摆位。
# 装了扩展之后:胶囊会被定位到"当前工作显示器"的底部居中、避开 panel 和
# dash-to-dock、不吃焦点、崩溃自动重启,和 Myna 原版一致。
#
# 依旧不需要 snap:扩展通过 $MYNA_HUD_BINARY 找本地编译的二进制
# (见 resolve.js 的 override 分支),snap 那条路压根不会走。
#
#   bash scripts/install-gnome-extension.sh
#   然后注销重登(让 environment.d 生效),再:
#   gnome-extensions enable myna-shell@canonical.com
set -euo pipefail

SRC="${MYNA_SOURCE_DIR:-$HOME/Desktop/myna}"
UUID="myna-shell@canonical.com"
EXT_SRC="$SRC/extensions/myna-shell"
EXT_DEST="$HOME/.local/share/gnome-shell/extensions/$UUID"
HUD="$HOME/.local/bin/myna-hud"
ENV_DIR="$HOME/.config/environment.d"

if [ ! -d "$EXT_SRC" ]; then
    echo "extension source not found: $EXT_SRC (set \$MYNA_SOURCE_DIR)" >&2
    exit 1
fi

if [ ! -x "$HUD" ]; then
    echo "==> $HUD missing, building it first"
    MYNA_SOURCE_DIR="$SRC" bash "$(dirname "$0")/build-myna-hud.sh"
fi

echo "==> installing extension to $EXT_DEST"
mkdir -p "$EXT_DEST"
for f in "$EXT_SRC"/*.js "$EXT_SRC"/metadata.json "$EXT_SRC"/README.md; do
    [ -e "$f" ] && install -m 0644 "$f" "$EXT_DEST/"
done

echo "==> 让扩展直接找本地二进制(不打这个补丁就得注销重登)"
python3 - "$EXT_DEST/resolve.js" <<'PY'
"""在装好的 resolve.js 里加一条"本地二进制"分支。

Myna 原版的 resolve.js 只认 $MYNA_HUD_BINARY 或 `snap run myna.hud`;
我们不加 snap,于是在 snap 分支之前插入本地路径优先:
  $MYNA_HUD → $HOME/.local/bin/myna-hud
打补丁后 **不需要注销重登**(环境变量只在登录时导入 gnome-shell)。
"""
import sys
from pathlib import Path

marker = "doubao-input-for-linux: local binary"
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if marker in text:
    print("    already patched")
    sys.exit(0)

anchor = "    if (isExecutable(SNAP_LAUNCHER) || isExecutable(`/usr/bin/${SNAP_LAUNCHER}`)) {"
patch = (
    "    // __MARKER__ — 本地编译的渲染器优先于 snap。\n"
    "    const localCandidates = [\n"
    "        getenv('MYNA_HUD'),\n"
    "        (getenv('HOME') || '') + '/.local/bin/myna-hud',\n"
    "    ].filter((p) => typeof p === 'string' && p !== '');\n"
    "    for (const candidate of localCandidates) {\n"
    "        if (isExecutable(candidate)) {\n"
    "            return {argv: [candidate], source: 'local'};\n"
    "        }\n"
    "    }\n"
    "\n"
).replace("__MARKER__", marker) + anchor

if anchor not in text:
    print("    !! anchor not found, resolve.js 结构可能变了,请手动确认", file=sys.stderr)
    sys.exit(1)
path.write_text(text.replace(anchor, patch, 1), encoding="utf-8")
print("    patched:", path)
PY

echo "==> pointing the extension at the local renderer"
mkdir -p "$ENV_DIR"
cat > "$ENV_DIR/10-myna-hud.conf" <<EOF
# 让 myna-shell 扩展用本地编译的渲染器,而不是 \`snap run myna.hud\`。
MYNA_HUD_BINARY=$HUD
EOF

cat <<EOF

==> done. Next:
    1. 启用扩展(装过的话只需这一步;没装过先重登):
       gnome-extensions enable $UUID
    2. 确认:gdbus call --session -d com.canonical.Myna.Dictation \\
         -o /com/canonical/Myna/Dictation \\
         -m org.freedesktop.DBus.Properties.GetAll com.canonical.Myna.Dictation

扩展启用后会自己拉起 ~/.local/bin/myna-hud 并把窗口摆到"当前显示器底部居中、
避开 dock、不吃焦点";本项目的 HUD_AUTO_LAUNCH 检测到扩展启用就让位,
不会起两个 myna-hud(见 hud/launcher.py 的 extension_enabled())。
EOF
