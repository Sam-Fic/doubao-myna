#!/usr/bin/env bash
# 编译 Myna 的悬浮胶囊渲染器并安装到 ~/.local/bin(不经 snap)。
#
#   bash scripts/build-myna-hud.sh            # release 构建
#   MYNA_SOURCE_DIR=/path/to/myna bash scripts/build-myna-hud.sh
#
# 依赖:cargo + rustc(rustup)、libgtk-4-dev、libadwaita-1-dev。
# 产物只用到一个二进制:myna-hud。它自己就是 GTK4 单实例应用,启动后
# 只消费 com.canonical.Myna.Dictation 上的属性,不需要 snapd、不需要
# GNOME 扩展也能跑(X11 下会自动用 --host x11)。
set -euo pipefail

SRC="${MYNA_SOURCE_DIR:-$HOME/Desktop/myna}"
DEST="${MYNA_HUD_DEST:-$HOME/.local/bin}"
PROFILE="${MYNA_HUD_PROFILE:-release}"

if ! command -v cargo >/dev/null 2>&1; then
    echo "cargo not found; install rustup first: https://rustup.rs" >&2
    exit 1
fi

if [ ! -d "$SRC/client" ]; then
    echo "Myna source not found at $SRC/client; set \$MYNA_SOURCE_DIR" >&2
    exit 1
fi

echo "==> building myna-hud from $SRC/client ($PROFILE)"
( cd "$SRC/client" && cargo build "--$PROFILE" -p myna-hud )

BINARY="$SRC/client/target/$PROFILE/myna-hud"
if [ ! -x "$BINARY" ]; then
    echo "expected binary missing: $BINARY" >&2
    exit 1
fi

mkdir -p "$DEST"
install -m 0755 "$BINARY" "$DEST/myna-hud"
echo "==> installed $DEST/myna-hud"
"$DEST/myna-hud" --version
