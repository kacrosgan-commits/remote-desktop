"""Per-device session widget for the controller.

RemoteView   — paints the remote frame (letterboxed) and captures input.
RemoteSession— one tab: control strip + RemoteView + its own Net client,
               targeting a single device_id.
"""
import sys
import os
import base64
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QEvent, Signal
from PySide6.QtGui import QImage, QPainter, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QCheckBox, QPushButton,
    QComboBox, QFileDialog,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import protocol as P  # noqa: E402
from controller.net import Net, Signals  # noqa: E402

_QT_KEYMAP = {
    Qt.Key_Return: "enter", Qt.Key_Enter: "enter", Qt.Key_Escape: "esc",
    Qt.Key_Tab: "tab", Qt.Key_Backtab: "tab", Qt.Key_Backspace: "backspace", Qt.Key_Space: "space",
    Qt.Key_Delete: "delete", Qt.Key_Insert: "insert", Qt.Key_Home: "home",
    Qt.Key_End: "end", Qt.Key_PageUp: "page_up", Qt.Key_PageDown: "page_down",
    Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right",
    Qt.Key_Control: "ctrl", Qt.Key_Alt: "alt", Qt.Key_Shift: "shift",
    Qt.Key_Meta: "cmd", Qt.Key_CapsLock: "caps_lock", Qt.Key_NumLock: "num_lock",
    Qt.Key_Print: "print_screen", Qt.Key_Pause: "pause", Qt.Key_Menu: "menu",
    Qt.Key_F1: "f1", Qt.Key_F2: "f2", Qt.Key_F3: "f3", Qt.Key_F4: "f4",
    Qt.Key_F5: "f5", Qt.Key_F6: "f6", Qt.Key_F7: "f7", Qt.Key_F8: "f8",
    Qt.Key_F9: "f9", Qt.Key_F10: "f10", Qt.Key_F11: "f11", Qt.Key_F12: "f12",
}
_QT_BUTTONS = {
    Qt.LeftButton: "left", Qt.RightButton: "right", Qt.MiddleButton: "middle",
}


