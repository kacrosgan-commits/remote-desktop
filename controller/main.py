"""Controller dashboard with live screen previews.

Enter your Relay URL and Network Key once. Every agent using that same
network key appears here with online/offline status and a live thumbnail.
Click View (or double-click) an online device to control it.

Run:  python -m controller.main
"""
import sys
import os

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QBrush, QImage, QPainter, QIcon, QPixmap, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QTabWidget,
    QTabBar, QMessageBox, QScrollArea, QFrame, QSizePolicy, QStackedWidget,
    QToolButton, QSplitter, QSystemTrayIcon, QMenu,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from controller import store  # noqa: E402
import branding  # noqa: E402
import config  # noqa: E402
from controller.net import ConsoleNet, ConsoleSignals, PreviewFeed  # noqa: E402
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
QPushButton#RemoveBtn {
    background: #ffffff;
    color: #b91c1c;
    border: 1px solid #fecaca;
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 600;
}
QPushButton#RemoveBtn:hover {
    background: #fef2f2;
    border-color: #f87171;
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
        self._aspect = 16 / 9
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def set_frame(self, data: bytes):
        img = QImage()
        if img.loadFromData(data, "JPG") and img.height() > 0:
            self._img = img
            self._aspect = img.width() / img.height()
            self._fit_height()
            self.update()

    def clear_frame(self):
        self._img = QImage()
        self.update()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width: int) -> int:
        return max(64, int(width / max(self._aspect, 0.5)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def _fit_height(self):
        height = self.heightForWidth(max(1, self.width()))
        if self.maximumHeight() != height:
            self.setFixedHeight(height)

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
    remove_requested = Signal(dict)

    def __init__(self, device: dict):
        super().__init__()
        self.setObjectName("DeviceCard")
        self.device = dict(device)
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.thumb = ScreenThumb()
        layout.addWidget(self.thumb, 0)

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
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setObjectName("RemoveBtn")
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.device))
        footer.addWidget(self.remove_btn)
        layout.addLayout(footer)
        self._pay_on = False
        self.pay_dot = QLabel("●", self.thumb)
        self.pay_dot.setStyleSheet(
            "color: #dc2626; font-size: 22px; font-weight: 800; background: transparent;")
        self.pay_dot.move(8, 4)
        self.pay_dot.hide()
        self._blink = QTimer(self)
        self._blink.setInterval(450)
        self._blink.timeout.connect(self._toggle_pay_dot)
        self._apply_status()

    def set_payment(self, active: bool):
        """Blink a red dot on this screen while a payment app is open."""
        if active and not self._pay_on:
            self._pay_on = True
            self.pay_dot.show()
            self._blink.start()
        elif not active and self._pay_on:
            self._pay_on = False
            self._blink.stop()
            self.pay_dot.hide()

    def _toggle_pay_dot(self):
        self.pay_dot.setVisible(not self.pay_dot.isVisible())

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
        self._previews: dict[str, PreviewFeed] = {}
        self._hidden: set[str] = store.load_hidden()
        self._paused_previews: set[str] = set()  # View tab open for these
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
        root.addWidget(top)

        self.status = QLabel("not connected")
        self.status.setObjectName("StatusBar")
        root.addWidget(self.status)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)

        side = QFrame()
        side.setObjectName("SidePanel")
        side.setMinimumWidth(240)
        side.setMaximumWidth(340)
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
        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.setObjectName("RemoveBtn")
        self.remove_btn.setToolTip(
            "Hide this PC from the dashboard. Use Show removed to bring it back.")
        self.remove_btn.clicked.connect(self._remove_selected)
        side_layout.addWidget(self.remove_btn)
        self.show_removed_btn = QPushButton("Show removed")
        self.show_removed_btn.setObjectName("SecondaryBtn")
        self.show_removed_btn.setToolTip(
            "Un-hide PCs removed earlier (needed after reinstalling agent on the same PC).")
        self.show_removed_btn.clicked.connect(self._show_removed)
        side_layout.addWidget(self.show_removed_btn)
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
        self.status.setText("connecting…")
        if self.console and self._credentials == (relay, key):
            self.console.reconnect()
            return
        if self.console:
            self.console.stop()
            self.console = None
        if getattr(self, "signals", None) is not None:
            try:
                self.signals.devices.disconnect()
                self.signals.preview.disconnect()
                self.signals.status.disconnect()
                self.signals.alert.disconnect()
            except (RuntimeError, TypeError):
                pass
        self._credentials = (relay, key)
        # Parent to this widget so queued slots run on the GUI thread.
        self.signals = ConsoleSignals(self)
        # IMPORTANT: connect to real QObject methods with QueuedConnection.
        # Lambdas run on the network thread and cannot paint QWidget previews.
        self.signals.devices.connect(
            self._update_devices, Qt.ConnectionType.QueuedConnection)
        self.signals.preview.connect(
            self._on_preview, Qt.ConnectionType.QueuedConnection)
        self.signals.status.connect(
            self._on_link_status, Qt.ConnectionType.QueuedConnection)
        self.signals.alert.connect(
            self._on_alert, Qt.ConnectionType.QueuedConnection)
        self.console = ConsoleNet(relay, key, self.signals)
        self.console.start()

    def _on_link_status(self, text: str):
        self.status.setText(text)
        if text.startswith("disconnected"):
            win = self.window()
            if isinstance(win, MainWindow):
                win.notify_link_problem(text)

    def _on_alert(self, alert: dict):
        device_id = alert.get("device_id")
        active = bool(alert.get("active", True))
        card = self._cards.get(device_id) if device_id else None
        if card is not None:
            card.set_payment(active)
        if not active:
            return
        win = self.window()
        if isinstance(win, MainWindow):
            win.notify_watch_alert(alert)

    def _update_devices(self, devices: list):
        # Drop locally-hidden devices so Remove stays in sync even if the agent
        # reconnects (online remove would otherwise make the PC reappear).
        devices = [d for d in devices if d.get("id") and d.get("id") not in self._hidden]
        devices = sorted(
            devices,
            key=lambda d: (not d.get("online"), str(d.get("name") or "").lower()),
        )

        seen = set()
        selected_id = None
        current = self.list.currentItem()
        if current is not None:
            data = current.data(Qt.UserRole)
            if data:
                selected_id = data.get("id")
        self.list.clear()
        for d in devices:
            seen.add(d["id"])
            self._devices[d["id"]] = d
            card = self._cards.get(d["id"])
            if card is None:
                card = DeviceCard(d)
                card.view_requested.connect(self._open_device)
                card.remove_requested.connect(self._remove_device)
                self._cards[d["id"]] = card
            else:
                card.update_device(d)

            item = QListWidgetItem()
            item.setData(Qt.UserRole, d)
            online = bool(d["online"])
            item.setText(f"{'●' if online else '○'}  {d['name']}"
                         f"{'' if online else '  (offline)'}")
            if not online:
                item.setForeground(QBrush(QColor(150, 150, 150)))
            self.list.addItem(item)
            if d["id"] == selected_id:
                self.list.setCurrentItem(item)

        for device_id in list(self._cards):
            if device_id not in seen:
                self._stop_preview(device_id)
                card = self._cards.pop(device_id)
                card.setParent(None)
                card.deleteLater()
                self._devices.pop(device_id, None)

        count = len(devices)
        online_count = sum(1 for d in devices if d.get("online"))
        self.side_title.setText(f"Devices ({count})")
        self.screens_title.setText(f"All Screens ({online_count})")
        if count == 0 and self._hidden:
            self.status.setText(
                f"connected — {len(self._hidden)} computer(s) hidden. Click Show removed.")
        elif count == 0:
            self.status.setText(
                "connected — waiting for an agent. It must use this same Relay URL and Network Key.")
        else:
            self.status.setText(f"connected — {online_count} online, {count - online_count} offline")
        self._relayout_cards()
        self._sync_previews()

    def _sync_previews(self):
        """Attach a low-rate control session per online card for live thumbnails."""
        if not self._credentials:
            return
        relay, key = self._credentials
        wanted = {
            did for did, d in self._devices.items()
            if d.get("online") and did not in self._paused_previews
        }
        for did in list(self._previews):
            if did not in wanted:
                self._stop_preview(did)
        for did in wanted:
            if did in self._previews:
                continue
            card = self._cards.get(did)
            if card is None:
                continue
            try:
                self._previews[did] = PreviewFeed(
                    relay, key, did, card, self,
                    on_offline=self._mark_device_offline)
            except Exception:
                pass

    def _mark_device_offline(self, device_id: str):
        """Flip a card to Offline immediately when its preview session drops.

        The relay DEVICE_LIST push/poll confirms soon after; this avoids a
        multi-second stale Online state after agent.exe is killed/uninstalled.
        Never closes the controller window.
        """
        current = self._devices.get(device_id)
        if not current or not current.get("online"):
            self._stop_preview(device_id)
            return
        devices = []
        for did, d in self._devices.items():
            if did == device_id:
                devices.append({**d, "online": False})
            else:
                devices.append(d)
        self._update_devices(devices)

    def _stop_preview(self, device_id: str):
        feed = self._previews.pop(device_id, None)
        if feed is not None:
            feed.stop()

    def pause_preview(self, device_id: str):
        """Release the controller slot so a View tab can take over."""
        self._paused_previews.add(device_id)
        self._stop_preview(device_id)

    def resume_preview(self, device_id: str):
        self._paused_previews.discard(device_id)
        self._sync_previews()

    def _remove_selected(self):
        item = self.list.currentItem()
        if item is None:
            QMessageBox.information(self, "Remove",
                                    "Select a computer in the list first, "
                                    "or click Remove on a screen card.")
            return
        device = item.data(Qt.UserRole) or {}
        self._remove_device(device)

    def _remove_device(self, device: dict):
        if not device or not device.get("id"):
            return
        if self.console is None or not self._credentials:
            QMessageBox.warning(self, "Not connected",
                                "Connect to the relay first.")
            return
        name = device.get("name", "Device")
        device_id = device["id"]
        if device.get("online"):
            answer = QMessageBox.question(
                self, "Remove PC?",
                f"Remove {name} from this dashboard?\n\n"
                "It will stay hidden here even if the agent is still running.\n"
                "The agent on that PC is not uninstalled.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer != QMessageBox.Yes:
                return
        else:
            answer = QMessageBox.question(
                self, "Remove PC?",
                f"Remove {name} from the list?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer != QMessageBox.Yes:
                return
        window = self.window()
        if isinstance(window, MainWindow):
            window.close_device_session(device_id)
        self.pause_preview(device_id)
        # Persist hide so the UI stays in sync if the agent reconnects.
        self._hidden = store.hide_device(device_id)
        self.console.remove_device(device_id)
        # Optimistic local update (don't wait for relay round-trip).
        remaining = [d for d in self._devices.values() if d["id"] != device_id]
        self._update_devices(remaining)

    def _show_removed(self):
        if not self._hidden:
            QMessageBox.information(self, "Show removed",
                                    "No removed computers are hidden.")
            return
        self._hidden = store.clear_hidden()
        if self.console is not None:
            self.console.request_devices()
        self.status.setText("showing removed computers…")

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
                self.grid_layout.addWidget(card, i // cols, i % cols, Qt.AlignTop)
            # Fill remaining cells so stretch stays at bottom-right.
            for c in range(cols):
                self.grid_layout.setColumnStretch(c, 1)
        else:
            for card in ordered:
                self.list_layout.insertWidget(self.list_layout.count() - 1, card)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._grid_mode and self._cards:
            self._relayout_cards()

    def _on_preview(self, device_id: str, jpeg):
        # Optional PREVIEW messages from an updated relay (extra path).
        if not isinstance(jpeg, (bytes, bytearray, memoryview)):
            return
        card = self._cards.get(device_id)
        if card is not None:
            card.set_preview(bytes(jpeg))

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
        # Free the controller slot held by the dashboard thumbnail feed.
        self.pause_preview(device["id"])
        self.on_connect(*self._credentials, device)

    def shutdown_previews(self):
        for did in list(self._previews):
            self._stop_preview(did)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{branding.DISPLAY_NAME} — Controller")
        self.setStyleSheet(_STYLE)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.setCentralWidget(self.tabs)

        self.dashboard = Dashboard(self._open_session)
        self.tabs.addTab(self.dashboard, "Devices")
        self.tabs.tabBar().setTabButton(0, QTabBar.RightSide, None)

        self.statusBar().showMessage("Ready")
        self._setup_tray()

    def _setup_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = _tray_icon()
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(f"{branding.DISPLAY_NAME} Controller")
        menu = QMenu()
        show_act = QAction(f"Show {branding.DISPLAY_NAME}", self)
        show_act.triggered.connect(self._raise_window)
        quit_act = QAction("Quit", self)
        # Explicit Quit only — agent offline/uninstall must never call this.
        quit_act.triggered.connect(QApplication.instance().quit)
        menu.addAction(show_act)
        menu.addSeparator()
        menu.addAction(quit_act)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._raise_window()

    def _raise_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def notify_link_problem(self, text: str):
        """Connection warnings stay on this PC. The agent does not pop a dialog."""
        self.statusBar().showMessage(text, 20000)
        if self.tray is not None:
            self.tray.showMessage(
                "Connection problem", text, QSystemTrayIcon.Warning, 10000)

    def notify_watch_alert(self, alert: dict):
        """Tray notification only. No dialog and no taskbar alarm."""
        device = alert.get("device_name") or alert.get("device_id") or "Unknown PC"
        app_name = alert.get("app") or "Payment app"
        detail = (alert.get("detail") or "").strip()
        title = f"{app_name} is running"
        body = f"On {device}"
        if detail:
            body = f"{body}\n{detail}"
        self.statusBar().showMessage(f"{title} — {device}", 20000)
        if self.tray is not None:
            self.tray.showMessage(title, body, QSystemTrayIcon.Information, 8000)

    def _open_session(self, relay, key, device):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RemoteSession) and w.device["id"] == device["id"]:
                self.tabs.setCurrentIndex(i)
                return
        self.dashboard.pause_preview(device["id"])
        session = RemoteSession(relay, key, device)
        idx = self.tabs.addTab(session, device["name"])
        self.tabs.setCurrentIndex(idx)

    def _close_tab(self, index):
        if index == 0:
            return
        w = self.tabs.widget(index)
        device_id = None
        if isinstance(w, RemoteSession):
            device_id = w.device.get("id")
            w.shutdown()
        self.tabs.removeTab(index)
        w.deleteLater()
        if device_id:
            self.dashboard.resume_preview(device_id)

    def close_device_session(self, device_id: str):
        for i in range(self.tabs.count() - 1, 0, -1):
            w = self.tabs.widget(i)
            if isinstance(w, RemoteSession) and w.device.get("id") == device_id:
                self._close_tab(i)

    def closeEvent(self, e):
        if self.dashboard.console:
            self.dashboard.console.stop()
        self.dashboard.shutdown_previews()
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RemoteSession):
                w.shutdown()
        if self.tray is not None:
            self.tray.hide()
        super().closeEvent(e)


def _tray_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#2563eb"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 12, 12)
    p.setPen(QColor("#ffffff"))
    p.drawText(pm.rect(), Qt.AlignCenter, "RD")
    p.end()
    return QIcon(pm)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(branding.DISPLAY_NAME)
    app.setQuitOnLastWindowClosed(True)
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
