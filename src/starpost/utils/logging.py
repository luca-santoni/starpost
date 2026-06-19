"""Logging setup. App logs go to stderr and to a rotating file in the cache dir."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from starpost.utils.paths import cache_dir, harden_file

_CONFIGURED = False


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that keeps its log files owner-only (0600).

    Logs can contain sensitive paths and identifiers, so every file the handler
    opens — the active log and each one created after a rollover — is locked
    down. (A rollover renames the current file, which preserves its mode, then
    opens a fresh one through here, so masking on open covers them all.)
    """

    def _open(self):
        stream = super()._open()
        harden_file(self.baseFilename)
        return stream


def configure(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)

    file = _PrivateRotatingFileHandler(
        cache_dir() / "starpost.log", maxBytes=1_000_000, backupCount=3
    )
    file.setFormatter(fmt)

    root = logging.getLogger("starpost")
    root.setLevel(level)
    root.addHandler(stream)
    root.addHandler(file)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"starpost.{name}")
