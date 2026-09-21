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
    target = startup.install(source, ["--name", "Office PC"])
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
    assert startup.install(source, []) == source
    assert source.read_bytes() == b"executable"


def test_install_stops_running_agent_before_copy(tmp_path, monkeypatch):
    from agent import startup

    source = tmp_path / "download" / "agent.exe"
    source.parent.mkdir()
    source.write_bytes(b"new")
    destination = tmp_path / "Local AppData" / "RemoteDesk"
    destination.mkdir(parents=True)
    target = destination / "agent.exe"
    target.write_bytes(b"old")
    stop = Mock()
    copies = {"n": 0}

    def flaky_copy(src, dst):
        if Path(dst).name != "agent.exe":
            return
        copies["n"] += 1
        if copies["n"] == 1:
            raise PermissionError("locked")
        Path(dst).write_bytes(Path(src).read_bytes())

    monkeypatch.setattr(startup, "install_dir", lambda: destination)
    monkeypatch.setattr(startup, "register_startup", Mock())
    monkeypatch.setattr(startup, "stop_installed_agent", stop)
    monkeypatch.setattr(startup.shutil, "copy2", flaky_copy)
    assert startup.install(source, []).read_bytes() == b"new"
    assert stop.called
    assert copies["n"] == 2


def test_install_renames_locked_binary_then_replaces(tmp_path, monkeypatch):
    from agent import startup

    source = tmp_path / "download" / "agent.exe"
    source.parent.mkdir()
    source.write_bytes(b"new-bytes")
    destination = tmp_path / "Local AppData" / "RemoteDesk"
    destination.mkdir(parents=True)
    target = destination / "agent.exe"
    target.write_bytes(b"old-bytes")

    def always_locked_onto_agent(src, dst):
        if Path(dst).resolve() == target.resolve() and target.exists():
            raise PermissionError("cannot overwrite running image")
        Path(dst).write_bytes(Path(src).read_bytes())

    monkeypatch.setattr(startup, "install_dir", lambda: destination)
    monkeypatch.setattr(startup, "register_startup", Mock())
    monkeypatch.setattr(startup, "stop_installed_agent", Mock())
    monkeypatch.setattr(startup.shutil, "copy2", always_locked_onto_agent)
    installed = startup.install(source, [])
    assert installed.read_bytes() == b"new-bytes"
    assert not (destination / "agent.exe.old").exists()


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

