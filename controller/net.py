"""Reconnectable dashboard and remote-session clients, each on its own thread."""
import asyncio
import base64
import threading

import websockets
from PySide6.QtCore import QObject, Qt, Signal

import protocol as P
from protocol.connection import run_pair


class ConsoleSignals(QObject):
    devices = Signal(list)
    # object (not bytes): safer across queued cross-thread deliveries in PySide.
    preview = Signal(str, object)  # device_id, jpeg bytes
    status = Signal(str)
    alert = Signal(dict)  # watched app opened on an agent PC


class Signals(QObject):
    frame = Signal(object)  # latest JPEG bytes (coalesced)
    status = Signal(str)
    peer = Signal(bool)


class _Client(threading.Thread):
    def __init__(self, url, network_key, signals):
        super().__init__(daemon=True)
        self.url, self.network_key, self.signals = url, network_key, signals
        self.loop = None
        self._attempt = None
        self._stopping = threading.Event()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        finally:
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    async def _main(self):
        backoff = 1
        while not self._stopping.is_set():
            self._attempt = asyncio.create_task(self._session())
            try:
                await self._attempt
                self.signals.status.emit("disconnected — reconnecting…")
            except asyncio.CancelledError:
                # A refresh cancels the current connection or backoff.
                backoff = 1
                continue
            except Exception as exc:
                self.signals.status.emit(f"disconnected: {exc}")
            finally:
                self._disconnected()
            if self._stopping.is_set():
                break
            self._attempt = asyncio.create_task(asyncio.sleep(backoff))
            try:
                await self._attempt
            except asyncio.CancelledError:
                backoff = 1
                continue
            backoff = min(backoff * 2, 15)

    def _disconnected(self):
        pass

    def _cancel_attempt(self):
        if self._attempt is not None:
            self._attempt.cancel()

    def reconnect(self):
        if self.loop is not None:
            try:
                self.loop.call_soon_threadsafe(self._cancel_attempt)
            except RuntimeError:  # Thread already closed its event loop.
                pass

    def stop(self):
        self._stopping.set()
        self.reconnect()


class ConsoleNet(_Client):
    """Dashboard client: live device list + previews; can remove devices."""

    # How often to ask the relay for a fresh list (backup if a push was missed).
    SYNC_INTERVAL_SEC = 3.0

    def __init__(self, url, network_key, signals):
        super().__init__(url, network_key, signals)
        self.outq = None
        self._connected = False

    async def _session(self):
        async with websockets.connect(self.url, max_size=None, close_timeout=2) as ws:
            self.outq = asyncio.Queue()
            self._connected = True
            await ws.send(P.dumps(P.auth_console(self.network_key)))
            # Do NOT use run_pair here: if the sender task fails, FIRST_COMPLETED
            # would cancel the receiver and drop live DEVICE_LIST pushes.
            sender = asyncio.create_task(self._send(ws))
            poller = asyncio.create_task(self._poll_devices())
            try:
                await self._recv(ws)
            finally:
                self._connected = False
                poller.cancel()
                sender.cancel()
                await asyncio.gather(sender, poller, return_exceptions=True)

    async def _poll_devices(self):
        """Actively re-sync so newly installed agents appear without clicking Connect."""
        while True:
            await asyncio.sleep(self.SYNC_INTERVAL_SEC)
            queue = self.outq
            if self._connected and queue is not None:
                try:
                    queue.put_nowait(P.request_devices())
                except Exception:
                    pass

    async def _recv(self, ws):
        async for message in ws:
            if isinstance(message, bytes):
                continue
            msg = P.loads(message)
            kind = msg.get("type")
            if kind == P.DEVICE_LIST:
                self.signals.devices.emit(msg.get("devices", []))
                self.signals.status.emit("online")
            elif kind == P.PREVIEW:
                device_id = msg.get("device_id")
                jpeg_b64 = msg.get("jpeg")
                if device_id and jpeg_b64:
                    try:
                        self.signals.preview.emit(
                            device_id, base64.b64decode(jpeg_b64))
                    except Exception:
                        pass
            elif kind == P.ALERT:
                self.signals.alert.emit(msg)
            elif kind == P.ERROR:
                raise RuntimeError(msg.get("message", "relay error"))

    async def _send(self, ws):
        while True:
            msg = await self.outq.get()
            await ws.send(P.dumps(msg))

    def _disconnected(self):
        self._connected = False
        self.outq = None
        if self._stopping.is_set():
            self.signals.devices.emit([])
        # Keep the last device list on screen during reconnect. Emitting [] on
        # every blip raced with the next DEVICE_LIST and hid newly joined agents.
        self.signals.status.emit("disconnected — reconnecting…")

    def send_json(self, msg: dict):
        queue = self.outq

        def enqueue():
            if self._connected and queue is not None and queue is self.outq:
                queue.put_nowait(msg)

        if self.loop is not None and self._connected:
            try:
                self.loop.call_soon_threadsafe(enqueue)
            except RuntimeError:
                pass

    def remove_device(self, device_id: str):
        self.send_json(P.remove_device(device_id))

    def request_devices(self):
        self.send_json(P.request_devices())


