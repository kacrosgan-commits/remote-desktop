"""Block the LOCAL physical keyboard & mouse on the controlled machine,
while still letting injected (remote-controlled) events through.

This is the feature TeamViewer/AnyDesk call "Block user input".

Windows implementation uses low-level hooks (WH_KEYBOARD_LL / WH_MOUSE_LL).
The hook callback checks the 'injected' flag on each event:
  - injected events (from our own SendInput via pynput) -> pass through
  - physical events, while blocking is on                -> swallowed

Notes / limitations:
  * Ctrl+Alt+Del and the secure desktop CANNOT be blocked without a
    kernel-mode driver. That is a Windows security guarantee.
  * To affect elevated windows the agent should run as Administrator.
  * Linux/macOS backends are stubbed; fill in evdev / CGEventTap later.
"""
from __future__ import annotations
import sys
import threading


class _BaseBlocker:
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def block(self) -> None: ...
    def unblock(self) -> None: ...


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------
class _WindowsBlocker(_BaseBlocker):
    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self._blocking = False
        self._thread: threading.Thread | None = None
        self._thread_id = None
        self._kbd_hook = None
        self._mouse_hook = None
        # keep references so the callbacks aren't garbage-collected
        self._kbd_proc = None
        self._mouse_proc = None

        self.WH_KEYBOARD_LL = 13
        self.WH_MOUSE_LL = 14
        self.HC_ACTION = 0
        self.LLKHF_INJECTED = 0x10
        self.LLMHF_INJECTED = 0x01
        self.WM_QUIT = 0x0012

        ULONG_PTR = wintypes.WPARAM

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("pt", wintypes.POINT),
                ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        self.KBDLLHOOKSTRUCT = KBDLLHOOKSTRUCT
        self.MSLLHOOKSTRUCT = MSLLHOOKSTRUCT
        self.HOOKPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )

        # Signatures
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self.user32.SetWindowsHookExW.restype = wintypes.HHOOK
        self.user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, self.HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD
        ]
        self.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self.user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        ]
        self.user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]

    def _kbd_callback(self, nCode, wParam, lParam):
        if nCode == self.HC_ACTION and self._blocking:
            info = self.ctypes.cast(
                lParam, self.ctypes.POINTER(self.KBDLLHOOKSTRUCT)
            ).contents
            if not (info.flags & self.LLKHF_INJECTED):
                return 1  # swallow physical keystroke
        return self.user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _mouse_callback(self, nCode, wParam, lParam):
        if nCode == self.HC_ACTION and self._blocking:
            info = self.ctypes.cast(
                lParam, self.ctypes.POINTER(self.MSLLHOOKSTRUCT)
            ).contents
            if not (info.flags & self.LLMHF_INJECTED):
                return 1  # swallow physical mouse event
        return self.user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _run(self):
        ctypes = self.ctypes
        self._thread_id = self.kernel32.GetCurrentThreadId()
        h_mod = self.kernel32.GetModuleHandleW(None)

        self._kbd_proc = self.HOOKPROC(self._kbd_callback)
        self._mouse_proc = self.HOOKPROC(self._mouse_callback)

        self._kbd_hook = self.user32.SetWindowsHookExW(
            self.WH_KEYBOARD_LL, self._kbd_proc, h_mod, 0
        )
        self._mouse_hook = self.user32.SetWindowsHookExW(
            self.WH_MOUSE_LL, self._mouse_proc, h_mod, 0
        )

        # Low-level hooks require a message loop on the installing thread.
        msg = self.wintypes.MSG()
        while self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(msg))
            self.user32.DispatchMessageW(ctypes.byref(msg))

        if self._kbd_hook:
            self.user32.UnhookWindowsHookEx(self._kbd_hook)
        if self._mouse_hook:
            self.user32.UnhookWindowsHookEx(self._mouse_hook)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._blocking = False
        if self._thread_id:
            # PostThreadMessage(WM_QUIT) to break the message loop.
            self.user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)

    def block(self):
        self._blocking = True

    def unblock(self):
        self._blocking = False


# ---------------------------------------------------------------------------
# Linux (X11) — stub; wire up python-evdev EVIOCGRAB or Xlib grabs here.
# ---------------------------------------------------------------------------
class _LinuxBlocker(_BaseBlocker):
    def __init__(self):
        print("[InputBlocker] Linux backend not implemented; block is a no-op.",
              file=sys.stderr)

    def start(self): ...
    def stop(self): ...
    def block(self):
        print("[InputBlocker] block() ignored (Linux stub).", file=sys.stderr)
    def unblock(self): ...


class _NoopBlocker(_BaseBlocker):
    def __init__(self):
        print("[InputBlocker] Unsupported OS; block is a no-op.", file=sys.stderr)
    def start(self): ...
    def stop(self): ...
    def block(self): ...
    def unblock(self): ...


def make_input_blocker() -> _BaseBlocker:
    if sys.platform.startswith("win"):
        return _WindowsBlocker()
    if sys.platform.startswith("linux"):
        return _LinuxBlocker()
    return _NoopBlocker()
