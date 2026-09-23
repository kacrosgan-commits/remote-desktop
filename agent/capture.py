"""Screen capture for the agent (controlled machine)."""
import mss
import numpy as np
import cv2


class ScreenCapturer:
    def __init__(self, monitor_index: int = 0):
        # mss monitors: index 0 = all displays as one desktop, 1 = primary, 2 = second, ...
        self._sct = mss.mss()
        self.monitor_index = 0
        self.monitor = self._sct.monitors[0]
        self.set_monitor(monitor_index)

    @property
    def width(self) -> int:
        return self.monitor["width"]

    @property
    def height(self) -> int:
        return self.monitor["height"]

    @property
    def left(self) -> int:
        return self.monitor["left"]

    @property
    def top(self) -> int:
        return self.monitor["top"]

    def set_monitor(self, monitor_index: int):
        """Switch which display is captured. 0 = every display in one image."""
        monitors = self._sct.monitors
        if not monitors:
            return
        if monitor_index < 0 or monitor_index >= len(monitors):
            monitor_index = 0
        self.monitor_index = monitor_index
        self.monitor = monitors[monitor_index]

    def grab_jpeg(self, quality: int = 60, scale: float = 1.0) -> bytes:
        raw = self._sct.grab(self.monitor)          # BGRA
        frame = np.asarray(raw)[:, :, :3]           # drop alpha -> BGR
        if scale != 1.0:
            frame = cv2.resize(
                frame, (int(frame.shape[1] * scale), int(frame.shape[0] * scale)),
                interpolation=cv2.INTER_AREA,
            )
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise RuntimeError("JPEG encode failed")
        return buf.tobytes()

    def close(self):
        self._sct.close()
