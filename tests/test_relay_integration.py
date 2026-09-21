import asyncio
import socket
import threading
import time
from types import SimpleNamespace

import pytest
import uvicorn
import websockets

import protocol as P
from controller.net import ConsoleNet, Net
from relay.server import app, networks


class Recorder:
    def __init__(self):
        self.values = []

    def emit(self, *value):
        self.values.append(value[0] if len(value) == 1 else value)


@pytest.fixture
def relay_url():
    networks.clear()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started, "local relay failed to start"
    try:
        yield f"ws://127.0.0.1:{port}/ws"
    finally:
        server.should_exit = True
        worker.join(timeout=5)
        listener.close()
        assert not worker.is_alive()


async def eventually(predicate):
    async with asyncio.timeout(6):
        while not predicate():
            await asyncio.sleep(0.01)


async def receive(ws):
    return P.loads(await asyncio.wait_for(ws.recv(), timeout=6))


def test_refresh_keeps_sessions_and_reconnects_after_agent_restart(relay_url):
    async def scenario():
        console_signals = SimpleNamespace(devices=Recorder(), status=Recorder(), preview=Recorder())
        session_signals = SimpleNamespace(peer=Recorder(), status=Recorder(), frame=Recorder())
        console = ConsoleNet(relay_url, "test-network", console_signals)
        session = Net(relay_url, "test-network", "device", session_signals)
        console.start()
        try:
            async with websockets.connect(relay_url) as agent:
                await agent.send(P.dumps(P.auth_agent("test-network", "device", "Test PC")))
                await eventually(lambda: console_signals.devices.values and
                                 console_signals.devices.values[-1] == [
                                     {"id": "device", "name": "Test PC", "online": True}])
                await agent.send(P.dumps(P.preview("device", __import__("base64").b64encode(b"thumb").decode())))
                await eventually(lambda: console_signals.preview.values == [("device", b"thumb")])
                session.start()
                assert (await receive(agent))["type"] == P.PEER_JOINED
                await eventually(lambda: session_signals.peer.values == [True])

                # Exercise the actual network-thread input queue through the relay.
                inputs = [P.mouse(P.M_DOWN, 0.5, 0.5), P.mouse(P.M_UP, 0.5, 0.5),
                          P.key(P.K_DOWN, "ctrl"), P.key(P.K_DOWN, "c"),
                          P.key(P.K_UP, "c"), P.key(P.K_UP, "ctrl")]
                for message in inputs:
                    session.send_json(message)
                    assert await receive(agent) == message
                await agent.send(b"TEST_FRAME")
                await eventually(lambda: session_signals.frame.values == [b"TEST_FRAME"])

                count = len(console_signals.devices.values)
                console.reconnect()
                await eventually(lambda: len(console_signals.devices.values) > count and
                                 console_signals.devices.values[-1] and
                                 console_signals.devices.values[-1][0]["online"])
                assert session_signals.peer.values == [True]

                # Refresh the screen: old control session ends before a new one starts.
                session.reconnect()
                assert (await receive(agent))["type"] == P.PEER_LEFT
                assert (await receive(agent))["type"] == P.PEER_JOINED
                await eventually(lambda: session_signals.peer.values[-2:] == [False, True])

            await eventually(lambda: not session_signals.peer.values[-1])
            session.send_json(P.key(P.K_DOWN, "x"))  # must be discarded while offline
            async with websockets.connect(relay_url) as restarted:
                await restarted.send(P.dumps(P.auth_agent("test-network", "device", "Test PC")))
                assert (await receive(restarted))["type"] == P.PEER_JOINED
                await eventually(lambda: session_signals.peer.values[-1])
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(restarted.recv(), timeout=0.15)
                await restarted.send(b"NEW_FRAME")
                await eventually(lambda: session_signals.frame.values[-1] == b"NEW_FRAME")
        finally:
            session.stop()
            console.stop()
            if session.ident is not None:
                session.join(timeout=4)
                assert not session.is_alive()
            console.join(timeout=4)
            assert not console.is_alive()
    asyncio.run(scenario())


def test_console_can_remove_offline_device(relay_url):
    async def scenario():
        console_signals = SimpleNamespace(devices=Recorder(), status=Recorder(), preview=Recorder())
        console = ConsoleNet(relay_url, "test-network", console_signals)
        console.start()
        try:
            async with websockets.connect(relay_url) as agent:
                await agent.send(P.dumps(P.auth_agent("test-network", "device", "Test PC")))
                await eventually(lambda: any(
                    devices and devices[-1].get("online")
                    for devices in console_signals.devices.values
                    for devices in [devices] if devices and isinstance(devices, list)
                ) or any(
                    d.get("id") == "device" and d.get("online")
                    for batch in console_signals.devices.values
                    for d in (batch or [])
                ))
            await eventually(lambda: any(
                d.get("id") == "device" and not d.get("online")
                for batch in console_signals.devices.values
                for d in (batch or [])
            ))
            console.remove_device("device")
            await eventually(lambda: console_signals.devices.values[-1] == [])
        finally:
            console.stop()
            console.join(timeout=4)
    asyncio.run(scenario())
