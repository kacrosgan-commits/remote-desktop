"""Clipboard and file drop on the agent PC.

Text is placed on the clipboard and pasted with Ctrl+V.
Files are saved under Desktop/RemoteDragon (or Downloads) and, on Windows,
placed on the clipboard so Ctrl+V drops them into the focused window.
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import protocol as P

MAX_TEXT_CHARS = 200_000
MAX_FILE_BYTES = 32 * 1024 * 1024

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_filename(name: str) -> str | None:
    raw = str(name or "").replace("\\", "/").replace("\x00", "")
    base = raw.split("/")[-1]
    base = _SAFE_NAME.sub("_", base).strip(" .")
    if not base or base in {".", ".."}:
        return None
    return base[:120]


def drop_dir() -> Path:
    desktop = Path.home() / "Desktop"
    root = desktop if desktop.is_dir() else Path.home() / "Downloads"
    folder = root / "RemoteDragon"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_drop(name: str, data: bytes) -> Path:
    safe = safe_filename(name)
    if safe is None:
        raise ValueError("invalid file name")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("file is too large")
    folder = drop_dir().resolve()
    dest = (folder / safe).resolve()
    if dest.parent != folder:
        raise ValueError("invalid file path")
    dest.write_bytes(data)
    return dest


def set_clipboard_text(text: str) -> bool:
    text = text[:MAX_TEXT_CHARS]
    if sys.platform == "win32":
        return _win_set_text(text)
    return _xclip_set(text, "text/plain")


def set_clipboard_files(paths: list[Path]) -> bool:
    if sys.platform != "win32" or not paths:
        return False
    return _win_set_files(paths)


def paste_text(injector, text: str) -> bool:
    try:
        if not text:
            return False
        if not set_clipboard_text(str(text)):
            return False
        _chord_paste(injector)
        return True
    except Exception:
        return False


def paste_file(injector, path: Path) -> bool:
    try:
        if set_clipboard_files([path]):
            _chord_paste(injector)
        return True
    except Exception:
        return False


def _chord_paste(injector):
    for action, name in (
        (P.K_DOWN, "ctrl"),
        (P.K_DOWN, "v"),
        (P.K_UP, "v"),
        (P.K_UP, "ctrl"),
    ):
        injector.handle_key(P.key(action, name))


class FileTransfer:
    """Reassemble one controller → agent file."""

    def __init__(self, name: str, size: int):
        self.name = name
        self.size = size
        self._buf = bytearray()

    def add(self, data: bytes) -> str | None:
        if len(self._buf) + len(data) > self.size or len(self._buf) + len(data) > MAX_FILE_BYTES:
            return "file is too large"
        self._buf.extend(data)
        return None

    def finish(self) -> bytes | str:
        if len(self._buf) != self.size:
            return "file was truncated"
        return bytes(self._buf)


class FileInbox:
    def __init__(self):
        self._open: dict[str, FileTransfer] = {}

    def begin(self, transfer_id: str, name: str, size: int) -> str | None:
        safe = safe_filename(name)
        if not transfer_id or safe is None:
            return "invalid file"
        if not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES:
            return "file is too large"
        self._open[transfer_id] = FileTransfer(safe, size)
        return None

    def chunk(self, transfer_id: str, data_b64: str) -> str | None:
        transfer = self._open.get(transfer_id)
        if transfer is None:
            return "unknown file transfer"
        try:
            data = base64.b64decode(data_b64, validate=True)
        except Exception:
            return "bad file data"
        return transfer.add(data)

    def finish(self, transfer_id: str) -> Path | str:
        transfer = self._open.pop(transfer_id, None)
        if transfer is None:
            return "unknown file transfer"
        data = transfer.finish()
        if isinstance(data, str):
            return data
        try:
            return write_drop(transfer.name, data)
        except Exception as exc:
            return str(exc)


def _xclip_set(payload: str, target: str) -> bool:
    import subprocess
    try:
        subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", target],
            input=payload.encode("utf-8"),
            check=True, capture_output=True,
        )
        return True
    except Exception:
        return False


def _win_clipboard():
    """64-bit-safe clipboard APIs.

    The default ctypes return type is a 32-bit int. On 64-bit Windows that
    truncates HGLOBAL pointers, and the next write hits a tiny address such
    as 0x20 (access violation) and kills the agent session.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    return user32, kernel32


def _win_set_text(text: str) -> bool:
    import ctypes
    user32, kernel32 = _win_clipboard()
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    data = text.encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        return False
    handle = None
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            handle = None
            return False
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            handle = None
            return False
        handle = None  # system owns it after a successful SetClipboardData
        return True
    except Exception:
        if handle:
            kernel32.GlobalFree(handle)
        return False
    finally:
        user32.CloseClipboard()


def _win_set_files(paths: list[Path]) -> bool:
    import ctypes
    import struct
    user32, kernel32 = _win_clipboard()
    CF_HDROP = 15
    GMEM_MOVEABLE = 0x0002
    wide = ("\0".join(str(p) for p in paths) + "\0\0").encode("utf-16-le")
    header = struct.pack("=IiiiI", 20, 0, 0, 0, 1)
    blob = header + wide
    if not user32.OpenClipboard(None):
        return False
    handle = None
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(blob))
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            handle = None
            return False
        ctypes.memmove(ptr, blob, len(blob))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_HDROP, handle):
            kernel32.GlobalFree(handle)
            handle = None
            return False
        handle = None
        return True
    except Exception:
        if handle:
            kernel32.GlobalFree(handle)
        return False
    finally:
        user32.CloseClipboard()
