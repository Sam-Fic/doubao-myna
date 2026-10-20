"""Entry point: `python -m doubao_input`."""
from __future__ import annotations

import logging
import signal
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib  # noqa: E402

from doubao_input.app import DoubaoInputApp

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
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
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, number, _terminate, number)

    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
