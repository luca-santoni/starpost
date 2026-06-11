"""Logging setup. App logs go to stderr and to a rotating file in the cache dir."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from starpost.utils.paths import cache_dir

_CONFIGURED = False


def configure(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)

    file = RotatingFileHandler(
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
