"""Watch for crypto-wallet / sensitive apps on the agent PC.

Scans process names and (on Windows) top-level window titles. When a listed
app appears, the agent emits an ALERT for the controller dashboard.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

# Native payment apps. Matched on the process name. Keep lowercase.
# Browsers and LDPlayer are not listed here: opening them is not a payment.
WATCH_PATTERNS: tuple[tuple[str, str], ...] = (
    ("exodus", "Exodus wallet"),
    ("atomic", "Atomic wallet"),
    ("electrum", "Electrum wallet"),
    ("ledger live", "Ledger Live"),
    ("ledger live.exe", "Ledger Live"),
    ("trezor", "Trezor Suite"),
    ("trezorsuite", "Trezor Suite"),
    ("coinbase", "Coinbase"),
    ("binance", "Binance"),
    ("wasabi", "Wasabi wallet"),
    ("sparrow", "Sparrow wallet"),
    ("bitcoin-qt", "Bitcoin Core"),
    ("bitcoin.exe", "Bitcoin Core"),
    ("monero-wallet", "Monero wallet"),
    ("mycelium", "Mycelium"),
    ("trustwallet", "Trust Wallet"),
    ("phantom", "Phantom wallet"),
    ("metamask", "MetaMask"),
    ("brave wallet", "Brave Wallet"),
    ("crypto.com", "Crypto.com"),
    ("cryptocom", "Crypto.com"),
    ("blockchain.exe", "Blockchain.com"),
    ("guarda", "Guarda wallet"),
    ("jaxx", "Jaxx wallet"),
    ("cake wallet", "Cake Wallet"),
    ("exodus wallet", "Exodus wallet"),
    ("stripe", "Stripe"),
    ("paypal", "PayPal"),
    ("square", "Square"),
    ("cash app", "Cash App"),
    ("venmo", "Venmo"),
    ("revolut", "Revolut"),
    ("shopify pos", "Shopify POS"),
)

# Where a payment page or Android app can be showing. Used only to label the
# alert ("in Chrome", "in LDPlayer"). These never alert by themselves.
HOSTS: tuple[tuple[str, str], ...] = (
    ("google chrome", "Chrome"),
    ("microsoft edge", "Edge"),
    ("firefox", "Firefox"),
    ("opera", "Opera"),
    ("brave", "Brave"),
    ("ldplayer", "LDPlayer"),
    ("dnplayer", "LDPlayer"),
)


@dataclass(frozen=True)
class Match:
    key: str
    label: str
    detail: str


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _match_text(text: str) -> Match | None:
    """Payment app only. A bare browser or LDPlayer title does not match."""
    norm = _normalize(text)
    if not norm:
        return None
    for pattern, label in WATCH_PATTERNS:
        if pattern in norm:
            return Match(key=pattern, label=label, detail=text.strip()[:120])
    return None


def _host_label(text: str) -> str | None:
    norm = _normalize(text)
    for pattern, label in HOSTS:
        if pattern in norm:
            return label
    return None


def _match_title(text: str) -> Match | None:
    """Payment service visible in a local window, a browser tab, or LDPlayer."""
    hit = _match_text(text)
    if hit is None:
        return None
    host = _host_label(text)
    if host is None:
        return hit
    return Match(hit.key, f"{hit.label} in {host}", f"in {host}: {text.strip()[:100]}")


def list_process_names() -> list[str]:
    if sys.platform == "win32":
        return _list_process_names_win()
    return _list_process_names_posix()


def _list_process_names_posix() -> list[str]:
    names: list[str] = []
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/comm", "r", encoding="utf-8",
                          errors="ignore") as f:
                    name = f.read().strip()
            except OSError:
                continue
            if name:
                names.append(name)
    except OSError:
        return []
    return names


def _list_process_names_win() -> list[str]:
    names: list[str] = []
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        CreateToolhelp32Snapshot = kernel32.CreateToolhelp32Snapshot
        Process32FirstW = kernel32.Process32FirstW
        Process32NextW = kernel32.Process32NextW
        CloseHandle = kernel32.CloseHandle

        snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == INVALID_HANDLE_VALUE or snap is None:
            return []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            if not Process32FirstW(snap, ctypes.byref(entry)):
                return []
            while True:
                name = entry.szExeFile.strip()
                if name:
                    names.append(name)
                if not Process32NextW(snap, ctypes.byref(entry)):
                    break
        finally:
            CloseHandle(snap)
    except Exception:
        return []
    return names


def list_window_titles() -> list[str]:
    """Best-effort visible window titles (Windows only)."""
    if sys.platform != "win32":
        return []
    titles: list[str] = []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        IsWindowVisible = user32.IsWindowVisible
        GetWindowTextLengthW = user32.GetWindowTextLengthW
        GetWindowTextW = user32.GetWindowTextW

        def callback(hwnd, _lparam):
            if not IsWindowVisible(hwnd):
                return True
            length = GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if title:
                titles.append(title)
            return True

        EnumWindows(EnumWindowsProc(callback), 0)
    except Exception:
        return []
    return titles


def scan_matches() -> list[Match]:
    found: dict[str, Match] = {}
    for name in list_process_names():
        hit = _match_text(name)
        if hit and hit.key not in found:
            found[hit.key] = Match(hit.key, hit.label, f"process: {name}")
    for title in list_window_titles():
        hit = _match_title(title)
        if hit and hit.key not in found:
            found[hit.key] = Match(hit.key, hit.label, hit.detail)
    return list(found.values())
