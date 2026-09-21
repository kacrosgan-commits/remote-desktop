"""Relay / rendezvous server with a live device registry.

Roles (decided by the first AUTH message):
  * agent      -> registers under a network_key + device_id; becomes online
                  and controllable. Always sends low-rate PREVIEW thumbnails
                  for the dashboard; streams full frames only while a
                  controller is attached.
  * console    -> the dashboard: subscribes to a network_key and receives
                  a live DEVICE_LIST (pushed on every change) plus PREVIEW
                  thumbnails for each online agent.
  * controller -> an active control session for one device_id: input flows
                  to that device's agent, frames flow back.

Everyone in the SAME network_key can see/control each other; different keys
are fully isolated. The key is the only access control, so make it strong.

Run:  uvicorn relay.server:app --host 0.0.0.0 --port 8000
"""
import sys
import os
from dataclasses import dataclass, field

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import protocol as P  # noqa: E402

app = FastAPI()


@dataclass
class Device:
    name: str
    agent: WebSocket | None = None
    controller: WebSocket | None = None

    @property
    def online(self) -> bool:
        return self.agent is not None


@dataclass
class Network:
    devices: dict[str, Device] = field(default_factory=dict)
    consoles: set = field(default_factory=set)


networks: dict[str, Network] = {}


def get_network(key: str) -> Network:
    net = networks.get(key)
    if net is None:
        net = Network()
        networks[key] = net
    return net


async def _send(ws, msg: dict):
    try:
        await ws.send_text(P.dumps(msg))
    except Exception:
        pass


async def broadcast_devices(net: Network):
    payload = P.device_list([
        {"id": did, "name": d.name, "online": d.online}
        for did, d in net.devices.items()
    ])
    for c in list(net.consoles):
        try:
            await c.send_text(P.dumps(payload))
        except Exception:
            net.consoles.discard(c)


async def broadcast_preview(net: Network, text: str):
    """Fan dashboard thumbnails to every console on this network key."""
    for c in list(net.consoles):
        try:
            await c.send_text(text)
        except Exception:
            net.consoles.discard(c)


async def _preview_from_jpeg(net: Network, device_id: str, jpeg: bytes):
    import base64
    await broadcast_preview(net, P.dumps(P.preview(
        device_id, base64.b64encode(jpeg).decode("ascii"))))


@app.get("/healthz")
async def healthz():
    return {"ok": True, "networks": len(networks)}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    # 1) First message MUST be AUTH.
    try:
        first = P.loads(await ws.receive_text())
    except Exception:
        await _send(ws, P.error("expected AUTH as first message"))
        await ws.close()
        return
    if first.get("type") != P.AUTH:
        await _send(ws, P.error("first message was not AUTH"))
        await ws.close()
        return

    role = first.get("role")
    key = first.get("network_key")
    if not key or role not in (P.ROLE_AGENT, P.ROLE_CONSOLE, P.ROLE_CONTROLLER):
        await _send(ws, P.error("invalid AUTH"))
        await ws.close()
        return

    net = get_network(key)

    if role == P.ROLE_AGENT:
        await _handle_agent(ws, net, first)
    elif role == P.ROLE_CONSOLE:
        await _handle_console(ws, net)
    else:
        await _handle_controller(ws, net, first)


