# Packaging StarPost releases

This document covers building distributable StarPost artifacts for **Linux**
(a portable `.AppImage`) and **Windows** (a standalone `starpost.exe` bundle,
optionally wrapped in an installer).

Both platforms use **PyInstaller** to bundle the Python interpreter, Qt, and all
dependencies into a self-contained build, so end users need neither Python nor a
dependency install.

> **PyInstaller does not cross-compile.** Build each platform's artifact *on that
> platform* — the Linux AppImage on Linux, the Windows `.exe` on Windows.

---

## Prerequisites (both platforms)

On the **build machine**:

- **Python 3.11+**.
- A checkout of this repository, with the project and its dev extras installed
  into a virtual environment — the dev extras include PyInstaller:

  ```bash
  pip install -e ".[dev]"
  ```

  (See [`dev_install.md`](dev_install.md) for setting up the virtual
  environment.)

The version number stamped onto releases comes from `version` in
[`pyproject.toml`](../pyproject.toml).

---

## What gets bundled

The PyInstaller build is driven by [`packaging/starpost.spec`](../packaging/starpost.spec).
It is cross-platform and:

- Uses `src/starpost/app.py` as the entry point, with `src/` on the path.
- Bundles the non-code data the app needs at runtime:
  - `src/starpost/macros/` → `starpost/macros` (the Java macro templates),
  - `src/starpost/gui/resources/` → `starpost/gui/resources` (QSS, icons),
  - `config/default_settings.yaml` → `config` (first-run settings seed).
- Declares `hiddenimports` for `pyqtgraph` and the matplotlib Agg backend.
- Selects the app icon per OS: `StarPost-logo.ico` on Windows, `StarPost-logo.png`
  elsewhere.
- Builds a **folder bundle** (`COLLECT`), not a single file, and runs the app
  **windowed** (`console=False`).

The result is `dist/starpost/`, containing the launcher (`starpost` on Linux,
`starpost.exe` on Windows) plus its bundled runtime.

---

## Building the bundle (Linux & Windows)

From the repository root, with the virtual environment active:

```bash
pyinstaller packaging/starpost.spec
```

Output lands in `dist/starpost/`. On Windows this folder is already portable —
zip it up or feed it to an installer (below). On Linux, continue to the AppImage
step for a single-file artifact.

---

## Linux: AppImage

[`packaging/build_appimage.sh`](../packaging/build_appimage.sh) wraps the
PyInstaller bundle into a single portable `StarPost-<version>-<arch>.AppImage`
that runs on most Linux distributions with **no install and no Python on the
user's machine**.

### Build it

```bash
pip install -e ".[dev]"          # build host needs the deps + PyInstaller
packaging/build_appimage.sh      # → StarPost-<version>-x86_64.AppImage
```

Build for a non-host architecture by setting `ARCH`:

```bash
ARCH=aarch64 packaging/build_appimage.sh
```

### What the script does

1. **PyInstaller** — runs `pyinstaller --noconfirm packaging/starpost.spec` to
   produce `dist/starpost/` (and aborts if the bundle is missing).
2. **Assemble the AppDir** (`build/StarPost.AppDir`):
   - copies `dist/starpost/` into `usr/bin/`,
   - installs [`packaging/AppRun`](../packaging/AppRun) as the entry point (it
     resolves its own location and `exec`s `usr/bin/starpost`),
   - installs [`packaging/starpost.desktop`](../packaging/starpost.desktop) and
     the icon (`StarPost-logo.png`) at the AppDir root and under the usual
     `usr/share/` locations.
3. **Pack with appimagetool** — uses `appimagetool` from `PATH` if present,
   otherwise downloads it from the AppImage project, then packs the AppDir with
   `--appimage-extract-and-run` (so no working FUSE mount is needed).

The version is read automatically from `pyproject.toml`; the output is
`StarPost-<version>-<arch>.AppImage` in the repo root.

### Requirements & gotchas

- **Build on the oldest glibc you must support.** glibc is forward- but not
  backward-compatible, so an AppImage built on a new distro may refuse to start
  on older ones. Building in an old container (e.g. an older Ubuntu LTS) gives
  the widest reach.
- Needs **`curl`** and internet on the build host (to fetch `appimagetool`),
  unless `appimagetool` is already on `PATH`.
- **FUSE is not required** on the build host (the script uses
  `--appimage-extract-and-run`).
- The bundling intentionally uses `appimagetool` directly rather than
  `linuxdeploy-plugin-qt`: PyInstaller's PySide6 hook already bundles Qt and its
  plugins, and the Qt plugin on top would double-bundle and can conflict.

