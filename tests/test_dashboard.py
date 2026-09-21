from unittest.mock import Mock

from PySide6.QtWidgets import QMessageBox

from controller import main


def test_connect_reuses_dashboard_connection_and_does_not_open_session(app, monkeypatch):
    monkeypatch.setattr(main.store, "load", lambda: ("ws://localhost:8000/ws", "test"))
    monkeypatch.setattr(main.store, "load_hidden", lambda: set())
    monkeypatch.setattr(main.store, "save", Mock())
    monkeypatch.setattr(main, "PreviewFeed", Mock())
    client = Mock()
    monkeypatch.setattr(main, "ConsoleNet", client)
    on_connect = Mock()
    dashboard = main.Dashboard(on_connect)
    dashboard._update_devices([{"id": "pc", "name": "PC", "online": True}])
    dashboard.connect_btn.click()
    client.assert_called_once()
    client.return_value.reconnect.assert_called_once()
    on_connect.assert_not_called()
    assert not hasattr(dashboard, "refresh_btn")
    dashboard.shutdown_previews()
    dashboard.close()


def test_unsaved_connection_edits_do_not_change_selected_device_network(app, monkeypatch):
    monkeypatch.setattr(main.store, "load", lambda: ("ws://localhost:8000/ws", "original"))
    monkeypatch.setattr(main.store, "load_hidden", lambda: set())
    monkeypatch.setattr(main.store, "save", Mock())
    monkeypatch.setattr(main, "PreviewFeed", Mock())
    monkeypatch.setattr(main, "ConsoleNet", Mock())
    on_connect = Mock()
    dashboard = main.Dashboard(on_connect)
    device = {"id": "pc", "name": "PC", "online": True}
    dashboard._update_devices([device])
    dashboard.key.setText("unsaved change")
    dashboard._connect_selected(dashboard.list.item(0))
    on_connect.assert_called_once_with("ws://localhost:8000/ws", "original", device)
    dashboard.shutdown_previews()
    dashboard.close()


def test_dashboard_shows_cards_and_view_opens_online_device(app, monkeypatch):
    monkeypatch.setattr(main.store, "load", lambda: ("ws://localhost:8000/ws", "key"))
    monkeypatch.setattr(main.store, "load_hidden", lambda: set())
    monkeypatch.setattr(main.store, "save", Mock())
    monkeypatch.setattr(main, "PreviewFeed", Mock())
    monkeypatch.setattr(main, "ConsoleNet", Mock())
    on_connect = Mock()
    dashboard = main.Dashboard(on_connect)
    online = {"id": "a", "name": "Alpha", "online": True}
    offline = {"id": "b", "name": "Beta", "online": False}
    dashboard._update_devices([online, offline])
    assert dashboard.side_title.text() == "Devices (2)"
    assert dashboard.screens_title.text() == "All Screens (1)"
    assert "a" in dashboard._cards and "b" in dashboard._cards
    dashboard._cards["a"].view_btn.click()
    on_connect.assert_called_once()
    on_connect.reset_mock()
    dashboard._cards["b"].view_btn.click()
    on_connect.assert_not_called()
    dashboard._on_preview("a", b"not-a-jpeg")  # ignored by QImage; must not crash
    dashboard.shutdown_previews()
    dashboard.close()


def test_remove_hides_device_in_ui_even_if_still_online(app, monkeypatch):
    monkeypatch.setattr(main.store, "load", lambda: ("ws://localhost:8000/ws", "key"))
    monkeypatch.setattr(main.store, "load_hidden", lambda: set())
    monkeypatch.setattr(main.store, "save", Mock())
    monkeypatch.setattr(main.store, "hide_device", lambda did: {did})
    monkeypatch.setattr(main, "PreviewFeed", Mock())
    console = Mock()
    monkeypatch.setattr(main, "ConsoleNet", Mock(return_value=console))
    monkeypatch.setattr(QMessageBox, "question", Mock(return_value=QMessageBox.Yes))
    dashboard = main.Dashboard(Mock())
    online = {"id": "a", "name": "Alpha", "online": True}
    dashboard._update_devices([online])
    dashboard._cards["a"].remove_btn.click()
    console.remove_device.assert_called_once_with("a")
    assert "a" not in dashboard._cards
    assert dashboard.side_title.text() == "Devices (0)"
    # Relay may still list it; hidden filter keeps UI cleared.
    dashboard._update_devices([online])
    assert "a" not in dashboard._cards
    dashboard.shutdown_previews()
    dashboard.close()


def test_hidden_devices_filtered_from_device_list(app, monkeypatch):
    monkeypatch.setattr(main.store, "load", lambda: ("ws://localhost:8000/ws", "key"))
    monkeypatch.setattr(main.store, "load_hidden", lambda: {"gone"})
    monkeypatch.setattr(main.store, "save", Mock())
    monkeypatch.setattr(main, "PreviewFeed", Mock())
    monkeypatch.setattr(main, "ConsoleNet", Mock())
    dashboard = main.Dashboard(Mock())
    dashboard._update_devices([
        {"id": "gone", "name": "Hidden", "online": True},
        {"id": "ok", "name": "Visible", "online": True},
    ])
    assert list(dashboard._cards) == ["ok"]
    dashboard.shutdown_previews()
    dashboard.close()
