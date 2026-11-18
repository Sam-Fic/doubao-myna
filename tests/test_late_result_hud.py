"""回归:会话结束后迟到的 ASR result 不得把胶囊重新点亮。

复现的竞态:松键 → STOPPING → finish/安全超时先完成 → IDLE(胶囊已隐藏),
随后服务端迟到的 result 经 idle_add 派发,旧代码会无条件 on_overlay_update
→ set_state(RECORDING),胶囊永久停在屏幕底部。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from doubao_input.doubao.app_state import AppState, LoginStatus, RecordingState
from doubao_input.doubao.transcription import TranscriptionManager


def main() -> None:
    st = AppState()
    st.login_status = LoginStatus.LOGGED_IN
    tm = TranscriptionManager(st)
    updates: list[str] = []
    tm.on_overlay_update = updates.append

    # 1) 竞态场景:会话已结束(IDLE),迟到的 result 必须被丢弃
    st.recording_state = RecordingState.IDLE
    st.transcription_text = ""
    tm._on_asr_result("迟到的识别结果")
    assert updates == [], f"IDLE 时仍触发了 overlay 更新: {updates}"
    assert st.transcription_text == "", "IDLE 时仍写入了文本"
    print("OK: IDLE 时迟到 result 被丢弃,胶囊不会被重新点亮")

    # 2) 正常场景:RECORDING 中的 result 照常更新
    st.recording_state = RecordingState.RECORDING
    tm._on_asr_result("正常识别文本")
    assert updates == ["正常识别文本"], updates
    assert st.transcription_text == "正常识别文本"
    print("OK: RECORDING 中 result 正常更新")

    # 3) STOPPING + awaiting_final_result:仍走完成流程(粘贴/置 idle)
    st.recording_state = RecordingState.STOPPING
    tm.awaiting_final_result = True
    pasted: list[str] = []
    tm.on_paste = pasted.append
    tm.on_overlay_hide = lambda: None
    tm._on_asr_result("最终文本")
    assert pasted == ["最终文本"], pasted
    assert st.recording_state == RecordingState.IDLE
    print("OK: STOPPING 期间最终 result 仍正常完成并隐藏")

    # 4) bridge._on_text 守卫:IDLE/STOPPING 不点亮,RECORDING 照常
    from doubao_input.hud.bridge import MynaHudBridge

    class FakePub:
        def __init__(self) -> None:
            self.states: list[tuple[str, str]] = []

        def set_state(self, s: str, m: str) -> None:
            self.states.append((s, m))

    b = MynaHudBridge.__new__(MynaHudBridge)
    b._app_state = st
    b._publisher = FakePub()
    b.enabled = True
    b._hold_timer = 0
    st.recording_state = RecordingState.IDLE
    b._on_text(st, "x")
    st.recording_state = RecordingState.STOPPING
    b._on_text(st, "x")
    assert b._publisher.states == [], b._publisher.states
    st.recording_state = RecordingState.RECORDING
    st.transcription_text = "你好"
    b._on_text(st, "你好")
    assert b._publisher.states and b._publisher.states[-1][0] == "recording"
    print("OK: bridge 只在 STARTING/RECORDING 时点亮胶囊")
    print("ALL PASS")


if __name__ == "__main__":
    main()