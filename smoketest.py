"""End-to-end relay smoke test (no GUI, no screen capture).

Starts the relay in-process, connects a fake agent and controller, and
checks that: pairing works, PEER_JOINED fires, a binary frame flows
agent->controller, and input/lock JSON flows controller->agent.
"""
import asyncio
import threading
import time
import uvicorn
import websockets

import protocol as P
from relay.server import app

URL = "ws://127.0.0.1:8123/ws"


def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8123, log_level="warning")


async def main():
    results = []

    # controller connects first and waits.
    controller = await websockets.connect(URL)
    await controller.send(P.dumps(P.auth("s1", "pw", P.ROLE_CONTROLLER)))

    # agent connects -> both should get PEER_JOINED.
    agent = await websockets.connect(URL)
    await agent.send(P.dumps(P.auth("s1", "pw", P.ROLE_AGENT)))

    ctrl_join = P.loads(await asyncio.wait_for(controller.recv(), 2))
    agent_join = P.loads(await asyncio.wait_for(agent.recv(), 2))
    results.append(("controller got PEER_JOINED", ctrl_join.get("type") == P.PEER_JOINED))
    results.append(("agent got PEER_JOINED", agent_join.get("type") == P.PEER_JOINED))

    # agent -> controller : binary frame
    await agent.send(b"\xff\xd8FAKEJPEG\xff\xd9")
    got = await asyncio.wait_for(controller.recv(), 2)
    results.append(("binary frame agent->controller", got == b"\xff\xd8FAKEJPEG\xff\xd9"))

    # controller -> agent : mouse move
    await controller.send(P.dumps(P.mouse(P.M_MOVE, 0.5, 0.5)))
    m = P.loads(await asyncio.wait_for(agent.recv(), 2))
    results.append(("mouse move controller->agent", m.get("type") == P.INPUT_MOUSE))

    # controller -> agent : lock
    await controller.send(P.dumps({"type": P.LOCK_INPUT}))
    lk = P.loads(await asyncio.wait_for(agent.recv(), 2))
    results.append(("LOCK_INPUT controller->agent", lk.get("type") == P.LOCK_INPUT))

    # wrong password rejected
    bad = await websockets.connect(URL)
    await bad.send(P.dumps(P.auth("s1", "WRONG", P.ROLE_CONTROLLER)))
    err = P.loads(await asyncio.wait_for(bad.recv(), 2))
    results.append(("wrong password rejected", err.get("type") == P.ERROR))

    # agent disconnect -> controller gets PEER_LEFT
    await agent.close()
    left = P.loads(await asyncio.wait_for(controller.recv(), 2))
    results.append(("PEER_LEFT on agent disconnect", left.get("type") == P.PEER_LEFT))

    await controller.close()

    print("\n=== SMOKE TEST RESULTS ===")
    ok = True
    for name, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("==========================")
    print("OVERALL:", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    time.sleep(1.5)  # let uvicorn bind
    asyncio.run(main())
