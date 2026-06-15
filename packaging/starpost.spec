# Cross-platform PyInstaller spec for starpost. Build with:
#     pyinstaller packaging/starpost.spec
# Produces dist/starpost/ (a folder build). On Windows the launcher is
# starpost.exe; on Linux, an AppImage can be produced from the dist/ output for
# team distribution. PyInstaller does not cross-compile: build each OS's
# artifact on that OS.
# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

block_cipher = None
root = Path(SPECPATH).parent

# Per-OS app icon: .ico on Windows, the PNG elsewhere (ignored on Linux EXE,
# used by some packagers). macOS would use an .icns if/when supported.
_resources = root / "src" / "starpost" / "gui" / "resources"
if sys.platform == "win32":
    icon = str(_resources / "StarPost-logo.ico")
else:
    icon = str(_resources / "StarPost-logo.png")

a = Analysis(
    [str(root / "src" / "starpost" / "app.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[
        (str(root / "src" / "starpost" / "macros"), "starpost/macros"),
        (str(root / "src" / "starpost" / "gui" / "resources"), "starpost/gui/resources"),
        (str(root / "config" / "default_settings.yaml"), "config"),
    ],
    hiddenimports=["pyqtgraph", "matplotlib.backends.backend_agg"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="starpost", console=False, icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, name="starpost")
