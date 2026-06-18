# Running StarPost from source

This guide covers running StarPost **as a Python script straight out of the
downloaded repository folder** — no packaging, no system install. This is the
recommended path for development and for trying the app from a checkout.

If instead you want a standalone build (PyInstaller bundle or a Linux AppImage),
see the *Packaging* section of the [README](../README.md).

---

## 1. Prerequisites

- **Python 3.11 or newer** (3.11+ is required; verify with `python3 --version`).
- **pip** and the **venv** module (bundled with Python on most systems; on
  Debian/Ubuntu you may need `sudo apt install python3-venv`).
- **git** — optional, only if you clone rather than download a ZIP.
- **A licensed STAR-CCM+ installation** — *optional for running the app*. The
  GUI opens and is fully navigable without one; STAR-CCM+ is only needed to
  actually extract data from `.sim` files (its executable path is set in
  **Settings**).

Works on **Linux** and **Windows**.

---

## 2. Get the repository

Clone it:

```bash
git clone <repository-url> starpost
cd starpost
```

…or download the repository ZIP from your host, extract it, and `cd` into the
extracted folder. All commands below are run **from the repository root** (the
folder containing `pyproject.toml` and the `src/` directory).

---

## 3. Create and activate a virtual environment

A virtual environment keeps StarPost's dependencies isolated from your system
Python.

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Windows (PowerShell or Command Prompt)

```powershell
py -m venv .venv
.venv\Scripts\activate
```

Once activated, your shell prompt shows `(.venv)`. Run the remaining steps with
the environment active. Use `deactivate` to leave it later.

---

## 4. Install the dependencies

Pick **one** of the following from the repository root.

**Editable install with dev tools (recommended):** installs StarPost and its
dependencies plus the development extras (`pytest`, `ruff`, `pyinstaller`):

```bash
pip install -e ".[dev]"
```

**Runtime dependencies only:** if you don't need the dev tools:

```bash
pip install -r requirements.txt
```

The same dependencies (PySide6, pyqtgraph, numpy, matplotlib, pandas, …) install
on both Linux and Windows.

---

## 5. Run the program

The repository ships a launcher script that runs the GUI directly from `src/`
without needing the package on your `PYTHONPATH`:

```bash
python scripts/dev_run.py
```

That's it — the StarPost window should open.

### Alternative ways to launch

These are equivalent and handy depending on your setup:

- **As a module** (requires the editable install from step 4, or `src/` on your
  `PYTHONPATH`):

  ```bash
  python -m starpost.app
  ```

- **Console entry point** (created by `pip install -e .`):

  ```bash
  starpost
  ```

All three call the same entry point, `starpost.app:main`.

---

## 6. Run the tests (optional)

With the dev extras installed (step 4, editable install), run the test suite
from the repository root:

```bash
python -m pytest
```

To lint the code with the project's configured rules:

```bash
ruff check .
```

---

## 7. Where settings and data live

StarPost stores its configuration and caches **outside** the repository, in the
per-OS locations chosen by `platformdirs`:

- Settings — Linux: `~/.config/starpost/settings.yaml`,
  Windows: `%APPDATA%\starpost\settings.yaml`
- Cache & logs — Linux: `~/.cache/starpost/`,
  Windows: `%LOCALAPPDATA%\starpost\`

The file is seeded from [`config/default_settings.yaml`](../config/default_settings.yaml)
on first run. Deleting the settings file resets the app to defaults. See the
[README](../README.md#configuration) for the full configuration reference.

---

## Troubleshooting

- **`python3 -m venv` fails on Linux** — install your distro's venv package,
  e.g. `sudo apt install python3-venv` on Debian/Ubuntu.
- **`ModuleNotFoundError: No module named 'starpost'`** — make sure the virtual
  environment is active and dependencies are installed (step 4). The
  `scripts/dev_run.py` launcher adds `src/` to the path for you; `python -m
  starpost.app` requires the editable install or `src/` on `PYTHONPATH`.
- **Qt/PySide6 fails to start with a display error** — the GUI needs a graphical
  session. On a headless machine you won't be able to open the window; this is
  expected.
- **Wrong Python version** — confirm `python --version` reports 3.11+ inside the
  activated virtual environment.
