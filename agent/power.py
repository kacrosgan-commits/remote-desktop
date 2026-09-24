"""Keep the agent PC controllable while Windows would otherwise sleep.

A fully powered-off PC cannot run the agent. While the agent is running it
asks Windows to stay out of sleep. When a controller connects, the monitor
is turned back on so the session is visible.
"""
from __future__ import annotations

import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040


def _set_state(flags: int) -> None:
    if sys.platform != "win32":
        return
    import ctypes
    ctypes.windll.kernel32.SetThreadExecutionState(flags)


def stay_awake() -> None:
    """Block system sleep for as long as this agent process runs."""
    _set_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED)


def wake_display() -> None:
    """Turn the monitor on and keep the system awake for a remote session."""
    _set_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED | ES_AWAYMODE_REQUIRED)
    if sys.platform != "win32":
        return
    import ctypes
    HWND_BROADCAST = 0xFFFF
    WM_SYSCOMMAND = 0x0112
    SC_MONITORPOWER = 0xF170
    ctypes.windll.user32.SendNotifyMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, -1)


def allow_display_sleep() -> None:
    """Let the monitor sleep again, but keep the PC itself awake."""
    stay_awake()


def release() -> None:
    """Allow normal sleep after the agent exits."""
    _set_state(ES_CONTINUOUS)
