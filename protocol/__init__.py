"""Shared wire protocol for Remote Dragon.

Auto-discovery model:
  * Every agent and the controller share one NETWORK KEY.
  * Agents REGISTER themselves with the relay -> they appear online.
  * The controller's dashboard SUBSCRIBEs and receives a live DEVICE_LIST.
  * To control a device, the controller opens a session by device_id.

Control / input messages are JSON (WebSocket TEXT frames).
Screen frames are raw JPEG bytes (WebSocket BINARY frames).
"""
import json

# ---- message "type" values ---------------------------------------------------
AUTH = "AUTH"              # client -> relay (first message; role-specific)
DEVICE_LIST = "DEVICE_LIST"  # relay -> console: [{id, name, online}]
PREVIEW = "PREVIEW"        # agent -> relay -> console: {device_id, jpeg} (base64)
REMOVE_DEVICE = "REMOVE_DEVICE"  # console -> relay: drop a device from the registry
REQUEST_DEVICES = "REQUEST_DEVICES"  # console -> relay: ask for a fresh DEVICE_LIST
ALERT = "ALERT"              # agent -> relay -> console: wallet/app opened on a PC
PEER_JOINED = "PEER_JOINED"  # relay -> agent/controller
PEER_LEFT = "PEER_LEFT"      # relay -> agent/controller
ERROR = "ERROR"            # relay -> client {message}

INPUT_MOUSE = "INPUT_MOUSE"   # controller -> agent
INPUT_KEY = "INPUT_KEY"       # controller -> agent
LOCK_INPUT = "LOCK_INPUT"     # controller -> agent
UNLOCK_INPUT = "UNLOCK_INPUT" # controller -> agent
CONFIG = "CONFIG"          # controller -> agent {fps?, quality?}

# roles
ROLE_AGENT = "agent"        # a controllable machine announcing itself
ROLE_CONSOLE = "console"    # the dashboard, listening for the device list
ROLE_CONTROLLER = "controller"  # an active control session for one device

# mouse actions
M_MOVE = "move"
M_DOWN = "down"
M_UP = "up"
M_SCROLL = "scroll"

# key actions
K_DOWN = "down"
K_UP = "up"


def dumps(msg: dict) -> str:
    return json.dumps(msg, separators=(",", ":"))


def loads(text: str) -> dict:
    return json.loads(text)


# --- auth constructors (first message per connection) -------------------------
def auth_agent(network_key: str, device_id: str, name: str) -> dict:
    return {"type": AUTH, "role": ROLE_AGENT, "network_key": network_key,
            "device_id": device_id, "name": name}


def auth_console(network_key: str) -> dict:
    return {"type": AUTH, "role": ROLE_CONSOLE, "network_key": network_key}


def auth_controller(network_key: str, device_id: str) -> dict:
    return {"type": AUTH, "role": ROLE_CONTROLLER, "network_key": network_key,
            "device_id": device_id}


# --- other messages -----------------------------------------------------------
def device_list(devices: list[dict]) -> dict:
    return {"type": DEVICE_LIST, "devices": devices}


def error(message: str) -> dict:
    return {"type": ERROR, "message": message}


def mouse(action: str, x: float = 0.0, y: float = 0.0,
          button: str = "left", dx: int = 0, dy: int = 0) -> dict:
    return {"type": INPUT_MOUSE, "action": action, "x": x, "y": y,
            "button": button, "dx": dx, "dy": dy}


def key(action: str, name: str) -> dict:
    return {"type": INPUT_KEY, "action": action, "name": name}


def config(fps: int | None = None, quality: int | None = None,
           scale: float | None = None) -> dict:
    m = {"type": CONFIG}
    if fps is not None:
        m["fps"] = fps
    if quality is not None:
        m["quality"] = quality
    if scale is not None:
        m["scale"] = scale
    return m


def preview(device_id: str, jpeg_b64: str) -> dict:
    """Dashboard thumbnail: JPEG as base64 so consoles can fan-in many devices."""
    return {"type": PREVIEW, "device_id": device_id, "jpeg": jpeg_b64}


def remove_device(device_id: str) -> dict:
    return {"type": REMOVE_DEVICE, "device_id": device_id}


def request_devices() -> dict:
    return {"type": REQUEST_DEVICES}


def alert(app: str, detail: str = "", device_id: str = "", device_name: str = "") -> dict:
    """Agent -> relay -> console: a watched app (e.g. wallet) appeared on a PC."""
    return {
        "type": ALERT,
        "kind": "watch_app",
        "device_id": device_id,
        "device_name": device_name,
        "app": app,
        "detail": detail,
    }


KEY_NAMES = {
    "enter", "esc", "tab", "backspace", "space", "delete", "insert",
    "home", "end", "page_up", "page_down",
    "up", "down", "left", "right",
    "ctrl", "alt", "shift", "cmd",
    "caps_lock", "num_lock", "print_screen", "pause", "menu",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8",
    "f9", "f10", "f11", "f12",
}
