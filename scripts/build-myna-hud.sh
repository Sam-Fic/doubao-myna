#!/usr/bin/env bash
# 编译 Myna 的悬浮胶囊渲染器并安装到 ~/.local/bin(不经 snap)。
#
#   bash scripts/build-myna-hud.sh            # release 构建
#   MYNA_HUD_DEST=/usr/local/bin bash ...     # 换安装位置
#   MYNA_HUD_PROFILE=debug bash ...           # debug 构建
#
# 依赖:cargo + rustc(rustup)、libgtk-4-dev、libadwaita-1-dev。
#
# ## 源码从哪来
#
# 用**本仓库内嵌的** `vendor/myna-hud/`(以及它依赖的 `vendor/myna-platform/`),
# 不再需要 ~/Desktop/myna 或任何外部 checkout。vendored 的代码来自
# Myna(AGPL-3.0-or-later,见 NOTICE),并带有本项目的“胶囊单行 + 横向滚动”
# 改动 —— 直接改在 vendored 源码里,不需要额外的 patch 步骤。
#
# 想构建**未改动**的上游渲染器:
#
#   MYNA_SOURCE_DIR=/path/to/myna bash scripts/build-myna-hud.sh
#
# 这时会用外部源码(不碰它的工作区:在 git worktree / 临时拷贝里构建),
# 胶囊会退回上游行为 —— 文字变长时换行、把胶囊撑高。
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${MYNA_SOURCE_DIR:-$REPO/vendor}"
DEST="${MYNA_HUD_DEST:-$HOME/.local/bin}"
PROFILE="${MYNA_HUD_PROFILE:-release}"

if ! command -v cargo >/dev/null 2>&1; then
    echo "cargo not found; install rustup first: https://rustup.rs" >&2
    exit 1
fi

if [ ! -f "$SRC/Cargo.toml" ] || [ ! -d "$SRC/myna-hud" ]; then
    echo "myna-hud sources not found under $SRC" >&2
    echo "  vendored copy missing? expected $REPO/vendor/myna-hud" >&2
    exit 1
fi

# ---- 决定用哪棵树构建 ----

WORK=""
cleanup() {
    if [ -n "$WORK" ] && [ -d "$WORK" ]; then
        if [ -e "$WORK/tree/.git" ]; then
            git -C "$WORK_REPO" worktree remove --force "$WORK/tree" 2>/dev/null || true
            git -C "$WORK_REPO" worktree prune 2>/dev/null || true
        fi
        rm -rf "$WORK" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

BUILD_SRC="$SRC"
PATCHED_OK=1

if [ -n "${MYNA_SOURCE_DIR:-}" ]; then
    # 外部源码:上游布局是 <repo>/client/myna-hud,而且没有我们的改动。
    if [ -d "$SRC/client/myna-hud" ]; then
        echo "==> MYNA_SOURCE_DIR set: building UPSTREAM myna-hud (unpatched)"
        echo "    the capsule will wrap instead of scrolling"
        PATCHED_OK=0
        WORK="$(mktemp -d "${TMPDIR:-/tmp}/myna-hud-build.XXXXXX")"
        WORK_REPO="$SRC"
        mkdir -p "$WORK/tree"
        if git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
            if git -C "$SRC" worktree add --detach "$WORK/tree" HEAD >/dev/null 2>&1; then
                BUILD_SRC="$WORK/tree/client"
            else
                git -C "$SRC" archive --format=tar HEAD | tar -x -C "$WORK/tree"
                BUILD_SRC="$WORK/tree/client"
            fi
        else
            rm -rf "$WORK/tree"
            cp -a "$SRC/client" "$WORK/tree"
            BUILD_SRC="$WORK/tree"
        fi
    else
        echo "==> MYNA_SOURCE_DIR set: using $SRC as-is"
    fi
fi

# ---- 构建 ----

echo "==> building myna-hud from $BUILD_SRC ($PROFILE)"
if [ "$PROFILE" = "release" ]; then
    ( cd "$BUILD_SRC" && cargo build --release -p myna-hud )
    BINARY="$BUILD_SRC/target/release/myna-hud"
else
    ( cd "$BUILD_SRC" && cargo build -p myna-hud )
    BINARY="$BUILD_SRC/target/debug/myna-hud"
fi

if [ ! -x "$BINARY" ]; then
    echo "expected binary missing: $BINARY" >&2
    exit 1
fi

mkdir -p "$DEST"
install -m 0755 "$BINARY" "$DEST/myna-hud"
echo "==> installed $DEST/myna-hud"
"$DEST/myna-hud" --version

if [ "$PATCHED_OK" = "1" ]; then
    echo
    echo "胶囊:文字变长时先变宽,到上限(420px)就停止变宽、旧字往左滚走,"
    echo "      最新字始终停在右端;高度全程不变。"
fi
