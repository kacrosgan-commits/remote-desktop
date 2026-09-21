# RemoteDesk

Control a Windows computer (`agent.exe`) from another computer
(`controller.exe`) through your own WebSocket relay. Both applications
connect outbound, so agent computers do not need port forwarding.

## Updated version

- **Dashboard screen grid:** the Devices tab shows a live thumbnail of every
  online computer. Click **View** (or double-click the list) to open a full
  control session. Online/offline status updates automatically as agents
  connect or disconnect.
- **Automatic installation and startup:** launch the newly built agent once.
  It installs for the current Windows user and starts at that user's next
  sign-in, including after a restart. A logon task also restarts the agent
  if it exits unexpectedly.
- **Refresh:** reload the device list with Refresh/F5; reconnect an individual
  session with Refresh screen.
- **Mouse and keyboard:** an explicit control/view-only toggle, clicks,
  double-clicks, dragging, scrolling, typing and keyboard shortcuts.
  Switching away, disabling control or disconnecting releases held input.
- **Reconnect fixes:** no stale input is replayed after reconnecting, and
  screen capture stays on the same worker thread.

Read [WINDOWS-QUICKSTART.md](WINDOWS-QUICKSTART.md) for installation, upgrades,
removal, limitations and Windows acceptance checks.

## Build on Windows

Install Python 3.10 or newer and double-click `build.bat`. Enter your relay
URL and network key, or press Enter to retain the current settings. The build
installs dependencies and produces `dist/agent.exe`, `dist/controller.exe`
and `dist/RemoteDesk-windows.zip`. Copy the new agent to the controlled PC
and the controller to the controlling PC.

**The original executables in `dist` are older builds.** Source changes do
not update those files until you run the Windows build. PyInstaller must
run on Windows to produce these Windows executables.

## Relay

From the repository root:

```sh
docker build -f relay/Dockerfile -t remotedesk-relay .
docker run -d --name relay -p 8000:8000 remotedesk-relay
```

Use `relay/Caddyfile` to terminate TLS and connect with `wss://`.
For a local test, use `ws://<relay-ip>:8000/ws`. The relay must remain running.
The wire protocol has not changed. Rebuild/redeploy the relay from this
source as part of the update: it also fixes an old connection incorrectly
marking a newly reconnected agent offline after a restart.

Agents register under a stable device ID. The dashboard subscribes to a
network key and receives online/offline updates plus live screen previews.
Double-click an online machine (or click **View**) to open its session;
several machines can be open in separate tabs. Full-resolution frames stream
only while a control session is open; low-rate thumbnails always feed the
dashboard while the agent is online.

The network key grants access to the computers using it. Keep it private
and use a long random value. JPEG frames travel over WebSocket binary
messages; keyboard, mouse and configuration messages use JSON. FPS and
quality can be adjusted inside each remote tab.

## Running from source

```sh
python -m pip install -r agent/requirements.txt -r controller/requirements.txt
python -m agent.main --relay ws://localhost:8000/ws --network-key YOUR_KEY
python -m controller.main
```

Running from source does not install startup. The packaged Windows agent
also supports `--portable` to run without installation and `--install` to
register startup explicitly.

## Tests

```sh
python -m pip install pytest -r agent/requirements.txt -r controller/requirements.txt -r relay/requirements.txt
python -m pytest -q
```

Tests use Qt offscreen and a dummy input backend, so they do not control the
test machine. The integration test starts a relay bound to localhost and
checks input, frames, refresh and reconnection. Actual Windows registry
startup, capture and OS input injection need the two-computer checks in the
quickstart guide.

## Limits

The agent starts after its installing user signs in, not on the Windows
sign-in screen. Normal installation runs with that user's privileges.
UAC secure desktop, Ctrl+Alt+Del and elevated applications have Windows
restrictions. The local-input blocking backend is implemented for Windows;
Linux/macOS blocking backends remain stubs. Code signing is recommended
when distributing your own executables.
