"""Capture region selection for multi-monitor desktops."""
from agent.capture import ScreenCapturer


class _FakeSct:
    def __init__(self):
        self.monitors = [
            {"left": 0, "top": 0, "width": 3000, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": 1920, "top": 0, "width": 1080, "height": 1080},
        ]

    def close(self):
        pass


def test_default_and_second_display(monkeypatch):
    monkeypatch.setattr("agent.capture.mss.mss", lambda: _FakeSct())
    cap = ScreenCapturer(0)
    assert cap.monitor_index == 0
    assert cap.width == 3000
    cap.set_monitor(2)
    assert cap.monitor_index == 2
    assert cap.left == 1920
    assert cap.width == 1080
    cap.set_monitor(9)  # missing display falls back to all
    assert cap.monitor_index == 0
    cap.close()
