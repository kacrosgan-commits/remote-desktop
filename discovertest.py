"""Test the auto-discovery relay: registration, live list, isolation, control."""
import asyncio, threading, time, uvicorn, websockets
import protocol as P
from relay.server import app

URL = "ws://127.0.0.1:8166/ws"

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8166, log_level="warning")

async def recv_json(ws, t=2):
    return P.loads(await asyncio.wait_for(ws.recv(), t))

async def main():
    R = []

    # Console subscribes to key "TEAM" before any agent exists.
    console = await websockets.connect(URL)
    await console.send(P.dumps(P.auth_console("TEAM")))
    first = await recv_json(console)
    R.append(("console gets empty list first",
              first["type"] == P.DEVICE_LIST and first["devices"] == []))

    # Agent A comes online -> console should get a push listing A.
    agentA = await websockets.connect(URL)
    await agentA.send(P.dumps(P.auth_agent("TEAM", "dev-a", "PC-A")))
    upd = await recv_json(console)
    R.append(("agent A appears online",
              any(d["id"] == "dev-a" and d["online"] for d in upd["devices"])))

    # Agent B (same key) -> list now has A and B.
    agentB = await websockets.connect(URL)
    await agentB.send(P.dumps(P.auth_agent("TEAM", "dev-b", "PC-B")))
    upd = await recv_json(console)
    R.append(("agent B appears too", len(upd["devices"]) == 2))

    # Different network key is isolated.
    otherconsole = await websockets.connect(URL)
    await otherconsole.send(P.dumps(P.auth_console("OTHER")))
    other_first = await recv_json(otherconsole)
    R.append(("other key sees nothing", other_first["devices"] == []))

    # Control device A.
    ctrl = await websockets.connect(URL)
    await ctrl.send(P.dumps(P.auth_controller("TEAM", "dev-a")))
    j_ctrl = await recv_json(ctrl)
    j_agent = await recv_json(agentA)
    R.append(("controller paired with A",
              j_ctrl["type"] == P.PEER_JOINED and j_agent["type"] == P.PEER_JOINED))

    # Input controller->A ; frame A->controller.
    await ctrl.send(P.dumps(P.mouse(P.M_MOVE, 0.42, 0.42)))
    m = await recv_json(agentA)
    R.append(("input reaches agent A", abs(m["x"] - 0.42) < 1e-6))
    await agentA.send(b"FRAME_A")
    f = await asyncio.wait_for(ctrl.recv(), 2)
    R.append(("frame reaches controller", f == b"FRAME_A"))

    # Second controller on A is rejected.
    ctrl2 = await websockets.connect(URL)
    await ctrl2.send(P.dumps(P.auth_controller("TEAM", "dev-a")))
    err = await recv_json(ctrl2)
    R.append(("2nd controller rejected", err["type"] == P.ERROR))

    # Agent A goes offline -> console update shows A offline, controller notified.
    await agentA.close()
    left = await recv_json(ctrl)
    R.append(("controller told device left", left["type"] == P.PEER_LEFT))
    upd = await recv_json(console)
    a_state = [d for d in upd["devices"] if d["id"] == "dev-a"][0]
    R.append(("A now shows offline", a_state["online"] is False))

    for ws in (console, agentB, otherconsole, ctrl):
        await ws.close()

    print("\n=== AUTO-DISCOVERY TEST ===")
    ok = all(p for _, p in R)
    for name, passed in R:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    print("OVERALL:", "PASS" if ok else "FAIL")

threading.Thread(target=run_server, daemon=True).start()
time.sleep(1.5)
asyncio.run(main())
