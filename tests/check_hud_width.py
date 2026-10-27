"""状态文案的宽度截断自检(不需要 pytest / GTK 之外的依赖)。

背景:胶囊标签由 ``myna-hud`` 画,它的源码 vendored 在 ``vendor/myna-hud``
下,并且已改成**单行 + 宽度封顶 + 横向滚动**。所以 ``StatusMessage`` 只要
不超过它的标签宽度上限(LABEL_MAX_WIDTH = 420px),文字就不会换行、
胶囊高度恒定。

这个脚本锁住两件事:

  1. ``fit_tail`` 的输出永远不超过预算(按 :func:`display_width` 算);
  2. 若本机有 GTK/Pango,再把预算换算成像素,验证它确实不超过胶囊的
     一行宽度上限。

跑法::

    PYTHONPATH=src python3 tests/check_hud_width.py
"""

from __future__ import annotations

import sys

from doubao_input.doubao.config import HUD_STATUS_MAX_CHARS as CAP
from doubao_input.hud.wire import display_width, fit_tail

#: 与 vendor/myna-hud/src/pill.rs 的 LABEL_MAX_WIDTH 一致。
PILL_LABEL_MAX_WIDTH_PX = 420

#: 覆盖各种字符类别的样例:小写/大写/宽字母/数字/中文/全角标点/URL/混排。
SAMPLES = [
    "今天下午三点我们和设计团队一起开个会讨论新版本的界面交互细节以及下个季度需要交付的功能范围",
    "we met the design team at three to walk through the new interface",
    "WE MET THE DESIGN TEAM AT THREE TO WALK THROUGH THE NEW INTERFACE",
    "WWWWmmmmMMMMWWWWmmmmMMMMWWWW",
    "1234567890123456789012345678901234567890",
    "今天 meeting 讨论 API 的 design 细节以及 release plan",
    "http://example.com/path/to/some/resource?query=value",
    "你好，世界。这是一句话！还有吗？",
    "好",
    "",
]


def _real_pixel_budget() -> float | None:
    """用 Pango 算出胶囊的实际预算(px);没有 GTK/Pango 时返回 None。"""
    try:
        import gi

        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo
    except Exception as exc:  # 无 GTK 环境(CI 的最小镜像)就跳过像素校验
        print(f"  (skip pixel check: {exc})")
        return None

    ctx = PangoCairo.FontMap.get_default().create_context()
    # 与 myna-hud 的 CSS 一致:.myna-hud-label { font-size: 11pt }
    font = Pango.FontDescription.from_string("Sans 11")
    ctx.set_font_description(font)
    unit = ctx.get_metrics(font).get_approximate_char_width() / Pango.SCALE
    # 胶囊一行能显示的宽度:LABEL_MAX_WIDTH(见 patches/ 里的补丁)。
    # PILL 的 padding 等固定开销另算,这里只校验文本本身。
    return PILL_LABEL_MAX_WIDTH_PX


def _pixel_width(text: str, budget: float) -> float:
    import gi

    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo

    ctx = PangoCairo.FontMap.get_default().create_context()
    ctx.set_font_description(Pango.FontDescription.from_string("Sans 11"))
    layout = Pango.Layout(ctx)
    layout.set_text(text, -1)
    return layout.get_pixel_extents()[1].width


def main() -> int:
    failures: list[str] = []

    print(f"预算: {CAP} 个等宽单位")
    for sample in SAMPLES:
        out = fit_tail(sample, CAP)
        width = display_width(out)
        if width > CAP:
            failures.append(f"display_width {width} > {CAP}: {out!r}")
        print(f"  {len(sample):3d} 字输入 -> {out!r}  ({width} 单位)")

    # 流式场景:每一个前缀都必须放得下(识别文字是一个字一个字来的)。
    total = 0
    for sample in SAMPLES:
        for end in range(1, len(sample) + 1):
            out = fit_tail(sample[:end], CAP)
            total += 1
            if display_width(out) > CAP:
                failures.append(f"流式前缀越界: {out!r}")
                break
    print(f"  {total} 个流式前缀: 全部 <= 预算")

    budget_px = _real_pixel_budget()
    if budget_px is not None:
        print(f"真实字体预算: {budget_px:.0f}px")
        worst = 0.0
        for sample in SAMPLES:
            for end in range(1, len(sample) + 1):
                one = fit_tail(sample[:end], CAP)
                width = _pixel_width(one, budget_px)
                worst = max(worst, width)
                if width > budget_px:
                    failures.append(
                        f"真实宽度 {width:.0f}px > {budget_px:.0f}px: {one!r}"
                    )
                    break
        print(f"  实测最宽 {worst:.0f}px")

    if failures:
        print(f"\nFAIL ({len(failures)}):")
        for item in failures[:10]:
            print(f"  - {item}")
        return 1
    print("\nOK — 截断后始终能放进胶囊的一行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