### End-user run

```bash
chmod +x StarPost-*.AppImage
./StarPost-*.AppImage
```

---

## Windows: standalone bundle and installer

Build the bundle on Windows (PowerShell or Command Prompt), with the dev extras
installed:

```powershell
pip install -e ".[dev]"
pyinstaller packaging\starpost.spec
```

This produces `dist\starpost\`, containing `starpost.exe` and its runtime. The
spec automatically uses the Windows `.ico` for the executable icon. The folder
is **portable as-is** — it can be zipped and shipped, and runs without
installing Python.

### Installer: Inno Setup `Setup.exe`

The portable folder is the baseline artifact, but the repository now ships an
**Inno Setup** script — [`packaging/starpost.iss`](../packaging/starpost.iss) —
that wraps `dist\starpost\` into a single `Setup.exe`.

#### Prerequisite

[Inno Setup 6](https://jrsoftware.org/isdl.php) on the build machine (provides
the `ISCC.exe` command-line compiler). Install it once, e.g.:

```powershell
winget install JRSoftware.InnoSetup
```

A user-scope winget install places the compiler at
`%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`; a machine-wide install puts it
under `%ProgramFiles(x86)%\Inno Setup 6\`. `ISCC.exe` is not added to `PATH` by
default, so call it by full path (or add it to `PATH` yourself).

#### Build it

After the PyInstaller bundle exists (`dist\starpost\`), from the repo root:

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.1.0 packaging\starpost.iss
```

The result is `dist\StarPost-<version>-Setup.exe` (LZMA-compressed; the ~215 MB
bundle compresses to ~68 MB). **The installer must be named
`StarPost-<version>-Setup.exe`** (e.g. `StarPost-1.1.0-Setup.exe`); this is
produced automatically by the `OutputBaseFilename` in
[`starpost.iss`](../packaging/starpost.iss), so keep that setting in the format
`StarPost-{#MyAppVersion}-Setup`. Running it installs per-machine into
`C:\Program Files\StarPost` (requires elevation / UAC), shows the `LICENSE`,
creates a Start-menu shortcut (plus an optional, unchecked desktop shortcut),
registers an uninstaller in *Add/Remove Programs*, and offers to launch the app.

The version defaults to `1.1.0` inside the script but **should be passed on the
command line** (`/DMyAppVersion=<version>`) to match `version` in
[`pyproject.toml`](../pyproject.toml). The script's `AppId` GUID is fixed — do
not change it, or upgrades and uninstall will break for existing installs.

#### Code signing

`starpost.exe` and the generated `Setup.exe` are **unsigned**, so Windows
SmartScreen / UAC shows an "unknown publisher" warning on first run. To remove
it, sign both with a code-signing certificate (e.g. `signtool sign /fd SHA256`)
— sign `dist\starpost\starpost.exe` *before* compiling the installer, then sign
the resulting `Setup.exe`.

#### Alternative: WiX `.msi`

For managed/MSI-based deployment (Group Policy, Intune), author an `.msi` from
the same `dist\starpost\` contents with the **WiX Toolset**. The repository does
not ship a WiX project.

---

## Release checklist

1. Bump the version in **both** places, keeping them identical:
   - `version` in [`pyproject.toml`](../pyproject.toml) (the AppImage name and
     installer metadata derive from it), and
   - `__version__` in [`src/starpost/__init__.py`](../src/starpost/__init__.py)
     (what the running app reports and what the in-app updater compares against
     the latest GitHub release tag).

   If these drift, the in-app update check misbehaves — e.g. an installer built
   as `1.2.0` while the app still reports `1.1.0` would keep offering an "update"
   to a version that's already installed. (A future cleanup could make
   `pyproject.toml` read the version from `__init__.py` so there's a single
   source of truth.)
2. On **Linux**: run `packaging/build_appimage.sh` → `StarPost-<version>-<arch>.AppImage`.
3. On **Windows**: run `pyinstaller packaging\starpost.spec`, then build the
   installer with
   `ISCC.exe /DMyAppVersion=<version> packaging\starpost.iss` →
   `dist\StarPost-<version>-Setup.exe` (or just zip `dist\starpost\` for the
   portable build). Pass the same `<version>` as in `pyproject.toml`.
4. Smoke-test each artifact on a clean machine (the AppImage on an older distro;
   the Windows build on a machine without Python).
5. Publish both to the GitHub **Releases** page so the
   [README install instructions](../README.md#installation) point users at them.
