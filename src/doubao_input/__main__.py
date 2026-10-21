"""Entry point: `python -m doubao_input`."""
from __future__ import annotations

import logging
import signal
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, GLibUnix  # noqa: E402

from doubao_input.app import DoubaoInputApp
from doubao_input.hud.settings import load_language
from doubao_input.i18n import init as init_i18n

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # 先初始化多语言(用户在设置里选过的语言优先,否则跟随系统),再建任何界面 ——
    # 界面字符串是建的时候定死的。
    init_i18n(load_language() or None)
    app = DoubaoInputApp()

    def _terminate(*_args) -> bool:
        # Gtk.Application 收到 SIGTERM 不会走 "shutdown" 信号,子进程
        # (myna-hud)会被漏下来变成孤儿。这里显式清理后再退出。
        logger.info("received terminate signal; cleaning up")
        try:
            app._on_shutdown(None)
        finally:
            app.quit()
        return GLib.SOURCE_REMOVE

    for number in (signal.SIGTERM, signal.SIGINT):
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, number, _terminate, number)

    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
