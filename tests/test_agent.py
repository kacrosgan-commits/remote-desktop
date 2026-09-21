import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import protocol as P
from agent import main


@pytest.fixture
def agent(monkeypatch):
    class Capture:
        left = top = 0
        width, height = 1920, 1080

        def __init__(self, monitor_index=1):
            self.owner = threading.get_ident()
            self.grabber = None

        def grab_jpeg(self, quality, scale):
            self.grabber = threading.get_ident()
            return b"jpeg"

        def close(self):
            assert self.owner == threading.get_ident()

    monkeypatch.setattr(main, "ScreenCapturer", Capture)
    monkeypatch.setattr(main, "InputInjector", Mock())
    monkeypatch.setattr(main, "make_input_blocker", Mock())
    monkeypatch.setattr(main, "get_device_id", lambda: "test-device")
    args = SimpleNamespace(name="Test", fps=12, quality=60, scale=1.0, monitor=1)
    return main.Agent(args)


def test_capture_is_created_and_used_on_same_worker_thread(agent):
    async def scenario():
        agent._peer_present = True
        socket = SimpleNamespace(send=AsyncMock(side_effect=asyncio.CancelledError))
        try:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(agent._send_frames(socket), timeout=2)
            assert agent.cap.owner == agent.cap.grabber
            assert agent.cap.owner != threading.get_ident()
        finally:
            if hasattr(agent, "close"):
                await agent.close()
    asyncio.run(scenario())


def test_agent_releases_held_input_when_controller_leaves(agent):
    async def scenario():
        class Socket:
            async def __aiter__(self):
                yield P.dumps({"type": P.PEER_LEFT})
        try:
            await agent._recv(Socket())
            agent.injector.release_all.assert_called_once()
            agent.blocker.unblock.assert_called_once()
        finally:
            if hasattr(agent, "close"):
                await agent.close()
    asyncio.run(scenario())
