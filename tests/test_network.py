import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import protocol as P
from controller.net import Net, Signals


def test_stopped_network_thread_can_be_joined(app):
    net = Net("ws://127.0.0.1:1/ws", "test", "device", Signals())
    net.stop()
    net.start()
    net.join(timeout=2)
    assert not net.is_alive()


def test_offline_input_is_not_queued_for_next_connection():
    async def scenario():
        net = Net("ws://unused", "test", "device", Signals())
        net.loop = asyncio.get_running_loop()
        net.outq = asyncio.Queue()
        net.send_json(P.key(P.K_DOWN, "a"))
        await asyncio.sleep(0)
        assert net.outq.empty()
    asyncio.run(scenario())


def test_peer_left_ends_receive_loop_so_session_can_reconnect():
    async def scenario():
        signals = SimpleNamespace(peer=Mock(), status=Mock())
        net = Net("ws://unused", "test", "device", signals)

        class Socket:
            async def __aiter__(self):
                yield P.dumps({"type": P.PEER_LEFT})
                await asyncio.Event().wait()

        await asyncio.wait_for(net._recv(Socket()), timeout=0.2)
        signals.peer.emit.assert_called_with(False)
    asyncio.run(scenario())


def test_device_offline_error_is_soft_and_does_not_raise():
    async def scenario():
        signals = SimpleNamespace(peer=Mock(), status=Mock())
        net = Net("ws://unused", "test", "device", signals)

        class Socket:
            async def __aiter__(self):
                yield P.dumps(P.error("device offline or unknown"))

        await asyncio.wait_for(net._recv(Socket()), timeout=0.2)
        signals.peer.emit.assert_called_with(False)
        signals.status.emit.assert_called_with("device offline")
    asyncio.run(scenario())


def test_preview_feed_net_disables_auto_reconnect():
    signals = Signals()
    net = Net("ws://127.0.0.1:1/ws", "test", "device", signals, auto_reconnect=False)
    assert net.auto_reconnect is False