class RemoteView(QWidget):
    release_requested = Signal()
    paste_requested = Signal()

    def __init__(self, net: Net):
        super().__init__()
        self.net = net
        self._img = QImage()
        self._draw = QRectF()
        self._control_enabled = True
        self._pressed_keys = {}
        self._pressed_buttons = set()
        self._last_pos = (0.5, 0.5)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(640, 400)

    def set_frame(self, data: bytes):
        img = QImage()
        if img.loadFromData(data, "JPG"):
            self._img = img
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        if self._img.isNull():
            return
        iw, ih = self._img.width(), self._img.height()
        W, H = self.width(), self.height()
        scale = min(W / iw, H / ih)
        dw, dh = iw * scale, ih * scale
        ox, oy = (W - dw) / 2, (H - dh) / 2
        self._draw = QRectF(ox, oy, dw, dh)
        p.drawImage(self._draw, self._img)

    def set_control_enabled(self, enabled: bool):
        if not enabled:
            self.release_all()
        self._control_enabled = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)

    def release_all(self):
        for name in reversed(list(self._pressed_keys.values())):
            self.net.send_json(P.key(P.K_UP, name))
        self._pressed_keys.clear()
        for button in self._pressed_buttons:
            self.net.send_json(P.mouse(P.M_UP, *self._last_pos, button=button))
        self._pressed_buttons.clear()

    def focusOutEvent(self, event):
        self.release_all()
        super().focusOutEvent(event)

    def hideEvent(self, event):
        self.release_all()
        super().hideEvent(event)

    def event(self, event):
        if self._control_enabled:
            if event.type() == QEvent.ShortcutOverride:
                event.accept()
                return True
            if event.type() in (QEvent.KeyPress, QEvent.KeyRelease):
                if event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
                    handler = self.keyPressEvent if event.type() == QEvent.KeyPress else self.keyReleaseEvent
                    handler(event)
                    return True
        return super().event(event)

    def _norm(self, pos, clamp=False):
        if self._draw.width() <= 0 or self._draw.height() <= 0:
            return None
        nx = (pos.x() - self._draw.x()) / self._draw.width()
        ny = (pos.y() - self._draw.y()) / self._draw.height()
        if clamp:
            return max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny))
        if nx < 0 or nx > 1 or ny < 0 or ny > 1:
            return None
        return nx, ny

    def mouseMoveEvent(self, e):
        n = self._norm(e.position(), clamp=bool(self._pressed_buttons))
        if self._control_enabled and n:
            self._last_pos = n
            self.net.send_json(P.mouse(P.M_MOVE, n[0], n[1]))

    def mousePressEvent(self, e):
        self.setFocus()
        n = self._norm(e.position())
        button = _QT_BUTTONS.get(e.button())
        if self._control_enabled and n and button:
            self._last_pos = n
            self._pressed_buttons.add(button)
            self.net.send_json(P.mouse(
                P.M_DOWN, n[0], n[1], button))

    def mouseDoubleClickEvent(self, e):
        self.mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        button = _QT_BUTTONS.get(e.button())
        if button in self._pressed_buttons:
            n = self._norm(e.position(), clamp=True) or self._last_pos
            self._last_pos = n
            self._pressed_buttons.discard(button)
            self.net.send_json(P.mouse(
                P.M_UP, n[0], n[1], button))

    def wheelEvent(self, e):
        n = self._norm(e.position())
        dx, dy = int(e.angleDelta().x() / 120), int(e.angleDelta().y() / 120)
        if self._control_enabled and n and (dx or dy):
            self._last_pos = n
            self.net.send_json(P.mouse(P.M_SCROLL, *n, dx=dx, dy=dy))

    def _key_name(self, e):
        if e.key() in _QT_KEYMAP:
            return _QT_KEYMAP[e.key()]
        txt = e.text()
        if len(txt) == 1 and txt.isprintable() and txt != " ":
            return txt
        # Qt gives Ctrl+C a control character (\x03), not the letter 'c'.
        if Qt.Key_A <= e.key() <= Qt.Key_Z:
            return chr(e.key()).lower()
        if Qt.Key_0 <= e.key() <= Qt.Key_9:
            return chr(e.key())
        return None

    def keyPressEvent(self, e):
        if not self._control_enabled:
            return
        if (e.key() == Qt.Key_Escape and
                e.modifiers() & Qt.ControlModifier and e.modifiers() & Qt.ShiftModifier):
            self.set_control_enabled(False)
            self.release_requested.emit()
            return
        if e.key() == Qt.Key_V and e.modifiers() & Qt.ControlModifier and not e.isAutoRepeat():
            # Paste the controller clipboard instead of typing a remote Ctrl+V.
            if Qt.Key_Control in self._pressed_keys:
                self.net.send_json(P.key(P.K_UP, "ctrl"))
                self._pressed_keys.pop(Qt.Key_Control, None)
            self.paste_requested.emit()
            e.accept()
            return
        name = self._pressed_keys.get(e.key()) or self._key_name(e)
        if name:
            self._pressed_keys[e.key()] = name
            self.net.send_json(P.key(P.K_DOWN, name))
            e.accept()

    def keyReleaseEvent(self, e):
        if e.isAutoRepeat():
            return
        name = self._pressed_keys.pop(e.key(), None)
        if name:
            self.net.send_json(P.key(P.K_UP, name))
            e.accept()


