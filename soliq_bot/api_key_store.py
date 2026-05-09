"""Gemini API key storage: embedded default + persisted custom key cache.

* Embedded default → `soliq_bot/_default_key.py` (DEFAULT_GEMINI_API_KEY).
  Clients use this out of the box. If absent, falls back to GEMINI_API_KEY env.

* Custom key → end users can enter their own key in the GUI; we save it
  to `~/.soliq_bot/custom_key.txt` (chmod 600) so they do not have to
  re-enter on every launch.
"""
from __future__ import annotations

import os
from pathlib import Path

CACHE_DIR = Path.home() / ".soliq_bot"
CACHE_FILE = CACHE_DIR / "custom_key.txt"


def get_default_key() -> str:
    """Return the embedded default Gemini API key, or empty string."""
    try:
        from ._default_key import DEFAULT_GEMINI_API_KEY  # type: ignore
    except Exception:  # noqa: BLE001
        DEFAULT_GEMINI_API_KEY = ""
    if DEFAULT_GEMINI_API_KEY:
        return DEFAULT_GEMINI_API_KEY
    return os.environ.get("GEMINI_API_KEY", "")


def has_default_key() -> bool:
    return bool(get_default_key())


def load_custom_key() -> str:
    """Load the user-cached custom API key (or empty string)."""
    try:
        return CACHE_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except Exception:  # noqa: BLE001
        return ""


def save_custom_key(key: str) -> None:
    """Persist a custom API key to the cache file (chmod 600)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text((key or "").strip(), encoding="utf-8")
    try:
        os.chmod(CACHE_FILE, 0o600)
    except Exception:  # noqa: BLE001
        pass


def clear_custom_key() -> None:
    """Remove the cached custom API key file, if it exists."""
    try:
        CACHE_FILE.unlink()
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        pass
