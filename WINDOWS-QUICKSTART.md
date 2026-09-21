# RemoteDesk updated Windows version

## Build the new executables

On Windows, install Python 3.10 or newer, extract the updated source folder,
then double-click `build.bat`. Press Enter to keep your existing relay URL
and network key, or enter replacements. The build produces:

- `dist/agent.exe`
- `dist/controller.exe`
- `dist/RemoteDesk-windows.zip` (executables, installer/uninstaller and this guide)

Existing executables in the original project are **older builds**. The source
update must be built on Windows before these new features are available in an exe.

## On the computer you want to control

1. If you installed the old scheduled-task version, run the new
   `uninstall-agent.bat` as Administrator once before installing this version.
2. Double-click the **newly built** `agent.exe` once, as the Windows user
   whose desktop you want to control. It installs in
   `%LOCALAPPDATA%\RemoteDesk`, starts, and shows an installation confirmation.
   If an older agent is already running, the new exe stops it and replaces it
   automatically — you no longer need to close it by hand first.
3. After subsequent restarts, it starts automatically when **that user signs in**.
   Windows may delay startup briefly. A logon scheduled task also restarts the
   agent if it stops unexpectedly. Keep the relay running and the network available.

Installation is needed only once. It does not reinstall on every restart and
does not control the Windows sign-in screen. It runs with the signed-in user's
permissions; elevated applications and the UAC secure desktop are not covered
by a normal user session.

For a temporary session without installation, use `agent.exe --portable`.
To register startup again, use `agent.exe --install` or `install-agent.bat`.
Options such as `--name "Office PC"` are saved when installing.
To update an installed agent, run its uninstall script first and then launch
the newly built exe. The device ID is retained, so it keeps its dashboard identity.

Uninstall using `%LOCALAPPDATA%\RemoteDesk\uninstall-agent.bat`, as the same
Windows user. Logs are in `%USERPROFILE%\.remotedesk\agent.log`.

## On the controller computer

1. Open the **newly built** `controller.exe`. The Devices tab shows a live
   thumbnail grid of every online computer; online/offline updates automatically.
2. Click **View** on a card (or double-click the device in the sidebar) to open
   a control session. Keep **Control mouse and keyboard** checked,
   then click its screen to type, click, drag, double-click, or scroll.
3. Select a PC in the sidebar and click **Remove selected** to clear it from
   the list (offline PCs stay gone until that agent reconnects).
4. Uncheck control for view-only mode. **Ctrl+Shift+Esc** also releases control.
   Switching tabs/windows releases held remote keys and mouse buttons.
5. Use **Refresh screen** to reconnect a stalled remote tab.

The separate **Block local input on remote PC** option blocks that PC's physical
keyboard/mouse. It is unrelated to enabling the controller's mouse/keyboard.
Ctrl+Alt+Del and OS-reserved shortcuts may be handled by Windows locally.

Rebuild/redeploy your relay using the updated `relay/server.py` as part of this
update (see README.md) so dashboard thumbnails and reconnect fixes are available.
The reconnect fix also covers overlapping old/new connections after a restart
incorrectly marking the new agent offline.

## Checks before deployment

On two Windows computers, verify first installation, appearance in the device
list, mouse/keyboard input, Refresh, reboot and sign-in, and uninstallation.
Also check that switching away while holding Ctrl or dragging releases input.
The automated tests cover the Python/Qt behavior and a local relay, while these
Windows checks verify actual registry startup, capture and input injection.
