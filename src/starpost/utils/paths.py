"""Per-user locations for config, cache, and profiles.

Uses platformdirs so each OS gets its native location: on Linux this resolves
to the same XDG paths as before (~/.config/starpost, ~/.cache/starpost, and
honoring XDG_CONFIG_HOME/XDG_CACHE_HOME); on Windows it maps to %APPDATA% and
%LOCALAPPDATA%.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import platformdirs

from starpost import APP_NAME


def harden_file(path: Path) -> None:
    """Restrict ``path`` to owner read/write only (0600).

    Used for files that can hold sensitive data (the settings file's license
    credentials, the log). Best-effort: silently ignores filesystems that don't
    support POSIX permissions (e.g. some Windows setups), where the OS already
    scopes the per-user config/cache locations to the account.
    """
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def config_dir() -> Path:
    return _ensure(Path(platformdirs.user_config_dir(APP_NAME)))


def cache_dir() -> Path:
    return _ensure(Path(platformdirs.user_cache_dir(APP_NAME)))


def profiles_dir() -> Path:
    return _ensure(config_dir() / "profiles")


def settings_path() -> Path:
    return config_dir() / "settings.yaml"


def results_cache_path() -> Path:
    """Crash-recovery cache of extracted results."""
    return cache_dir() / "results_cache.json"


def file_list_cache_path() -> Path:
    """Persisted batch list of .sim files shown in the left panel."""
    return cache_dir() / "file_list.json"


def packaged_default_settings() -> Path:
    """The default_settings.yaml shipped with the repo/package."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: the spec stages config/ next to the unpacked
        # tree under sys._MEIPASS.
        return Path(sys._MEIPASS) / "config" / "default_settings.yaml"  # type: ignore[attr-defined]
    # repo layout: <root>/config/default_settings.yaml ; this file is
    # <root>/src/starpost/utils/paths.py
    return Path(__file__).resolve().parents[3] / "config" / "default_settings.yaml"


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    # These are per-user app dirs holding the settings (license credentials),
    # profiles and logs; keep them private to the owner. Best-effort, as with
    # harden_file().
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p
