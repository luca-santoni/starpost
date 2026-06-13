# PyInstaller spec for starpost (Linux). Build with:  pyinstaller packaging/starpost.spec
# Later: produce an AppImage from the dist/ output for team distribution.
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None
root = Path(SPECPATH).parent

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
    name="starpost", console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="starpost")
