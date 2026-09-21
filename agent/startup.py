"""Install the packaged Windows agent for the current user's next sign-in."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "RemoteDeskAgent"
_instance_handle = None


def install_dir() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "RemoteDesk"


def register_startup(executable: Path):
    import winreg

    command = subprocess.list2cmdline([str(executable), "--run"])
    if len(command) > 260:
        raise ValueError("The installation path is too long for Windows startup.")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)


def install(source: Path, arguments: list[str]) -> Path:
    destination = install_dir()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "agent.exe"
    if source.resolve() != target.resolve():
        try:
            shutil.copy2(source, target)
        except PermissionError as exc:
            raise RuntimeError(
                "Close the installed RemoteDesk agent before updating it. "
                "Then launch the new agent.exe again.") from exc
    (destination / "arguments.json").write_text(
        json.dumps(arguments), encoding="utf-8")
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    uninstaller = resources / "uninstall-agent.bat"
    if uninstaller.exists() and uninstaller.resolve() != (destination / uninstaller.name).resolve():
        shutil.copy2(uninstaller, destination / uninstaller.name)
    register_startup(target)
    return target


def saved_arguments(directory: Path) -> list[str]:
    try:
        data = json.loads((directory / "arguments.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(data, list) or not all(isinstance(arg, str) for arg in data):
        raise ValueError("Invalid saved agent arguments. Run install-agent.bat again.")
    return data


def notify(message: str, error: bool = False):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, message, "RemoteDesk Agent", 0x10 if error else 0x40)
    elif sys.stderr is not None:
        print(message, file=sys.stderr)


def prepare(arguments: list[str], validate) -> list[str] | None:
    """Return runtime options, or None when an installed child was launched."""
    parser = argparse.ArgumentParser(add_help=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--portable", action="store_true")
    mode.add_argument("--run", action="store_true")
    options, runtime = parser.parse_known_args(arguments)
    if "--help" in runtime or "-h" in runtime:
        return runtime
    packaged_windows = sys.platform == "win32" and getattr(sys, "frozen", False)
    if options.portable or not packaged_windows:
        if options.install:
            raise RuntimeError("Installation requires the packaged Windows agent.exe.")
        return runtime
    source = Path(sys.executable)
    if options.run:
        return saved_arguments(source.parent) + runtime
    if not options.install and source.resolve() == (install_dir() / "agent.exe").resolve():
        return saved_arguments(source.parent) + runtime
    runtime = saved_arguments(install_dir()) + runtime
    # Never persist a typo that would break every subsequent startup.
    validate(runtime)
    target = install(source, runtime)
    environment = os.environ.copy()
    # The installed child outlives this one-file PyInstaller launcher's temp dir.
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen([str(target), "--run"], cwd=target.parent, env=environment)
    notify(
        "RemoteDesk Agent is installed and starting.\n\n"
        "It will start automatically when this Windows user signs in after a restart.\n"
        f"Installed in: {target.parent}\n\n"
        "To remove it, run uninstall-agent.bat in that folder.")
    return None


def acquire_instance() -> bool:
    """Prevent two packaged agents from controlling the same login session."""
    global _instance_handle
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateMutexW(None, False, r"Local\RemoteDeskAgent")
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    if error == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _instance_handle = handle  # Windows closes this handle at process exit.
    return True
