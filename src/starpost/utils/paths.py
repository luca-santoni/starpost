"""XDG-aware locations for config, cache, and profiles.

Linux-native today; the XDG fallbacks below are also reasonable on other
platforms, so Windows support later mostly means swapping these for
platformdirs.
"""
from __future__ import annotations

import os
from pathlib import Path

from starpost import APP_NAME


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return _ensure(Path(base) / APP_NAME)


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return _ensure(Path(base) / APP_NAME)


def profiles_dir() -> Path:
    return _ensure(config_dir() / "profiles")


def settings_path() -> Path:
    return config_dir() / "settings.yaml"


def results_cache_path() -> Path:
    """Crash-recovery cache of extracted results."""
    return cache_dir() / "results_cache.json"


def packaged_default_settings() -> Path:
    """The default_settings.yaml shipped with the repo/package."""
    # repo layout: <root>/config/default_settings.yaml ; this file is
    # <root>/src/starpost/utils/paths.py
    return Path(__file__).resolve().parents[3] / "config" / "default_settings.yaml"


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p
