"""Controller dashboard with live screen previews.

Enter your Relay URL and Network Key once. Every agent using that same
network key appears here with online/offline status and a live thumbnail.
Click View (or double-click) an online device to control it.

Run:  python -m controller.main
"""
import sys
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush, QKeySequence, QShortcut, QImage, QPainter
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QTabWidget,
    QTabBar, QMessageBox, QScrollArea, QFrame, QSizePolicy, QStackedWidget,
    QToolButton, QSplitter,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from controller import store  # noqa: E402
import config  # noqa: E402
from controller.net import ConsoleNet, ConsoleSignals  # noqa: E402
from controller.view import RemoteSession  # noqa: E402


_STYLE = """
QMainWindow, QWidget#DashboardRoot {
    background: #f4f6f8;
    color: #1f2937;
    font-size: 13px;
}
QFrame#TopBar {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
}
QLineEdit {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: #2563eb;
}
QPushButton#PrimaryBtn {
    background: #2563eb;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton#PrimaryBtn:hover { background: #1d4ed8; }
QPushButton#SecondaryBtn {
    background: #ffffff;
    color: #111827;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 8px 14px;
}
QPushButton#SecondaryBtn:hover { background: #f9fafb; }
QFrame#SidePanel, QFrame#ScreensPanel {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
}
QLabel#SectionTitle {
    font-size: 14px;
    font-weight: 700;
    color: #111827;
}
QListWidget#DeviceList {
    border: none;
    background: transparent;
    outline: none;
}
QListWidget#DeviceList::item {
    padding: 10px 12px;
    border-radius: 8px;
    margin: 2px 4px;
}
QListWidget#DeviceList::item:selected {
    background: #eff6ff;
    border-left: 3px solid #2563eb;
}
QFrame#DeviceCard {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}
QFrame#DeviceCard:hover {
    border-color: #93c5fd;
}
QLabel#StatusOnline { color: #15803d; font-weight: 600; }
QLabel#StatusOffline { color: #6b7280; font-weight: 600; }
QPushButton#ViewBtn {
    background: #2563eb;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
}
QPushButton#ViewBtn:hover { background: #1d4ed8; }
QPushButton#ViewBtn:disabled {
    background: #e5e7eb;
    color: #9ca3af;
}
QToolButton#ViewToggle {
    background: transparent;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px 10px;
}
QToolButton#ViewToggle:checked {
    background: #2563eb;
    color: white;
    border-color: #2563eb;
}
QLabel#StatusBar {
    color: #6b7280;
    padding: 2px 4px;
}
"""


class ScreenThumb(QWidget):
    """Letterboxed JPEG preview used inside each device card."""

    def __init__(self):
        super().__init__()
        self._img = QImage()
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def set_frame(self, data: bytes):
        img = QImage()
        if img.loadFromData(data, "JPG"):
            self._img = img
            self.update()

    def clear_frame(self):
        self._img = QImage()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0f172a"))
        if self._img.isNull():
            p.setPen(QColor("#94a3b8"))
            p.drawText(self.rect(), Qt.AlignCenter, "Waiting for screen…")
            return
        iw, ih = self._img.width(), self._img.height()
        W, H = max(1, self.width()), max(1, self.height())
        scale = min(W / iw, H / ih)
        dw, dh = iw * scale, ih * scale
        ox, oy = (W - dw) / 2, (H - dh) / 2
        p.drawImage(ox, oy, self._img.scaled(
            int(dw), int(dh), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))


