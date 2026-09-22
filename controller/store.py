"""Persistence for the controller: relay URL, network key, and hidden devices."""
import json
import shutil
from pathlib import Path

import branding

CONFIG_DIR = Path.home() / branding.CONFIG_DIRNAME
LEGACY_CONFIG_DIR = Path.home() / branding.LEGACY_CONFIG_DIRNAME
CONFIG_FILE = CONFIG_DIR / "controller.json"


def _migrate_legacy_config():
    """Copy settings from the old RemoteDesk folder once."""
    legacy = LEGACY_CONFIG_DIR / "controller.json"
    if CONFIG_FILE.exists() or not legacy.exists():
        return
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, CONFIG_FILE)
    except OSError:
        pass


def load() -> tuple[str, str]:
    _migrate_legacy_config()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("relay", ""), data.get("network_key", "")
    except Exception:
        return "", ""


def load_hidden() -> set[str]:
    _migrate_legacy_config()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        hidden = data.get("hidden_devices", [])
        if isinstance(hidden, list):
            return {str(x) for x in hidden}
    except Exception:
        pass
    return set()


def save(relay: str, network_key: str, hidden_devices: set[str] | None = None) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing_hidden: list[str] = []
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            existing_hidden = list(json.load(f).get("hidden_devices", []))
    except Exception:
        pass
    if hidden_devices is not None:
        existing_hidden = sorted(hidden_devices)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"relay": relay, "network_key": network_key,
             "hidden_devices": existing_hidden},
            f, indent=2,
        )


def hide_device(device_id: str) -> set[str]:
    hidden = load_hidden()
    hidden.add(device_id)
    relay, key = load()
    save(relay, key, hidden)
    return hidden


def unhide_device(device_id: str) -> set[str]:
    hidden = load_hidden()
    hidden.discard(device_id)
    relay, key = load()
    save(relay, key, hidden)
    return hidden


def clear_hidden() -> set[str]:
    relay, key = load()
    save(relay, key, set())
    return set()
