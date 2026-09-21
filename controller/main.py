"""Controller dashboard with auto-discovery.

Enter your Relay URL and Network Key once. Every agent using that same
network key appears here automatically and shows online/offline live.
Double-click an online device to control it (opens as a tab).

Run:  python -m controller.main
"""
import sys
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QTabWidget,
    QTabBar, QMessageBox
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from controller import store  # noqa: E402
import config  # noqa: E402
from controller.net import ConsoleNet, ConsoleSignals  # noqa: E402
from controller.view import RemoteSession  # noqa: E402


class Dashboard(QWidget):
    def __init__(self, on_connect):
        super().__init__()
        self.on_connect = on_connect
        self.console: ConsoleNet | None = None
        self._credentials = None
        relay, network_key = store.load()
        # Fall back to the values baked in at build time (config.py) so the
        # app connects with no typing on first launch.
        if not relay:
            relay = config.RELAY_URL
        if not network_key:
            network_key = config.NETWORK_KEY

        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Relay URL"))
        self.relay = QLineEdit(relay)
        self.relay.setPlaceholderText("ws://46.250.249.191:8000/ws")
        row.addWidget(self.relay, 2)
        row.addWidget(QLabel("Network Key"))
        self.key = QLineEdit(network_key)
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("shared secret — same on every machine")
        row.addWidget(self.key, 1)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._start_console)
        row.addWidget(self.connect_btn)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Reload devices from the relay (F5)")
        self.refresh_btn.clicked.connect(self._start_console)
        row.addWidget(self.refresh_btn)
        self.refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        self.refresh_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.refresh_shortcut.activated.connect(self._start_console)
        layout.addLayout(row)

        self.status = QLabel("not connected")
        layout.addWidget(self.status)

        layout.addWidget(QLabel("Devices (double-click an online device to control):"))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._connect_selected)
        layout.addWidget(self.list, 1)

        # auto-connect if we already have both values saved
        if relay and network_key:
            self._start_console()

    def _start_console(self):
        relay = self.relay.text().strip()
        key = self.key.text().strip()
        if not relay or not key:
            QMessageBox.warning(self, "Missing info",
                                "Enter both the Relay URL and the Network Key.")
            return
        store.save(relay, key)
        self.status.setText("refreshing devices…")
        self.list.clear()
        if self.console and self._credentials == (relay, key):
            self.console.reconnect()
            return
        if self.console:
            self.console.stop()
        self._credentials = (relay, key)
        self.signals = ConsoleSignals()
        signals = self.signals
        # Ignore late events from a connection using the previous credentials.
        signals.devices.connect(lambda devices: self._update_devices(devices)
                                if self.signals is signals else None)
        signals.status.connect(lambda status: self.status.setText(status)
                               if self.signals is signals else None)
        self.console = ConsoleNet(relay, key, self.signals)
        self.console.start()

    def _update_devices(self, devices: list):
        self.list.clear()
        devices = sorted(devices, key=lambda d: (not d["online"], d["name"].lower()))
        for d in devices:
            dot = "●" if d["online"] else "○"
            suffix = "" if d["online"] else "  (offline)"
            item = QListWidgetItem(f"{dot}  {d['name']}{suffix}")
            item.setData(Qt.UserRole, d)
            if not d["online"]:
                item.setForeground(QBrush(QColor(150, 150, 150)))
            self.list.addItem(item)

    def _connect_selected(self, item: QListWidgetItem):
        d = item.data(Qt.UserRole)
        if not d:
            return
        if not d["online"]:
            QMessageBox.information(self, "Offline",
                                    f"{d['name']} is offline right now.")
            return
        self.on_connect(*self._credentials, d)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RemoteDesk — Controller")
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
    win.resize(1150, 750)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
