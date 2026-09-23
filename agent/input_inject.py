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
    "ctrl": Key.ctrl, "alt": Key.alt, "shift": Key.shift, "cmd": Key.cmd,
    "caps_lock": Key.caps_lock, "num_lock": Key.num_lock,
    "print_screen": Key.print_screen, "pause": Key.pause, "menu": Key.menu,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4, "f5": Key.f5,
    "f6": Key.f6, "f7": Key.f7, "f8": Key.f8, "f9": Key.f9, "f10": Key.f10,
    "f11": Key.f11, "f12": Key.f12,
}


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
        k = self._resolve_key(msg["name"])
        try:
            if msg["action"] == P.K_DOWN:
                self.keyboard.press(k)
                self._pressed_keys[msg["name"]] = k
            elif msg["action"] == P.K_UP:
                self.keyboard.release(k)
                self._pressed_keys.pop(msg["name"], None)
        except Exception:
            # Unknown / unmappable key: ignore rather than crash the session.
            pass

    def release_all(self):
        """A lost connection must never leave a remote modifier/drag held."""
        for key in reversed(list(self._pressed_keys.values())):
            try:
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
