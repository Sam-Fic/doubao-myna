"""听写提示音 —— 对齐 Myna 的 `sounds` 开关。

Myna 自带 7 套音色(AGPL 资源),这里**不搬运**那些音频文件,而是播系统
freedesktop 事件音(`canberra-gtk-play`),所以:

  * 缺 libcanberra 就静默不响,不报错;
  * 音色跟系统走(换声音主题会跟着变);
  * Myna 的时机:按下即播 Start(不等模型 Ready),会话结束时播 Stop,
    严重错误必播 Error —— 这里同样。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

TOOL = "canberra-gtk-play"

#: 时机 → freedesktop 事件音 id
EVENTS = {
    "start": "message-new-instant",
    "stop": "message",
    "error": "dialog-error",
}


class Sounds:
    """Play start/stop/error cues through the system sound theme."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = bool(enabled)
        self._tool: Optional[str] = shutil.which(TOOL)

    @property
    def available(self) -> bool:
        return self._tool is not None

    def play(self, kind: str) -> None:
        if not self.enabled or self._tool is None:
            return
        event = EVENTS.get(kind)
        if not event:
            return
        try:
            subprocess.Popen(
                [self._tool, "-i", event],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:  # pragma: no cover
            logger.debug("sound %s failed: %s", kind, e)
