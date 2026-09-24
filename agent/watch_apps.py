"""Watch for crypto-wallet and card apps on the agent PC.

Matches native process names, browser and LDPlayer window titles (including
child windows), and the Android app in the foreground inside LDPlayer.
Opening Chrome or LDPlayer alone does not alert.
"""
from __future__ import annotations

import os
import re
import subprocess
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
    ("jeton", "Jeton card"),
    ("redotpay", "RedotPay"),
    ("redot pay", "RedotPay"),
    ("credit card", "Card payment"),
    ("debit card", "Card payment"),
    ("card payment", "Card payment"),
    ("crypto wallet", "Crypto wallet"),
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

# Android package fragments. Used only for the app LDPlayer is showing.
ANDROID_PACKAGES: tuple[tuple[str, str], ...] = (
    ("exodus", "Exodus wallet"),
    ("io.metamask", "MetaMask"),
    ("trustapp", "Trust Wallet"),
    ("com.coinbase", "Coinbase"),
    ("com.binance", "Binance"),
    ("com.paypal", "PayPal"),
    ("com.venmo", "Venmo"),
    ("squareup.cash", "Cash App"),
    ("com.revolut", "Revolut"),
    ("org.electrum", "Electrum wallet"),
    ("com.mycelium", "Mycelium"),
    ("com.ledger.live", "Ledger Live"),
    ("atomicwallet", "Atomic wallet"),
    ("phantom", "Phantom wallet"),
    ("com.crypto.multiwallet", "Crypto wallet"),
    ("jeton", "Jeton card"),
    ("redotpay", "RedotPay"),
    ("redot.pay", "RedotPay"),
)

_FOCUS_RE = re.compile(r"([A-Za-z][\w]*(?:\.[\w]+)+)/")


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
        def collect(hwnd):
            length = GetWindowTextLengthW(hwnd)
            if length <= 0:
                return
            buf = ctypes.create_unicode_buffer(length + 1)
            GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if title:
                titles.append(title)

        def callback(hwnd, _lparam):
            if IsWindowVisible(hwnd):
                collect(hwnd)
                # Child titles catch a payment page in Chrome and an app inside LDPlayer.
                EnumChildWindows(hwnd, EnumWindowsProc(child_callback), 0)
            return True

        def child_callback(hwnd, _lparam):
            collect(hwnd)
            return True

        EnumWindows = user32.EnumWindows
        EnumChildWindows = user32.EnumChildWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        IsWindowVisible = user32.IsWindowVisible
        GetWindowTextLengthW = user32.GetWindowTextLengthW
        GetWindowTextW = user32.GetWindowTextW

        EnumWindows(EnumWindowsProc(callback), 0)
    except Exception:
        return []
    return titles


def _match_android(package: str) -> Match | None:
    norm = _normalize(package)
    if not norm:
        return None
    for pattern, label in ANDROID_PACKAGES:
        if pattern in norm:
            return Match(
                key=f"android:{pattern}",
                label=f"{label} in LDPlayer",
                detail=f"in LDPlayer: {package.strip()[:100]}",
            )
    return None


def packages_from_dumpsys(text: str) -> list[str]:
    """Package names from LDPlayer `dumpsys window` focus lines."""
    found: list[str] = []
    for line in text.splitlines():
        low = line.lower()
        if "mcurrentfocus" not in low and "mfocusedapp" not in low and "resumedactivity" not in low:
            continue
        for pkg in _FOCUS_RE.findall(line):
            if pkg not in found:
                found.append(pkg)
    return found


def running_ldplayer_indexes(list2_text: str) -> list[str]:
    indexes: list[str] = []
    for line in list2_text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 5 and parts[0].isdigit() and parts[4] == "1":
            indexes.append(parts[0])
    return indexes


def _ldplayer_running(names: list[str]) -> bool:
    for name in names:
        low = name.lower()
        if "ldplayer" in low or "dnplayer" in low:
            return True
    return False


def list_ldplayer_packages() -> list[str]:
    """Foreground Android packages inside running LDPlayer instances."""
    if sys.platform != "win32":
        return []
    console = _find_ldconsole()
    if not console:
        return []
    try:
        listing = _run_ld([console, "list2"])
        indexes = running_ldplayer_indexes(listing)
        packages: list[str] = []
        for index in indexes:
            dump = _run_ld([
                console, "adb", "--index", index, "--command",
                "shell dumpsys window",
            ])
            for pkg in packages_from_dumpsys(dump):
                if pkg not in packages:
                    packages.append(pkg)
        return packages
    except Exception:
        return []


def _run_ld(argv: list[str]) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=5,
        creationflags=flags)
    return result.stdout or ""


def _find_ldconsole() -> str | None:
    names = ("ldconsole.exe", "dnconsole.exe")
    roots = [
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
        r"C:\LDPlayer",
        r"D:\LDPlayer",
    ]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        try:
            for entry in os.listdir(root):
                folder = os.path.join(root, entry)
                if not os.path.isdir(folder):
                    continue
                for name in names:
                    path = os.path.join(folder, name)
                    if os.path.isfile(path):
                        return path
        except OSError:
            continue
    return None


def scan_matches() -> list[Match]:
    found: dict[str, Match] = {}
    names = list_process_names()
    for name in names:
        hit = _match_text(name)
        if hit and hit.key not in found:
            found[hit.key] = Match(hit.key, hit.label, f"process: {name}")
    for title in list_window_titles():
        hit = _match_title(title)
        if hit and hit.key not in found:
            found[hit.key] = Match(hit.key, hit.label, hit.detail)
    if _ldplayer_running(names):
        for package in list_ldplayer_packages():
            hit = _match_android(package)
            if hit and hit.key not in found:
                found[hit.key] = hit
    return list(found.values())
