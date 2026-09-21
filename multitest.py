"""Prove the relay isolates multiple machines/sessions at once."""
import asyncio, threading, time, uvicorn, websockets
import protocol as P
from relay.server import app

URL = "ws://127.0.0.1:8145/ws"

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8145, log_level="warning")

async def main():
    results = []
    # Two machines: session "office" and session "home", one controller each.
    c_office = await websockets.connect(URL)
    await c_office.send(P.dumps(P.auth("office", "pw1", P.ROLE_CONTROLLER)))
    a_office = await websockets.connect(URL)
    await a_office.send(P.dumps(P.auth("office", "pw1", P.ROLE_AGENT)))

    c_home = await websockets.connect(URL)
    await c_home.send(P.dumps(P.auth("home", "pw2", P.ROLE_CONTROLLER)))
    a_home = await websockets.connect(URL)
    await a_home.send(P.dumps(P.auth("home", "pw2", P.ROLE_AGENT)))

    # drain PEER_JOINED notifications
    for ws in (c_office, a_office, c_home, a_home):
        await asyncio.wait_for(ws.recv(), 2)

    # office controller sends a distinctive frame-ish marker to its agent path:
    # actually agent->controller for frames; test controller->agent input isolation.
    await c_office.send(P.dumps(P.mouse(P.M_MOVE, 0.11, 0.11)))
    await c_home.send(P.dumps(P.mouse(P.M_MOVE, 0.99, 0.99)))

    m_office = P.loads(await asyncio.wait_for(a_office.recv(), 2))
    m_home = P.loads(await asyncio.wait_for(a_home.recv(), 2))

    results.append(("office agent got office coords",
                    abs(m_office["x"] - 0.11) < 1e-6))
    results.append(("home agent got home coords",
                    abs(m_home["x"] - 0.99) < 1e-6))

    # Cross-talk check: office agent must NOT have received home's message.
    # Give it a moment; there should be nothing waiting.
    got_extra = False
    try:
        await asyncio.wait_for(a_office.recv(), 0.5)
        got_extra = True
    except asyncio.TimeoutError:
        pass
    results.append(("no cross-talk between sessions", not got_extra))

    # frame direction: home agent -> home controller only
    await a_home.send(b"HOME_FRAME")
    f = await asyncio.wait_for(c_home.recv(), 2)
    results.append(("home frame reached home controller", f == b"HOME_FRAME"))

    for ws in (c_office, a_office, c_home, a_home):
        await ws.close()

    print("\n=== MULTI-SESSION TEST ===")
    ok = all(p for _, p in results)
    for name, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    print("OVERALL:", "PASS" if ok else "FAIL")

threading.Thread(target=run_server, daemon=True).start()
time.sleep(1.5)
asyncio.run(main())
