"""Decode-at-thumbnail-size icon cache shared by the media galleries.

Decoding a (potentially 4K) image straight to thumbnail resolution is cheap;
caching by path + mtime means rebuilding a gallery doesn't re-decode every
image from disk each time.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImageReader, QPixmap


class ThumbnailCache:
    """path -> (mtime, QIcon) cache of thumbnail-sized icons."""

    def __init__(self, edge: int) -> None:
        self._edge = edge
        self._cache: dict[str, tuple[float, QIcon]] = {}

    def icon(self, path: str) -> QIcon | None:
        """A thumbnail-sized QIcon for ``path``, decoded directly at thumbnail
        resolution (cheap for large images) and cached by path + mtime.
        Returns None if the file can't be read."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        cached = self._cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()  # reads the header only — cheap
        if size.isValid() and not size.isEmpty():
            # Decode straight to the thumbnail box (keeping aspect), so a
            # 3840×2160 image isn't fully decoded just to shrink to ~220 px.
            scaled = size.scaled(
                QSize(self._edge, self._edge),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            if not scaled.isEmpty():
                reader.setScaledSize(scaled)
        image = reader.read()
        if image.isNull():
            return None
        icon = QIcon(QPixmap.fromImage(image))
        self._cache[path] = (mtime, icon)
        return icon
