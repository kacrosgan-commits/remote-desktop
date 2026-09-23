"""Clipboard text and file drop from the controller to the agent."""
import base64

from PySide6.QtCore import QEvent, Qt

import protocol as P
from agent.clipboard_io import FileInbox, safe_filename
from tests.test_input import key_event, make_view


def test_safe_filename_strips_directories():
    assert safe_filename(r"..\..\windows\system32\evil.exe") == "evil.exe"
    assert safe_filename("notes.txt") == "notes.txt"
    assert safe_filename("") is None


def test_file_inbox_writes_only_the_drop_folder(tmp_path, monkeypatch):
    from agent import clipboard_io
    monkeypatch.setattr(clipboard_io, "drop_dir", lambda: tmp_path)
    inbox = FileInbox()
    payload = b"hello remote"
    assert inbox.begin("t1", r"C:\temp\note.txt", len(payload)) is None
    assert inbox.chunk("t1", base64.b64encode(payload).decode()) is None
    dest = inbox.finish("t1")
    assert dest == tmp_path / "note.txt"
    assert dest.read_bytes() == payload


def test_ctrl_v_requests_paste_instead_of_typing_v(app):
    view, messages = make_view()
    hits = []
    view.paste_requested.connect(lambda: hits.append(True))
    view.keyPressEvent(key_event(
        QEvent.KeyPress, Qt.Key_V, "\x16", Qt.ControlModifier))
    assert hits == [True]
    assert all(msg.get("name") != "v" for msg in messages)
    assert P.clipboard("hi")["type"] == P.CLIPBOARD