class RemoteSession(QWidget):
    """A single device's live tab, backed by one Net control session."""

    def __init__(self, relay_url: str, network_key: str, device: dict):
        super().__init__()
        self.device = device  # {id, name, online}
        self.signals = Signals(self)
        self.net = Net(relay_url, network_key, device["id"], self.signals)
        self.view = RemoteView(self.net)
        self._connected = False
        self.view.set_control_enabled(False)

        controls = QHBoxLayout()
        self.control = QCheckBox("Control mouse and keyboard")
        self.control.setChecked(True)
        self.control.toggled.connect(self._toggle_control)
        self.view.release_requested.connect(lambda: self.control.setChecked(False))
        controls.addWidget(self.control)
        self.refresh = QPushButton("Refresh screen")
        self.refresh.clicked.connect(self._refresh)
        controls.addWidget(self.refresh)
        self.block = QCheckBox("Block local input on remote PC")
        self.block.setEnabled(False)
        self.block.toggled.connect(self._toggle_block)
        controls.addWidget(self.block)

        controls.addSpacing(12)
        controls.addWidget(QLabel("FPS"))
        self.fps = QSpinBox()
        self.fps.setRange(1, 30)
        self.fps.setValue(8)
        self.fps.valueChanged.connect(self._send_stream_config)
        controls.addWidget(self.fps)

        controls.addWidget(QLabel("Quality"))
        self.quality = QSpinBox()
        self.quality.setRange(10, 95)
        self.quality.setValue(45)
        self.quality.valueChanged.connect(self._send_stream_config)
        controls.addWidget(self.quality)

        controls.addWidget(QLabel("Scale %"))
        self.scale = QSpinBox()
        self.scale.setRange(15, 100)
        self.scale.setValue(45)
        self.scale.setToolTip("Lower = much faster over the relay (recommended 40–50).")
        self.scale.valueChanged.connect(self._send_stream_config)
        controls.addWidget(self.scale)

        controls.addWidget(QLabel("Display"))
        self.display = QComboBox()
        self.display.addItem("All", 0)
        self.display.addItem("1", 1)
        self.display.addItem("2", 2)
        self.display.addItem("3", 3)
        self.display.setToolTip(
            "All shows every monitor in one picture so clicks reach display 2. "
            "Choose 2 to control only the second screen.")
        self.display.currentIndexChanged.connect(self._send_stream_config)
        controls.addWidget(self.display)

        self.paste_btn = QPushButton("Paste")
        self.paste_btn.setToolTip("Paste text or files copied on this computer (Ctrl+V).")
        self.paste_btn.clicked.connect(self._paste_from_controller)
        controls.addWidget(self.paste_btn)
        self.send_file_btn = QPushButton("Send file")
        self.send_file_btn.setToolTip("Copy a file onto the remote desktop.")
        self.send_file_btn.clicked.connect(self._pick_file)
        controls.addWidget(self.send_file_btn)

        controls.addStretch(1)
        self.status = QLabel("connecting…")
        controls.addWidget(self.status)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(controls)
        layout.addWidget(QLabel(
            "Click the remote screen to type. Ctrl+V pastes text or files from this computer. "
            "Ctrl+Shift+Esc releases control."))
        layout.addWidget(self.view, 1)

        self.view.paste_requested.connect(self._paste_from_controller)
        self.signals.frame.connect(self.view.set_frame, Qt.ConnectionType.QueuedConnection)
        self.signals.status.connect(self.status.setText, Qt.ConnectionType.QueuedConnection)
        self.signals.peer.connect(self._on_peer, Qt.ConnectionType.QueuedConnection)
        self.net.start()

    def _stream_config(self) -> dict:
        return P.config(
            fps=self.fps.value(),
            quality=self.quality.value(),
            scale=self.scale.value() / 100.0,
            monitor=int(self.display.currentData()),
        )

    def _send_stream_config(self, *_):
        self.net.send_json(self._stream_config())

    def _toggle_block(self, checked: bool):
        self.net.send_json({"type": P.LOCK_INPUT if checked else P.UNLOCK_INPUT})

    def _toggle_control(self, enabled: bool):
        self.view.set_control_enabled(enabled and self._connected)
        self.block.setEnabled(enabled and self._connected)
        if not enabled:
            self.block.setChecked(False)

    def _refresh(self):
        self._on_peer(False)
        self.status.setText("refreshing…")
        self.net.reconnect()

    def _on_peer(self, joined: bool):
        self._connected = joined
        self.view.set_control_enabled(joined and self.control.isChecked())
        self.block.setEnabled(joined and self.control.isChecked())
        if not joined and self.block.isChecked():
            self.block.setChecked(False)
        if joined:
            self.net.send_json(self._stream_config())

    def _paste_from_controller(self):
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is not None and mime.hasUrls():
            files = [
                url.toLocalFile() for url in mime.urls()
                if url.isLocalFile() and os.path.isfile(url.toLocalFile())
            ]
            if files:
                for path in files:
                    self._send_file(path)
                return
        text = clipboard.text()
        if text:
            self.net.send_json(P.clipboard(text[:200_000]))
            self.status.setText("pasted clipboard text")
            return
        self.status.setText("clipboard is empty")

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Send file to remote PC")
        if path:
            self._send_file(path)

    def _send_file(self, path: str):
        file_path = Path(path)
        try:
            data = file_path.read_bytes()
        except OSError as exc:
            self.status.setText(f"cannot read file: {exc}")
            return
        if len(data) > 32 * 1024 * 1024:
            self.status.setText("file is larger than 32 MB")
            return
        transfer_id = uuid.uuid4().hex[:12]
        self.net.send_json(P.file_begin(transfer_id, file_path.name, len(data)))
        step = 192 * 1024
        for offset in range(0, len(data), step):
            piece = base64.b64encode(data[offset:offset + step]).decode("ascii")
            self.net.send_json(P.file_chunk(transfer_id, piece))
        self.net.send_json(P.file_end(transfer_id))
        self.status.setText(f"sent {file_path.name} to the remote desktop")

    def shutdown(self):
        self.view.set_control_enabled(False)
        self.net.stop()
