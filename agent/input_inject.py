"""Inject mouse & keyboard events on the controlled machine using pynput.

Injected events carry the OS 'injected' flag, which is exactly what lets
the InputBlocker distinguish them from the physical user's input.
"""
from pynput.mouse import Controller as MouseController, Button
from pynput.keyboard import Controller as KeyboardController, Key

import protocol as P

_BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}

_SPECIAL = {
    "enter": Key.enter, "esc": Key.esc, "tab": Key.tab,
    "backspace": Key.backspace, "space": Key.space, "delete": Key.delete,
    "insert": Key.insert, "home": Key.home, "end": Key.end,
    "page_up": Key.page_up, "page_down": Key.page_down,
    "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    # Left-hand keys. Generic VK_SHIFT / VK_CONTROL do not apply on Windows.
    "ctrl": Key.ctrl, "ctrl_l": Key.ctrl, "ctrl_r": Key.ctrl,
    "alt": Key.alt, "alt_l": Key.alt, "alt_r": Key.alt,
    "shift": Key.shift, "shift_l": Key.shift, "shift_r": Key.shift,
    "cmd": Key.cmd, "cmd_l": Key.cmd, "cmd_r": Key.cmd,
    "caps_lock": Key.caps_lock, "num_lock": Key.num_lock,
    "print_screen": Key.print_screen, "pause": Key.pause, "menu": Key.menu,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4, "f5": Key.f5,
    "f6": Key.f6, "f7": Key.f7, "f8": Key.f8, "f9": Key.f9, "f10": Key.f10,
    "f11": Key.f11, "f12": Key.f12,
}

# Windows virtual keys. Generic SHIFT/CONTROL/MENU are ignored by most apps.
_MODIFIER_VK = {
    "shift": 0xA0, "shift_l": 0xA0, "shift_r": 0xA1,
    "ctrl": 0xA2, "ctrl_l": 0xA2, "ctrl_r": 0xA3,
    "alt": 0xA4, "alt_l": 0xA4, "alt_r": 0xA5,
    "cmd": 0x5B, "cmd_l": 0x5B, "cmd_r": 0x5C,
}
_EXTENDED_VK = {0xA3, 0xA5, 0x5C}


def _send_modifier(name: str, down: bool) -> bool:
    """Press or release a modifier with the left/right virtual key Windows honors.

    Returns False when this platform should use pynput instead.
    """
    import sys
    if sys.platform != "win32":
        return False
    vk = _MODIFIER_VK.get(name)
    if vk is None:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002
        INPUT_KEYBOARD = 1

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]

        user32 = ctypes.windll.user32
        flags = 0 if down else KEYEVENTF_KEYUP
        if vk in _EXTENDED_VK:
            flags |= KEYEVENTF_EXTENDEDKEY
        event = INPUT()
        event.type = INPUT_KEYBOARD
        event.u.ki.wVk = vk
        event.u.ki.wScan = user32.MapVirtualKeyW(vk, 0)
        event.u.ki.dwFlags = flags
        return user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) == 1
    except Exception:
        return False


class InputInjector:
    def __init__(self, screen_left: int, screen_top: int,
                 screen_width: int, screen_height: int):
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.left = screen_left
        self.top = screen_top
        self.w = max(1, screen_width)
        self.h = max(1, screen_height)
        self._pressed_keys = {}
        self._pressed_buttons = set()

    def set_geometry(self, left: int, top: int, width: int, height: int):
        """Retarget clicks when the captured display changes (e.g. monitor 2)."""
        self.left = left
        self.top = top
        self.w = max(1, width)
        self.h = max(1, height)

    def _to_pixels(self, x: float, y: float) -> tuple[int, int]:
        px = self.left + max(0, min(self.w - 1, int(round(x * (self.w - 1)))))
        py = self.top + max(0, min(self.h - 1, int(round(y * (self.h - 1)))))
        return px, py

    def _resolve_key(self, name: str):
        if name in _SPECIAL:
            return _SPECIAL[name]
        return name  # single printable character

    def handle_mouse(self, msg: dict):
        action = msg["action"]
        if action == P.M_MOVE:
            self.mouse.position = self._to_pixels(msg["x"], msg["y"])
        elif action in (P.M_DOWN, P.M_UP):
            self.mouse.position = self._to_pixels(msg["x"], msg["y"])
            btn = _BUTTONS.get(msg.get("button", "left"), Button.left)
            if action == P.M_DOWN:
                self.mouse.press(btn)
                self._pressed_buttons.add(btn)
            else:
                self.mouse.release(btn)
                self._pressed_buttons.discard(btn)
        elif action == P.M_SCROLL:
            self.mouse.position = self._to_pixels(msg["x"], msg["y"])
            self.mouse.scroll(msg.get("dx", 0), msg.get("dy", 0))

    def handle_key(self, msg: dict):
        name = msg["name"]
        down = msg["action"] == P.K_DOWN
        if name in _MODIFIER_VK and _send_modifier(name, down):
            if down:
                self._pressed_keys[name] = name
            else:
                self._pressed_keys.pop(name, None)
            return
        k = self._resolve_key(name)
        try:
            if down:
                self.keyboard.press(k)
                self._pressed_keys[name] = k
            elif msg["action"] == P.K_UP:
                self.keyboard.release(k)
                self._pressed_keys.pop(name, None)
        except Exception:
            # Unknown / unmappable key: ignore rather than crash the session.
            pass

    def release_all(self):
        """A lost connection must never leave a remote modifier/drag held."""
        for name, key in reversed(list(self._pressed_keys.items())):
            try:
                if name in _MODIFIER_VK and _send_modifier(name, False):
                    continue
                self.keyboard.release(key)
            except Exception:
                pass
        for button in self._pressed_buttons:
            try:
                self.mouse.release(button)
            except Exception:
                pass
        self._pressed_keys.clear()
        self._pressed_buttons.clear()
