import asyncio

import protocol as P
from relay.server import Network, _handle_agent


class Socket:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.sent = []
        self.frames = []

    async def receive(self):
        return await self.messages.get()

    async def send_text(self, text):
        self.sent.append(P.loads(text))

    async def send_bytes(self, frame):
        self.frames.append(frame)


def test_old_agent_disconnect_cannot_remove_replacement():
    async def scenario():
        network = Network()
        old, new, controller = Socket(), Socket(), Socket()
        auth = P.auth_agent("key", "pc", "PC")
        old_task = asyncio.create_task(_handle_agent(old, network, auth))
        await asyncio.sleep(0)
        network.devices["pc"].controller = controller
        new_task = asyncio.create_task(_handle_agent(new, network, auth))
        await asyncio.sleep(0)
        try:
            await old.messages.put({"type": "websocket.disconnect"})
            await old_task
            assert network.devices["pc"].agent is new
            assert network.devices["pc"].online
            assert network.devices["pc"].controller is controller
            assert new.sent == [{"type": P.PEER_JOINED, "role": P.ROLE_CONTROLLER}]
            assert controller.sent == []
            await new.messages.put({"type": "websocket.receive", "bytes": b"NEW_FRAME"})
            await asyncio.sleep(0)
            assert controller.frames == [b"NEW_FRAME"]
        finally:
            await new.messages.put({"type": "websocket.disconnect"})
            await new_task
    asyncio.run(scenario())
