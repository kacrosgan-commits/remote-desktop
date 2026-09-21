import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest


def test_invalid_options_are_rejected_before_installing(tmp_path, monkeypatch):
    from agent import startup
    from agent.main import parse_args

    installer = Mock()
    monkeypatch.setattr(startup, "install", installer)
    monkeypatch.setattr(startup, "install_dir", lambda: tmp_path / "installed")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises((ValueError, SystemExit)):
        startup.prepare(["--fps", "bad"], validate=parse_args)
    installer.assert_not_called()


def test_install_copies_binary_and_preserves_options(tmp_path, monkeypatch):
    from agent import startup

    source = tmp_path / "download" / "agent.exe"
    source.parent.mkdir()
    source.write_bytes(b"test executable")
    destination = tmp_path / "Local AppData" / "RemoteDesk"
    register = Mock()
    monkeypatch.setattr(startup, "register_startup", register)
    monkeypatch.setattr(startup, "install_dir", lambda: destination)
    monkeypatch.setattr(startup, "stop_installed_agent", Mock())
    target, ready = startup.install(source, ["--name", "Office PC"])
    assert ready is True
    assert target.read_bytes() == b"test executable"
    assert json.loads((destination / "arguments.json").read_text()) == ["--name", "Office PC"]
    register.assert_called_once_with(target)


def test_failed_copy_does_not_register_nonexistent_agent(tmp_path, monkeypatch):
    from agent import startup

    register = Mock()
    monkeypatch.setattr(startup, "register_startup", register)
    monkeypatch.setattr(startup, "install_dir", lambda: tmp_path / "installed")
    with pytest.raises(OSError):
        startup.install(tmp_path / "missing.exe", [])
    register.assert_not_called()


def test_running_installed_copy_does_not_copy_onto_itself(tmp_path, monkeypatch):
    from agent import startup

    source = tmp_path / "agent.exe"
    source.write_bytes(b"executable")
    monkeypatch.setattr(startup, "register_startup", Mock())
    monkeypatch.setattr(startup, "install_dir", lambda: tmp_path)
    target, ready = startup.install(source, [])
    assert target == source
    assert ready is True
    assert source.read_bytes() == b"executable"


def test_install_retries_then_succeeds_when_target_unlocks(tmp_path, monkeypatch):
    from agent import startup

    source = tmp_path / "download" / "agent.exe"
    source.parent.mkdir()
    source.write_bytes(b"new")
    destination = tmp_path / "Local AppData" / "RemoteDesk"
    destination.mkdir(parents=True)
    target = destination / "agent.exe"
    target.write_bytes(b"old")
    stop = Mock()
    copies_to_target = {"n": 0}

    real_copy = startup.shutil.copy2

    def flaky_copy(src, dst):
        dst = Path(dst)
        # Staging copy always works.
        if dst.name == "agent.exe.new":
            return real_copy(src, dst)
        if dst.name == "agent.exe":
            copies_to_target["n"] += 1
            if copies_to_target["n"] == 1:
                raise PermissionError("locked")
            return real_copy(src, dst)
        return real_copy(src, dst)

    monkeypatch.setattr(startup, "install_dir", lambda: destination)
    monkeypatch.setattr(startup, "register_startup", Mock())
    monkeypatch.setattr(startup, "stop_installed_agent", stop)
    monkeypatch.setattr(startup.shutil, "copy2", flaky_copy)
    monkeypatch.setattr(startup.time, "sleep", Mock())
    target, ready = startup.install(source, [])
    assert ready is True
    assert target.read_bytes() == b"new"
    assert stop.called
    assert copies_to_target["n"] == 2


def test_install_defers_swap_when_target_stays_locked(tmp_path, monkeypatch):
    from agent import startup

    source = tmp_path / "download" / "agent.exe"
    source.parent.mkdir()
    source.write_bytes(b"new-bytes")
    destination = tmp_path / "Local AppData" / "RemoteDesk"
    destination.mkdir(parents=True)
    target = destination / "agent.exe"
    target.write_bytes(b"old-bytes")

    real_copy = startup.shutil.copy2

    def locked_target(src, dst):
        dst = Path(dst)
        if dst.resolve() == target.resolve():
            raise PermissionError("cannot overwrite running image")
        return real_copy(src, dst)

    monkeypatch.setattr(startup, "install_dir", lambda: destination)
    monkeypatch.setattr(startup, "register_startup", Mock())
    monkeypatch.setattr(startup, "stop_installed_agent", Mock())
    monkeypatch.setattr(startup.shutil, "copy2", locked_target)
    monkeypatch.setattr(startup.time, "sleep", Mock())
    installed, ready = startup.install(source, [])
    assert ready is False
    assert installed == target
    assert (destination / "agent.exe.new").read_bytes() == b"new-bytes"
    assert (destination / "finish-install.cmd").exists()


def test_stop_installed_agent_never_uses_image_name_taskkill(monkeypatch):
    from agent import startup

    calls = []

    def capture(cmd, **kwargs):
        calls.append(cmd)
        return Mock(returncode=0)

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(startup.subprocess, "run", capture)
    startup.stop_installed_agent(Path("C:/Users/Test/AppData/Local/RemoteDesk/agent.exe"))
    assert any("powershell" in c for c in calls)
    assert not any(
        isinstance(c, (list, tuple)) and "taskkill" in c and "/IM" in c
        for c in calls
    )


def test_startup_command_quotes_windows_paths_with_spaces(monkeypatch):
    from agent import startup

    registry = Mock()
    registry.CreateKey.return_value.__enter__ = Mock(return_value="key")
    registry.CreateKey.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(startup, "_register_logon_task", Mock())
    startup.register_startup(Path("C:/Users/Test User/RemoteDesk/agent.exe"))
    assert registry.SetValueEx.call_args.args[-1] == '"C:/Users/Test User/RemoteDesk/agent.exe" --run'
    startup._register_logon_task.assert_called_once()
