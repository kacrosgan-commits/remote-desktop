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
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import branding  # noqa: E402

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = branding.RUN_VALUE
TASK_NAME = branding.TASK_NAME
_instance_handle = None


def install_dir() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / branding.INSTALL_DIRNAME


def legacy_install_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / branding.LEGACY_INSTALL_DIRNAME


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
        try:
            winreg.DeleteValue(key, branding.LEGACY_RUN_VALUE)
        except OSError:
            pass
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
    subprocess.run(
        ["schtasks", "/Delete", "/TN", branding.LEGACY_TASK_NAME, "/F"],
        check=False, capture_output=True, text=True,
    )
    exe_xml = _xml_escape(str(executable))
    work_xml = _xml_escape(str(executable.parent))
    xml = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <RegistrationInfo>
            <Description>{branding.DISPLAY_NAME} agent — keeps the PC online after sign-in.</Description>
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
            for name in (RUN_NAME, branding.LEGACY_RUN_VALUE):
                try:
                    winreg.DeleteValue(key, name)
                except OSError:
                    pass
    except OSError:
        pass
    for task in (TASK_NAME, branding.LEGACY_TASK_NAME):
        subprocess.run(
            ["schtasks", "/Delete", "/TN", task, "/F"],
            check=False, capture_output=True, text=True,
        )


def stop_installed_agent(target: Path):
    """Stop only the *installed* agent — never kill this installer by image name.

    Earlier builds used `taskkill /IM agent.exe`, which also killed the
    installer process in Downloads/Documents (same filename) and aborted the
    update. Match by full path under the install folder, and skip our PID.
    """
    if sys.platform != "win32":
        return
    for task in (TASK_NAME, branding.LEGACY_TASK_NAME):
        subprocess.run(
            ["schtasks", "/Change", "/TN", task, "/DISABLE"],
            check=False, capture_output=True, text=True,
        )
        subprocess.run(
            ["schtasks", "/End", "/TN", task],
            check=False, capture_output=True, text=True,
        )
    target_path = str(target.resolve())
    folder = str(target.resolve().parent)
    my_pid = os.getpid()
    script = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        f"$target = [System.IO.Path]::GetFullPath({target_path!r}); "
        f"$folder = [System.IO.Path]::GetFullPath({folder!r}); "
        f"$me = {my_pid}; "
        "Get-CimInstance Win32_Process -Filter \"Name='agent.exe'\" | ForEach-Object { "
        "  if ($_.ProcessId -eq $me) { return }; "
        "  $path = $_.ExecutablePath; "
        "  if (-not $path) { return }; "
        "  $full = [System.IO.Path]::GetFullPath($path); "
        "  if (([string]::Compare($full, $target, $true) -eq 0) -or "
        "      $full.StartsWith($folder + [IO.Path]::DirectorySeparatorChar, "
        "                       [StringComparison]::OrdinalIgnoreCase)) { "
        "    Stop-Process -Id $_.ProcessId -Force "
        "  } "
        "}; "
        "Start-Sleep -Milliseconds 800"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=False, capture_output=True, text=True,
    )


def _write_finish_script(destination: Path, target: Path) -> Path:
    """Batch file that swaps agent.exe.new into place after the installer exits."""
    script = destination / "finish-install.cmd"
    # Only touch the installed binary path — never taskkill by image name alone.
    content = textwrap.dedent(f"""\
        @echo off
        setlocal
        cd /d "%~dp0"
        schtasks /Change /TN "{TASK_NAME}" /DISABLE >nul 2>&1
        schtasks /End /TN "{TASK_NAME}" >nul 2>&1
        powershell -NoProfile -Command ^
          "$ErrorActionPreference='SilentlyContinue';" ^
          "$t=[IO.Path]::GetFullPath('%cd%\\agent.exe');" ^
          "Get-CimInstance Win32_Process -Filter \\"Name='agent.exe'\\" | ForEach-Object {{" ^
          "  $p=$_.ExecutablePath; if(-not $p){{return}};" ^
          "  if([string]::Compare([IO.Path]::GetFullPath($p),$t,$true) -eq 0)" ^
          "  {{ Stop-Process -Id $_.ProcessId -Force }}" ^
          "}}"
        timeout /t 2 /nobreak >nul
        if exist "agent.exe.old" del /f /q "agent.exe.old" >nul 2>&1
        if exist "agent.exe" ren "agent.exe" "agent.exe.old" >nul 2>&1
        if exist "agent.exe" del /f /q "agent.exe" >nul 2>&1
        if exist "agent.exe.new" (
          move /y "agent.exe.new" "agent.exe" >nul
        )
        if exist "agent.exe.old" del /f /q "agent.exe.old" >nul 2>&1
        schtasks /Change /TN "{TASK_NAME}" /ENABLE >nul 2>&1
        if exist "agent.exe" (
          start "" "agent.exe" --run
        )
        del "%~f0" >nul 2>&1
        """)
    script.write_text(content, encoding="utf-8")
    return script


