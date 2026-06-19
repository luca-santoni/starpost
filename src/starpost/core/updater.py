"""Self-update backend: check GitHub Releases for a newer version and fetch the
Windows installer.

This module is deliberately UI-free and depends only on the standard library, so
it works inside the PyInstaller bundle with no extra packages. The Qt glue
(threading, progress dialog, prompts) lives in ``starpost.gui.update``.

Update model (see docs/packaging.md): releases are published on GitHub with a
``StarPost-<version>-Setup.exe`` Inno Setup installer asset. We compare the
latest release tag against the running version; if newer, we download that
installer and run it. The installer upgrades in place (same AppId) and leaves
user data in %APPDATA%/%LOCALAPPDATA% untouched.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from starpost import __version__

# The public repository releases are read from. Kept here so there is a single
# source of truth for the updater's target.
REPO = "luca-santoni/starpost"
_API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
_RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
_USER_AGENT = f"StarPost/{__version__} (auto-updater)"

# Network timeouts (seconds). The metadata request is small; the download uses a
# longer per-read timeout because the installer is tens of MB.
_META_TIMEOUT = 15
_DOWNLOAD_TIMEOUT = 60

# A progress callback receives (bytes_done, total_bytes); returning False asks
# the download to abort (it then raises UpdateCancelled).
ProgressCallback = Callable[[int, int], object]


class UpdateError(Exception):
    """Any failure while checking for or downloading an update."""


class UpdateCancelled(Exception):
    """Raised when a download is cancelled via its progress callback."""


@dataclass(frozen=True)
class UpdateInfo:
    """Details of an available newer release."""

    current: str          # the running version, e.g. "1.1.0"
    latest: str           # the latest release version, e.g. "1.2.0"
    asset_name: str       # e.g. "StarPost-1.2.0-Setup.exe"
    download_url: str      # direct browser_download_url for the installer asset
    size: int             # asset size in bytes (0 if unknown)
    sha256: str           # expected hex digest, or "" if the API didn't expose one
    release_url: str      # the human-facing release page
    notes: str            # the release body / changelog (may be empty)


# --------------------------------------------------------------------------- #
# Version handling
# --------------------------------------------------------------------------- #
def current_version() -> str:
    """The version of the running application."""
    return __version__


def _parse_version(text: str) -> tuple[int, ...]:
    """Turn a version/tag string into a comparable tuple of ints.

    Tolerant of a leading ``v`` and of pre-release/build suffixes: only the
    leading dotted-numeric part is used (``"v1.2.3-rc1"`` -> ``(1, 2, 3)``).
    """
    core = re.split(r"[^0-9.]", text.strip().lstrip("vV"), maxsplit=1)[0]
    parts = tuple(int(p) for p in core.split(".") if p.isdigit())
    return parts or (0,)


def is_newer(latest: str, current: str) -> bool:
    """True if ``latest`` is a strictly newer version than ``current``."""
    a, b = _parse_version(latest), _parse_version(current)
    # Pad to equal length so 1.1 and 1.1.0 compare equal rather than 1.1 < 1.1.0.
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return a > b


# --------------------------------------------------------------------------- #
# Capability checks
# --------------------------------------------------------------------------- #
def can_self_update() -> bool:
    """Whether this build can apply an update by running the installer.

    Only the frozen Windows build is installed via ``Setup.exe``; running from a
    source checkout (or on Linux) can still *check*, but applies updates by
    opening the releases page instead.
    """
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


# --------------------------------------------------------------------------- #
# Checking
# --------------------------------------------------------------------------- #
def _get_json(url: str, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https)
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Could not reach the update server: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise UpdateError("Unexpected response from the update server.") from exc


def _select_installer_asset(assets: list[dict]) -> Optional[dict]:
    """Pick the Windows installer asset (``StarPost-<version>-Setup.exe``)."""
    for asset in assets:
        name = str(asset.get("name", ""))
        if name.lower().endswith("setup.exe"):
            return asset
    return None


def check_for_update(timeout: int = _META_TIMEOUT) -> Optional[UpdateInfo]:
    """Query the latest release. Return an :class:`UpdateInfo` if a newer version
    is available, ``None`` if already up to date. Raises :class:`UpdateError` on
    any network/parse failure."""
    data = _get_json(_API_LATEST, timeout)
    latest = str(data.get("tag_name", "")).lstrip("vV")
    if not latest:
        raise UpdateError("The latest release has no version tag.")

    current = current_version()
    if not is_newer(latest, current):
        return None

    asset = _select_installer_asset(data.get("assets") or [])
    if asset is None:
        raise UpdateError(
            "A newer release exists but has no Windows installer asset."
        )

    # GitHub exposes a "digest" like "sha256:abcd..." on assets when available.
    digest = str(asset.get("digest", ""))
    sha256 = digest.split(":", 1)[1] if digest.lower().startswith("sha256:") else ""

    return UpdateInfo(
        current=current,
        latest=latest,
        asset_name=str(asset["name"]),
        download_url=str(asset["browser_download_url"]),
        size=int(asset.get("size") or 0),
        sha256=sha256,
        release_url=str(data.get("html_url") or _RELEASES_PAGE),
        notes=str(data.get("body") or "").strip(),
    )


# --------------------------------------------------------------------------- #
# Downloading
# --------------------------------------------------------------------------- #
def download_asset(
    info: UpdateInfo,
    dest_dir: Path,
    progress: Optional[ProgressCallback] = None,
    timeout: int = _DOWNLOAD_TIMEOUT,
) -> Path:
    """Download the installer for ``info`` into ``dest_dir`` and return its path.

    Verifies the SHA-256 digest when the release exposed one. If ``progress`` is
    given it is called as ``progress(done, total)``; returning ``False`` from it
    cancels the download (raising :class:`UpdateCancelled`). The partial file is
    removed on cancel or failure.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / info.asset_name

    req = urllib.request.Request(info.download_url, headers={"User-Agent": _USER_AGENT})
    hasher = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https)
            total = int(resp.headers.get("Content-Length") or info.size or 0)
            done = 0
            with open(dest, "wb") as out:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    hasher.update(chunk)
                    done += len(chunk)
                    if progress is not None and progress(done, total) is False:
                        raise UpdateCancelled()
    except UpdateCancelled:
        dest.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc}") from exc

    if info.sha256 and hasher.hexdigest().lower() != info.sha256.lower():
        dest.unlink(missing_ok=True)
        raise UpdateError("The downloaded installer failed integrity verification.")
    return dest


def default_download_dir() -> Path:
    """Where downloaded installers are cached (under the per-OS cache dir)."""
    from starpost.utils.paths import cache_dir

    return cache_dir() / "updates"


# --------------------------------------------------------------------------- #
# Applying
# --------------------------------------------------------------------------- #
def launch_installer(installer: Path) -> None:
    """Start the downloaded installer as a detached process.

    The caller is expected to quit the application shortly afterwards so the
    installer can replace the program files. The Inno Setup installer
    (CloseApplications) will close a still-running instance if needed, then
    relaunch StarPost when it finishes.
    """
    if sys.platform != "win32":
        raise UpdateError("The installer can only be run on Windows.")
    installer = Path(installer)
    if not installer.exists():
        raise UpdateError(f"Installer not found: {installer}")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen([str(installer)], close_fds=True, creationflags=flags)