async def _handle_agent(ws: WebSocket, net: Network, auth: dict):
    device_id = auth.get("device_id")
    name = auth.get("name") or device_id
    if not device_id:
        await _send(ws, P.error("agent AUTH missing device_id"))
        await ws.close()
        return

    dev = net.devices.get(device_id)
    if dev is None:
        dev = Device(name=name)
        net.devices[device_id] = dev
    dev.name = name
    dev.agent = ws
    # A reboot/reconnect can register before the old socket times out. Keep
    # any active controller paired with the current agent in that overlap.
    if dev.controller is not None:
        await _send(ws, {"type": P.PEER_JOINED, "role": P.ROLE_CONTROLLER})
    await broadcast_devices(net)

    try:
        while True:
            m = await ws.receive()
            if dev.agent is not ws:
                break
            if m.get("type") == "websocket.disconnect":
                break
            if m.get("bytes") is not None:
                c = dev.controller
                if c is not None:
                    await c.send_bytes(m["bytes"])
                else:
                    # Idle binary frames (preview-sized) feed the dashboard.
                    await _preview_from_jpeg(net, device_id, m["bytes"])
            elif m.get("text") is not None:
                text = m["text"]
                try:
                    msg = P.loads(text)
                except Exception:
                    msg = None
                if isinstance(msg, dict) and msg.get("type") == P.PREVIEW:
                    # Ensure device_id matches the registered agent.
                    msg["device_id"] = device_id
                    await broadcast_preview(net, P.dumps(msg))
                else:
                    c = dev.controller
                    if c is not None:
                        await c.send_text(text)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if dev.agent is ws:
            dev.agent = None
            if dev.controller is not None:
                controller = dev.controller
                dev.controller = None
                await _send(controller, {"type": P.PEER_LEFT, "role": P.ROLE_AGENT})
            await broadcast_devices(net)


async def _handle_console(ws: WebSocket, net: Network):
    net.consoles.add(ws)
    # send current list immediately
    await _send(ws, P.device_list([
        {"id": did, "name": d.name, "online": d.online}
        for did, d in net.devices.items()
    ]))
    try:
        while True:
            m = await ws.receive()
            if m.get("type") == "websocket.disconnect":
                break
            if m.get("text") is None:
                continue
            try:
                msg = P.loads(m["text"])
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            kind = msg.get("type")
            if kind == P.REQUEST_DEVICES:
                await _send(ws, P.device_list([
                    {"id": did, "name": d.name, "online": d.online}
                    for did, d in net.devices.items()
                ]))
            elif kind == P.REMOVE_DEVICE:
                device_id = msg.get("device_id")
                if device_id and device_id in net.devices:
                    await _remove_device(net, device_id)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        net.consoles.discard(ws)


async def _remove_device(net: Network, device_id: str):
    """Drop a device from the registry and close any live sockets for it."""
    dev = net.devices.pop(device_id, None)
    if dev is None:
        return
    agent = dev.agent
    controller = dev.controller
    dev.agent = None
    dev.controller = None
    if controller is not None:
        await _send(controller, {"type": P.PEER_LEFT, "role": P.ROLE_AGENT})
        try:
            await controller.close()
        except Exception:
            pass
    if agent is not None:
        await _send(agent, {"type": P.PEER_LEFT, "role": P.ROLE_CONTROLLER})
        try:
            await agent.close()
        except Exception:
            pass
    await broadcast_devices(net)


async def _handle_controller(ws: WebSocket, net: Network, auth: dict):
    device_id = auth.get("device_id")
    dev = net.devices.get(device_id)
    if dev is None or not dev.online:
        await _send(ws, P.error("device offline or unknown"))
        await ws.close()
        return
    if dev.controller is not None:
        await _send(ws, P.error("device is already being controlled"))
        await ws.close()
        return

    dev.controller = ws
    await _send(dev.agent, {"type": P.PEER_JOINED, "role": P.ROLE_CONTROLLER})
    await _send(ws, {"type": P.PEER_JOINED, "role": P.ROLE_AGENT})

    try:
        while True:
            m = await ws.receive()
            if m.get("type") == "websocket.disconnect":
                break
            if m.get("text") is not None:
                a = dev.agent
                if a is not None:
                    await a.send_text(m["text"])
            # controllers don't send binary
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if dev.controller is ws:
            dev.controller = None
            if dev.agent is not None:
                await _send(dev.agent, {"type": P.PEER_LEFT, "role": P.ROLE_CONTROLLER})