class Net(_Client):
    def __init__(self, url: str, network_key: str, device_id: str, signals: Signals):
        super().__init__(url, network_key, signals)
        self.device_id = device_id
        self.outq = None
        self._connected = False
        self._latest_frame: bytes | None = None
        self._frame_emit_pending = False

    async def _session(self):
        async with websockets.connect(self.url, max_size=None, close_timeout=2) as ws:
            self.outq = asyncio.Queue()
            self._latest_frame = None
            self._frame_emit_pending = False
            await ws.send(P.dumps(P.auth_controller(self.network_key, self.device_id)))
            self.signals.status.emit("connecting…")
            await run_pair(self._recv(ws), self._send(ws))

    def _disconnected(self):
        self._connected = False
        self.outq = None
        self._latest_frame = None
        self._frame_emit_pending = False
        self.signals.peer.emit(False)

    def _flush_frame(self):
        """Emit at most one queued paint with the newest JPEG."""
        self._frame_emit_pending = False
        data = self._latest_frame
        self._latest_frame = None
        if data is not None:
            self.signals.frame.emit(data)

    async def _recv(self, ws):
        async for message in ws:
            if isinstance(message, bytes):
                # Drop stale frames: only the newest JPEG is shown.
                self._latest_frame = message
                if not self._frame_emit_pending:
                    self._frame_emit_pending = True
                    self.loop.call_soon(self._flush_frame)
                continue
            msg = P.loads(message)
            kind = msg.get("type")
            if kind == P.PEER_JOINED:
                self._connected = True
                self.signals.peer.emit(True)
                self.signals.status.emit("connected")
            elif kind == P.PEER_LEFT:
                self._connected = False
                self.signals.peer.emit(False)
                self.signals.status.emit("device offline")
                return
            elif kind == P.ERROR:
                raise RuntimeError(msg.get("message", "relay error"))

    async def _send(self, ws):
        while True:
            msg = await self.outq.get()
            await ws.send(P.dumps(msg))

    def send_json(self, msg: dict):
        # Capture the queue as well as connection state: a delayed GUI callback
        # must not enqueue an old key/button event on a replacement connection.
        queue = self.outq

        def enqueue():
            if self._connected and queue is not None and queue is self.outq:
                queue.put_nowait(msg)

        if self.loop is not None and self._connected:
            try:
                self.loop.call_soon_threadsafe(enqueue)
            except RuntimeError:
                pass


class PreviewFeed:
    """Pull live JPEG frames for one dashboard card via a control session.

    Uses the existing controller role so thumbnails work even when the relay
    does not forward PREVIEW messages. Holds the single controller slot for
    that device until View is opened (pause) or the device goes offline.
    """

    def __init__(self, url: str, network_key: str, device_id: str, card, parent: QObject):
        self.device_id = device_id
        self.card = card
        self.signals = Signals(parent)
        self.net = Net(url, network_key, device_id, self.signals)
        self.signals.frame.connect(self._on_frame, Qt.ConnectionType.QueuedConnection)
        self.signals.peer.connect(self._on_peer, Qt.ConnectionType.QueuedConnection)
        self.net.start()

    def _on_frame(self, data: bytes):
        if self.card is not None:
            self.card.set_preview(data)

    def _on_peer(self, joined: bool):
        if joined:
            # Small, frequent thumbnails — scale is critical for VPS latency.
            self.net.send_json(P.config(fps=4, quality=35, scale=0.3))

    def stop(self):
        self.card = None
        try:
            self.signals.frame.disconnect()
            self.signals.peer.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.net.stop()
