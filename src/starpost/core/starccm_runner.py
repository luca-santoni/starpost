"""Drives the STAR-CCM+ executable in batch mode for one .sim at a time.

Command shape:
    <starccm_path> -batch <macro.java> <license args> <extra args> <file.sim>

License args come from Settings.license (default: -power -podkey <KEY>
-licpath <port>@<server>). Runs are sequential elsewhere (batch/queue.py) so at
most one license is checked out at a time.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

from starpost.core.macro_generator import render_macro
from starpost.core.result_parser import parse_sim_output
from starpost.core.settings import Settings
from starpost.data.models import SimResult
from starpost.utils.logging import get_logger

log = get_logger("runner")

LogSink = Callable[[str], None]


def exe_placeholder() -> str:
    """Placeholder text for the STAR-CCM+ executable field, per platform."""
    if sys.platform == "win32":
        return r"C:\Program Files\Siemens\...\star\bin\starccm+.bat"
    return "/path/to/starccm+"


def exe_dialog_filter() -> str:
    """QFileDialog name filter for picking the STAR-CCM+ launcher.

    On Windows the launcher is starccm+.bat (or .exe); narrowing the dialog to
    those saves the user hunting. Empty on Linux, where the binary has no
    extension and any file should be selectable.
    """
    if sys.platform == "win32":
        return "STAR-CCM+ launcher (starccm+.bat starccm+.exe);;All files (*.*)"
    return ""


# Flags whose immediately-following argument is a license secret (the POD key,
# the license server, or the license-file path). Their values must never reach
# the log file, the on-screen console, or any captured output.
_SECRET_FLAGS = ("-podkey", "-licpath")
_REDACTED = "***"


def redact_command(cmd: list[str]) -> str:
    """Render ``cmd`` for display/logging with license secrets masked.

    The argument following any flag in :data:`_SECRET_FLAGS` (the POD key and the
    license server/-file) is replaced with a placeholder, so credentials are
    never written to the log file or shown in the GUI console. The real command
    passed to the subprocess is left untouched.
    """
    out: list[str] = []
    redact_next = False
    for token in cmd:
        if redact_next:
            out.append(_REDACTED)
            redact_next = False
        else:
            out.append(token)
            if token in _SECRET_FLAGS:
                redact_next = True
    return " ".join(out)


class StarRunError(Exception):
    pass


class StarRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_command(self, macro: Path, sim_file: Path) -> list[str]:
        exe = self.settings.starccm_path
        if not exe:
            raise StarRunError("STAR-CCM+ executable path is not configured.")
        cmd = [exe, "-batch", str(macro)]
        cmd += self.settings.license.cli_args()
        cmd += list(self.settings.extra_args)
        cmd += [str(sim_file)]
        return cmd

    def extract(
        self,
        sim_file: Path,
        output_dir: Path,
        log_sink: Optional[LogSink] = None,
    ) -> SimResult:
        """Run the macro on one .sim and parse the exported CSVs into a result."""
        output_dir.mkdir(parents=True, exist_ok=True)
        sink = log_sink or (lambda s: None)

        with tempfile.TemporaryDirectory(prefix="starpost_macro_") as tmp:
            macro = render_macro(output_dir, Path(tmp))
            cmd = self.build_command(macro, sim_file)
            # Mask the POD key / license server before this command reaches the
            # GUI console or the log file; the subprocess still gets the real cmd.
            shown = redact_command(cmd)
            sink(f"$ {shown}")
            log.info("running: %s", shown)

            code = self._stream(cmd, sink)
            if code != 0:
                msg = f"starccm+ exited with code {code} for {sim_file.name}"
                sink(msg)
                return SimResult(sim_path=str(sim_file), error=msg)

        result = parse_sim_output(
            str(sim_file), output_dir, self.settings.plot_classification
        )
        sink(f"Parsed {len(result.reports)} reports, {len(result.plots)} plots "
             f"from {sim_file.name}")
        return result

    def _stream(self, cmd: list[str], sink: LogSink) -> int:
        """Run cmd, forwarding combined stdout/stderr to the sink line by line."""
        # On Windows the GUI build has no console, so each child STAR-CCM+
        # process would otherwise flash its own console window. Suppress it.
        creationflags = (
            subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creationflags,
            )
        except FileNotFoundError as e:
            raise StarRunError(f"Could not launch '{cmd[0]}': {e}") from e

        assert proc.stdout is not None
        for line in proc.stdout:
            sink(line.rstrip("\n"))
        return proc.wait()
