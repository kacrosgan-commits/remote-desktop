import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import protocol as P
from agent import main
from protocol.connection import run_pair


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
        agent._frame_ready = asyncio.Event()

        async def stop_after_grab():
            while agent.cap is None or agent.cap.grabber is None:
                await asyncio.sleep(0.01)
            raise asyncio.CancelledError()

        try:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(
                    run_pair(agent._capture_loop(), stop_after_grab()), timeout=2)
            assert agent.cap.owner == agent.cap.grabber
            assert agent.cap.owner != threading.get_ident()
        finally:
            if hasattr(agent, "close"):
                await agent.close()
    asyncio.run(scenario())


def test_send_loop_sends_latest_session_frame(agent):
    async def scenario():
        agent._peer_present = True
        agent._frame_ready = asyncio.Event()
        agent._latest_session_jpeg = b"newest"
        agent._frame_ready.set()
        sent = []

        async def fake_send(data):
            sent.append(data)
            raise asyncio.CancelledError()

        socket = SimpleNamespace(send=fake_send)
        try:
            with pytest.raises(asyncio.CancelledError):
                await agent._send_loop(socket)
            assert sent == [b"newest"]
            assert agent._latest_session_jpeg is None
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


def test_config_accepts_scale(agent):
    async def scenario():
        class Socket:
            async def __aiter__(self):
                yield P.dumps({"type": P.CONFIG, "fps": 6, "quality": 40, "scale": 0.4})
        try:
            await agent._recv(Socket())
            assert agent.fps == 6
            assert agent.quality == 40
            assert agent.scale == 0.4
        finally:
            if hasattr(agent, "close"):
                await agent.close()
    asyncio.run(scenario())