def _replace_executable(source: Path, target: Path) -> bool:
    """Place the new binary. Returns True if agent.exe is ready; False if a
    finish-install.cmd must complete the swap after this process exits.

    Always stages to agent.exe.new first so a locked agent.exe cannot block
    writing the update payload.
    """
    destination = target.parent
    staging = destination / "agent.exe.new"
    shutil.copy2(source, staging)

    stop_installed_agent(target)

    # Fast path: overwrite in place when the file is not locked.
    for _ in range(3):
        try:
            shutil.copy2(staging, target)
            try:
                staging.unlink()
            except OSError:
                pass
            return True
        except PermissionError:
            time.sleep(0.6)
            stop_installed_agent(target)

    # Slow path: installer exits, then finish-install.cmd swaps the file.
    _write_finish_script(destination, target)
    return False


def install(source: Path, arguments: list[str]) -> tuple[Path, bool]:
    """Install files and startup entries.

    Returns (target_exe, ready). When ready is False, the caller must launch
    finish-install.cmd instead of starting agent.exe directly.
    """
    # Stop a leftover agent from the previous RemoteDesk install folder.
    legacy = legacy_install_dir() / "agent.exe"
    if legacy.exists():
        stop_installed_agent(legacy)
    destination = install_dir()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "agent.exe"
    ready = True
    if source.resolve() != target.resolve():
        ready = _replace_executable(source, target)
    (destination / "arguments.json").write_text(
        json.dumps(arguments), encoding="utf-8")
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    uninstaller = resources / "uninstall-agent.bat"
    if uninstaller.exists() and uninstaller.resolve() != (destination / uninstaller.name).resolve():
        shutil.copy2(uninstaller, destination / uninstaller.name)
    # Recreate startup (task may have been disabled during the update).
    register_startup(target)
    return target, ready


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
            None, message, f"{branding.DISPLAY_NAME} Agent",
            0x10 if error else 0x40)
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
        for name in (source.name + ".old", source.name + ".new", "finish-install.cmd"):
            try:
                stale = source.parent / name
                if stale.exists() and stale.suffix in {".old", ".new"}:
                    stale.unlink()
            except OSError:
                pass
        return saved_arguments(source.parent) + runtime
    if not options.install and source.resolve() == (install_dir() / "agent.exe").resolve():
        return saved_arguments(source.parent) + runtime
    saved = saved_arguments(install_dir()) or saved_arguments(legacy_install_dir())
    runtime = saved + runtime
    # Never persist a typo that would break every subsequent startup.
    validate(runtime)
    target, ready = install(source, runtime)
    environment = os.environ.copy()
    # The installed child outlives this one-file PyInstaller launcher's temp dir.
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if ready:
        subprocess.Popen([str(target), "--run"], cwd=target.parent, env=environment)
    else:
        finish = target.parent / "finish-install.cmd"
        # Detached so this installer can exit before the swap touches agent.exe.
        subprocess.Popen(
            ["cmd.exe", "/c", str(finish)],
            cwd=target.parent,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0),
            close_fds=True,
        )
    # No success MessageBox — agent installs/starts silently in the background.
    # Failures still show via notify(..., error=True) from agent.main.
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
    handle = kernel32.CreateMutexW(None, False, branding.MUTEX_NAME)
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    if error == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _instance_handle = handle  # Windows closes this handle at process exit.
    return True
