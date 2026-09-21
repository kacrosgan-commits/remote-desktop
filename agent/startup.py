"""Install the packaged Windows agent for the current user's next sign-in."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "RemoteDeskAgent"
TASK_NAME = "RemoteDeskAgent"
_instance_handle = None


def install_dir() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "RemoteDesk"


def _startup_command(executable: Path) -> str:
    command = subprocess.list2cmdline([str(executable), "--run"])
    if len(command) > 260:
        raise ValueError("The installation path is too long for Windows startup.")
    return command


def register_startup(executable: Path):
    """Register both HKCU Run and a logon task that restarts if the agent exits."""
    import winreg

    command = _startup_command(executable)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
    _register_logon_task(executable)


def _xml_escape(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _register_logon_task(executable: Path):
    """User-level scheduled task: start at sign-in and restart on failure."""
    if sys.platform != "win32":
        return
    # Ensure the Run-key path is still valid even if task creation fails.
    _startup_command(executable)
    exe_xml = _xml_escape(str(executable))
    work_xml = _xml_escape(str(executable.parent))
    xml = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <RegistrationInfo>
            <Description>RemoteDesk agent — keeps the PC online after sign-in.</Description>
          </RegistrationInfo>
          <Triggers>
            <LogonTrigger>
              <Enabled>true</Enabled>
            </LogonTrigger>
          </Triggers>
          <Principals>
            <Principal id="Author">
              <LogonType>InteractiveToken</LogonType>
              <RunLevel>LeastPrivilege</RunLevel>
            </Principal>
          </Principals>
          <Settings>
            <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
            <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
            <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
            <AllowHardTerminate>true</AllowHardTerminate>
            <StartWhenAvailable>true</StartWhenAvailable>
            <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
            <IdleSettings>
              <StopOnIdleEnd>false</StopOnIdleEnd>
              <RestartOnIdle>false</RestartOnIdle>
            </IdleSettings>
            <AllowStartOnDemand>true</AllowStartOnDemand>
            <Enabled>true</Enabled>
            <Hidden>false</Hidden>
            <RunOnlyIfIdle>false</RunOnlyIfIdle>
            <WakeToRun>false</WakeToRun>
            <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
            <Priority>7</Priority>
            <RestartOnFailure>
              <Interval>PT1M</Interval>
              <Count>999</Count>
            </RestartOnFailure>
          </Settings>
          <Actions Context="Author">
            <Exec>
              <Command>{exe_xml}</Command>
              <Arguments>--run</Arguments>
              <WorkingDirectory>{work_xml}</WorkingDirectory>
            </Exec>
          </Actions>
        </Task>
        """)
    # schtasks /Create /XML requires a UTF-16 LE file on Windows.
    with tempfile.NamedTemporaryFile("wb", suffix=".xml", delete=False) as handle:
        handle.write(xml.encode("utf-16"))
        xml_path = handle.name
    try:
        subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", xml_path, "/F"],
            check=False, capture_output=True, text=True,
        )
    finally:
        try:
            os.unlink(xml_path)
        except OSError:
            pass


def unregister_startup():
    """Best-effort removal of Run key and scheduled task (used by uninstall bat)."""
    if sys.platform != "win32":
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_NAME)
    except OSError:
        pass
    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        check=False, capture_output=True, text=True,
    )


def stop_installed_agent(target: Path):
    """Stop a previously installed agent so its exe can be overwritten on update.

    The agent is often a background process (easy to miss in Task Manager's
    Apps list). The logon task may also relaunch it after a kill, so disable
    the task for the duration of the update.
    """
    if sys.platform != "win32":
        return
    subprocess.run(
        ["schtasks", "/Change", "/TN", TASK_NAME, "/DISABLE"],
        check=False, capture_output=True, text=True,
    )
    subprocess.run(
        ["schtasks", "/End", "/TN", TASK_NAME],
        check=False, capture_output=True, text=True,
    )
    # Broad kill by image name first (covers path/casing mismatches).
    subprocess.run(
        ["taskkill", "/F", "/IM", "agent.exe", "/T"],
        check=False, capture_output=True, text=True,
    )
    target_path = str(target.resolve())
    # Case-insensitive path match; also any agent under %LOCALAPPDATA%\RemoteDesk.
    script = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        f"$target = [System.IO.Path]::GetFullPath({target_path!r}); "
        "$folder = Split-Path -Parent $target; "
        "Get-Process | Where-Object { "
        "  $_.Path -and ("
        "    ([string]::Compare($_.Path, $target, $true) -eq 0) -or "
        "    ($_.Path -like ($folder + '\\*') -and $_.ProcessName -eq 'agent')"
        "  )"
        "} | Stop-Process -Force; "
        "Start-Sleep -Milliseconds 1200"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=False, capture_output=True, text=True,
    )


def _replace_executable(source: Path, target: Path):
    """Copy source onto target, even if Windows still has the old file open.

    Strategy:
      1) stop processes / disable restart task
      2) direct copy
      3) if locked: rename old exe -> agent.exe.old (usually allowed while
         running on Windows), then copy the new binary into place
    """
    stale = target.with_name(target.name + ".old")
    last_error = None
    for attempt in range(6):
        stop_installed_agent(target)
        # Drop leftovers from a previous interrupted update.
        try:
            if stale.exists():
                stale.unlink()
        except OSError:
            pass
        try:
            shutil.copy2(source, target)
            return
        except PermissionError as exc:
            last_error = exc
        # Rename-away the locked binary, then write the new one beside it.
        try:
            if target.exists():
                if stale.exists():
                    try:
                        stale.unlink()
                    except OSError:
                        stale = target.with_name(f"{target.name}.{attempt}.old")
                target.rename(stale)
            shutil.copy2(source, target)
            # Best-effort cleanup; the old process may still hold .old open.
            try:
                if stale.exists():
                    stale.unlink()
            except OSError:
                pass
            return
        except OSError as exc:
            last_error = exc
    raise RuntimeError(
        "Could not update the installed RemoteDesk agent.\n\n"
        "Windows still has the old file locked (background agent, scheduled "
        "task, or antivirus).\n\n"
        "Fix:\n"
        "1. Open Task Manager → Details tab → end every \"agent.exe\".\n"
        "2. Or run:  %LOCALAPPDATA%\\RemoteDesk\\uninstall-agent.bat\n"
        "3. Then double-click the new agent.exe again.\n\n"
        "If it still fails, temporarily pause Windows Defender real-time "
        "protection and retry."
    ) from last_error


def install(source: Path, arguments: list[str]) -> Path:
    destination = install_dir()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "agent.exe"
    if source.resolve() != target.resolve():
        _replace_executable(source, target)
    (destination / "arguments.json").write_text(
        json.dumps(arguments), encoding="utf-8")
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    uninstaller = resources / "uninstall-agent.bat"
    if uninstaller.exists() and uninstaller.resolve() != (destination / uninstaller.name).resolve():
        shutil.copy2(uninstaller, destination / uninstaller.name)
    # Re-enable / recreate startup (task was disabled during the update).
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
        # Clean leftovers from an in-place update while the old process was alive.
        try:
            stale = source.with_name(source.name + ".old")
            if stale.exists():
                stale.unlink()
        except OSError:
            pass
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
        "It will start automatically when this Windows user signs in after a restart,\n"
        "and will restart itself if it stops unexpectedly.\n"
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