class DeviceCard(QFrame):
    view_requested = Signal(dict)

    def __init__(self, device: dict):
        super().__init__()
        self.setObjectName("DeviceCard")
        self.device = dict(device)
        self.setMinimumSize(280, 220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.thumb = ScreenThumb()
        layout.addWidget(self.thumb, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(12, 10, 12, 10)
        self.name = QLabel(device.get("name", "Device"))
        self.name.setStyleSheet("font-weight: 700;")
        footer.addWidget(self.name, 1)
        self.status = QLabel()
        footer.addWidget(self.status)
        self.view_btn = QPushButton("View")
        self.view_btn.setObjectName("ViewBtn")
        self.view_btn.clicked.connect(lambda: self.view_requested.emit(self.device))
        footer.addWidget(self.view_btn)
        layout.addLayout(footer)
        self._apply_status()

    def update_device(self, device: dict):
        self.device = dict(device)
        self.name.setText(device.get("name", "Device"))
        self._apply_status()
        if not device.get("online"):
            self.thumb.clear_frame()

    def set_preview(self, jpeg: bytes):
        if self.device.get("online"):
            self.thumb.set_frame(jpeg)

    def _apply_status(self):
        online = bool(self.device.get("online"))
        self.status.setObjectName("StatusOnline" if online else "StatusOffline")
        self.status.setText("● Online" if online else "○ Offline")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.view_btn.setEnabled(online)


class Dashboard(QWidget):
    def __init__(self, on_connect):
        super().__init__()
        self.setObjectName("DashboardRoot")
        self.on_connect = on_connect
        self.console: ConsoleNet | None = None
        self._credentials = None
        self._devices: dict[str, dict] = {}
        self._cards: dict[str, DeviceCard] = {}
        self._grid_mode = True
        relay, network_key = store.load()
        if not relay:
            relay = config.RELAY_URL
        if not network_key:
            network_key = config.NETWORK_KEY

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        top = QFrame()
        top.setObjectName("TopBar")
        row = QHBoxLayout(top)
        row.setContentsMargins(12, 10, 12, 10)
        row.addWidget(QLabel("Relay URL"))
        self.relay = QLineEdit(relay)
        self.relay.setPlaceholderText("ws://host:8000/ws")
        row.addWidget(self.relay, 2)
        row.addWidget(QLabel("Network Key"))
        self.key = QLineEdit(network_key)
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("shared secret — same on every machine")
        row.addWidget(self.key, 1)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("PrimaryBtn")
        self.connect_btn.clicked.connect(self._start_console)
        row.addWidget(self.connect_btn)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("SecondaryBtn")
        self.refresh_btn.setToolTip("Reload devices from the relay (F5)")
        self.refresh_btn.clicked.connect(self._start_console)
        row.addWidget(self.refresh_btn)
        self.refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        self.refresh_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.refresh_shortcut.activated.connect(self._start_console)
        root.addWidget(top)

        self.status = QLabel("not connected")
        self.status.setObjectName("StatusBar")
        root.addWidget(self.status)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)

        side = QFrame()
        side.setObjectName("SidePanel")
        side.setMinimumWidth(220)
        side.setMaximumWidth(320)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(12, 12, 12, 12)
        self.side_title = QLabel("Devices (0)")
        self.side_title.setObjectName("SectionTitle")
        side_layout.addWidget(self.side_title)
        self.list = QListWidget()
        self.list.setObjectName("DeviceList")
        self.list.itemDoubleClicked.connect(self._connect_selected)
        self.list.itemClicked.connect(self._focus_card)
        side_layout.addWidget(self.list, 1)
        body.addWidget(side)

        screens = QFrame()
        screens.setObjectName("ScreensPanel")
        screens_layout = QVBoxLayout(screens)
        screens_layout.setContentsMargins(12, 12, 12, 12)
        header = QHBoxLayout()
        self.screens_title = QLabel("All Screens (0)")
        self.screens_title.setObjectName("SectionTitle")
        header.addWidget(self.screens_title, 1)
        self.grid_btn = QToolButton()
        self.grid_btn.setObjectName("ViewToggle")
        self.grid_btn.setText("Grid")
        self.grid_btn.setCheckable(True)
        self.grid_btn.setChecked(True)
        self.grid_btn.clicked.connect(lambda: self._set_view_mode(True))
        header.addWidget(self.grid_btn)
        self.list_btn = QToolButton()
        self.list_btn.setObjectName("ViewToggle")
        self.list_btn.setText("List")
        self.list_btn.setCheckable(True)
        self.list_btn.clicked.connect(lambda: self._set_view_mode(False))
        header.addWidget(self.list_btn)
        screens_layout.addLayout(header)

        self.screens_stack = QStackedWidget()
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_host = QWidget()
        self.grid_layout = QGridLayout(self.grid_host)
        self.grid_layout.setContentsMargins(4, 4, 4, 4)
        self.grid_layout.setSpacing(14)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.grid_scroll.setWidget(self.grid_host)
        self.screens_stack.addWidget(self.grid_scroll)

        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.NoFrame)
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(4, 4, 4, 4)
        self.list_layout.setSpacing(12)
        self.list_layout.addStretch(1)
        self.list_scroll.setWidget(self.list_host)
        self.screens_stack.addWidget(self.list_scroll)
        screens_layout.addWidget(self.screens_stack, 1)
        body.addWidget(screens)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        root.addWidget(body, 1)

        # Keep a plain attribute name used by existing tests.
        if relay and network_key:
            self._start_console()

    def _set_view_mode(self, grid: bool):
        self._grid_mode = grid
        self.grid_btn.setChecked(grid)
        self.list_btn.setChecked(not grid)
        self.screens_stack.setCurrentIndex(0 if grid else 1)
        self._relayout_cards()

    def _start_console(self):
        relay = self.relay.text().strip()
        key = self.key.text().strip()
        if not relay or not key:
            QMessageBox.warning(self, "Missing info",
                                "Enter both the Relay URL and the Network Key.")
            return
        store.save(relay, key)
        self.status.setText("refreshing devices…")
        if self.console and self._credentials == (relay, key):
            self.console.reconnect()
            return
        if self.console:
            self.console.stop()
        self._credentials = (relay, key)
        self.signals = ConsoleSignals()
        signals = self.signals
        signals.devices.connect(lambda devices: self._update_devices(devices)
                                if self.signals is signals else None)
        signals.preview.connect(lambda did, jpeg: self._on_preview(did, jpeg)
                                if self.signals is signals else None)
        signals.status.connect(lambda status: self.status.setText(status)
                               if self.signals is signals else None)
        self.console = ConsoleNet(relay, key, self.signals)
        self.console.start()

    def _update_devices(self, devices: list):
        devices = sorted(devices, key=lambda d: (not d["online"], d["name"].lower()))
        seen = set()
        self.list.clear()
        for d in devices:
            seen.add(d["id"])
            self._devices[d["id"]] = d
            card = self._cards.get(d["id"])
            if card is None:
                card = DeviceCard(d)
                card.view_requested.connect(self._open_device)
                self._cards[d["id"]] = card
            else:
                card.update_device(d)

            item = QListWidgetItem(d["name"])
            item.setData(Qt.UserRole, d)
            online = bool(d["online"])
            item.setText(f"{'●' if online else '○'}  {d['name']}"
                         f"{'' if online else '  (offline)'}")
            if not online:
                item.setForeground(QBrush(QColor(150, 150, 150)))
            self.list.addItem(item)

        for device_id in list(self._cards):
            if device_id not in seen:
                card = self._cards.pop(device_id)
                card.setParent(None)
                card.deleteLater()
                self._devices.pop(device_id, None)

        count = len(devices)
        online_count = sum(1 for d in devices if d["online"])
        self.side_title.setText(f"Devices ({count})")
        self.screens_title.setText(f"All Screens ({online_count})")
        self._relayout_cards()

    def _relayout_cards(self):
        # Detach from both layouts, then re-add in current mode.
        for card in self._cards.values():
            self.grid_layout.removeWidget(card)
            self.list_layout.removeWidget(card)
            card.setParent(None)

        ordered = sorted(
            self._cards.values(),
            key=lambda c: (not c.device.get("online"), c.device.get("name", "").lower()),
        )
        if self._grid_mode:
            cols = max(1, min(3, (self.grid_host.width() or 800) // 320))
            for i, card in enumerate(ordered):
                card.setMinimumHeight(220)
                self.grid_layout.addWidget(card, i // cols, i % cols)
            # Fill remaining cells so stretch stays at bottom-right.
            for c in range(cols):
                self.grid_layout.setColumnStretch(c, 1)
        else:
            for card in ordered:
                card.setMinimumHeight(200)
                self.list_layout.insertWidget(self.list_layout.count() - 1, card)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._grid_mode and self._cards:
            self._relayout_cards()

    def _on_preview(self, device_id: str, jpeg: bytes):
        card = self._cards.get(device_id)
        if card is not None:
            card.set_preview(jpeg)

    def _focus_card(self, item: QListWidgetItem):
        d = item.data(Qt.UserRole)
        if not d:
            return
        card = self._cards.get(d["id"])
        if card is not None:
            card.setFocus(Qt.OtherFocusReason)

    def _connect_selected(self, item: QListWidgetItem):
        d = item.data(Qt.UserRole)
        if d:
            self._open_device(d)

    def _open_device(self, device: dict):
        if not device:
            return
        # Prefer the latest status we know about.
        device = self._devices.get(device["id"], device)
        if not device.get("online"):
            QMessageBox.information(self, "Offline",
                                    f"{device.get('name', 'Device')} is offline right now.")
            return
        if not self._credentials:
            QMessageBox.warning(self, "Not connected",
                                "Connect to the relay first.")
            return
        self.on_connect(*self._credentials, device)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RemoteDesk — Controller")
        self.setStyleSheet(_STYLE)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.setCentralWidget(self.tabs)

        self.dashboard = Dashboard(self._open_session)
        self.tabs.addTab(self.dashboard, "Devices")
        self.tabs.tabBar().setTabButton(0, QTabBar.RightSide, None)

    def _open_session(self, relay, key, device):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RemoteSession) and w.device["id"] == device["id"]:
                self.tabs.setCurrentIndex(i)
                return
        session = RemoteSession(relay, key, device)
        idx = self.tabs.addTab(session, device["name"])
        self.tabs.setCurrentIndex(idx)

    def _close_tab(self, index):
        if index == 0:
            return
        w = self.tabs.widget(index)
        if isinstance(w, RemoteSession):
            w.shutdown()
        self.tabs.removeTab(index)
        w.deleteLater()

    def closeEvent(self, e):
        if self.dashboard.console:
            self.dashboard.console.stop()
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RemoteSession):
                w.shutdown()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
