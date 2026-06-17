"""
RemarkableSync configuration management.

Handles loading, saving, and interactive editing of user configuration.
Config is stored as JSON at ~/.config/remarkablesync/config.json (Linux/macOS)
or %APPDATA%/remarkablesync/config.json (Windows).
"""

import json
import platform
from pathlib import Path
from typing import Any, Dict

from src.__version__ import __version__

# Minimum config version required. Bump this when config format changes
# in a way that requires user to re-run the config wizard.
MIN_CONFIG_VERSION = "2.1.0"


def get_config_dir() -> Path:
    """Return the platform-appropriate config directory."""
    if platform.system() == "Windows":
        base = Path.home() / "AppData" / "Roaming"
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    return base / "remarkablesync"


def get_log_dir() -> Path:
    """Return the log directory."""
    return get_config_dir() / "logs"


def get_config_path() -> Path:
    """Return the full path to the config file."""
    return get_config_dir() / "config.json"


def _default_backup_dir() -> str:
    """Return the default backup directory inside the app data folder."""
    return str(get_config_dir() / "backup")


def _default_documents_dir() -> Path:
    """Return the user's Documents directory."""
    if platform.system() == "Windows":
        return Path.home() / "Documents"
    elif platform.system() == "Darwin":
        return Path.home() / "Documents"
    else:
        return Path.home() / "Documents"


# Default configuration values
DEFAULT_CONFIG: Dict[str, Any] = {
    "connection_mode": "usb",
    "wifi_host": "",
    "password": "",
    "folders": [],
    "sync_actions": ["backup", "pdf", "ocr"],
    "ocr_enabled": False,
    "ocr_output_dir": "",
    "output_dir": "",
    "embed_images": True,
    "pdf_dir": "",
    "ai_provider": "github",
    "ai_model": "",
    "ocr_custom_instructions": "",
    "pre_sync_command": "",
    "post_sync_command": "",
}


def get_custom_instructions_path() -> Path:
    """Return the default path for custom OCR instructions."""
    return get_config_dir() / "custom_instructions.md"


def load_custom_instructions() -> str:
    """Load custom OCR instructions from config path or default location.

    Returns:
        Custom instructions text, or empty string if not found.
    """
    config = load_config()
    custom_path = config.get("ocr_custom_instructions", "")

    # Use configured path or fall back to default
    if custom_path:
        path = Path(custom_path)
    else:
        path = get_custom_instructions_path()

    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


# All available sync actions
SYNC_ACTIONS = [
    ("backup", "Backup tablet files"),
    ("pdf", "PDF Conversion"),
    ("ocr", "AI Handwriting OCR & MD Export"),
]


def load_config() -> Dict[str, Any]:
    """Load config from disk, returning defaults if file doesn't exist."""
    path = get_config_path()
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "output_dir" not in data and "vault_dir" in data:
            data["output_dir"] = data["vault_dir"]
        data.pop("vault_dir", None)

        # Merge with defaults so new keys are always present
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)

        # Cascade-normalize sync_actions: if a later step is present,
        # all earlier steps must be too (e.g. "pdf" implies "backup").
        _action_order = [a for a, _ in SYNC_ACTIONS]
        actions = merged.get("sync_actions", [])
        valid = [a for a in actions if a in _action_order]
        if valid:
            highest = max(_action_order.index(a) for a in valid)
            merged["sync_actions"] = _action_order[: highest + 1]

        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(config: Dict[str, Any]) -> Path:
    """Save config to disk with version stamp. Returns the path written."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Stamp the config with current version
    config["config_version"] = __version__
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return path


def _parse_version(version_str: str) -> tuple:
    """Parse version string into tuple for comparison."""
    try:
        parts = version_str.split(".")
        return tuple(int(p) for p in parts[:3])
    except (ValueError, AttributeError):
        return (0, 0, 0)


def check_config_version() -> tuple[bool, str]:
    """Check if the current config is compatible with this version.

    Returns:
        Tuple of (is_valid, message). If is_valid is False, user should
        re-run the config command.
    """
    config = load_config()
    config_version = config.get("config_version", "0.0.0")

    current = _parse_version(config_version)
    minimum = _parse_version(MIN_CONFIG_VERSION)

    if current < minimum:
        return False, (
            f"Your configuration (v{config_version}) is outdated.\n"
            f"This version requires config v{MIN_CONFIG_VERSION} or newer.\n"
            f"Please run: remarkablesync config"
        )
    return True, ""
