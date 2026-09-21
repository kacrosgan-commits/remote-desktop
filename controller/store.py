"""Persistence for the controller: just the relay URL and network key.

Devices are discovered live from the relay, so there's no address book to
store anymore.
"""
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".remotedesk"
CONFIG_FILE = CONFIG_DIR / "controller.json"


def load() -> tuple[str, str]:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("relay", ""), data.get("network_key", "")
    except Exception:
        return "", ""


def save(relay: str, network_key: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"relay": relay, "network_key": network_key}, f, indent=2)
