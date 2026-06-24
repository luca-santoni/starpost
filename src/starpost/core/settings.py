"""Application settings + profiles, persisted as YAML.

Settings = how to run STAR-CCM+ (exe path, licensing, output dir).
Profile   = which reports/plots a user wants to export, reusable across files.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from starpost.utils.paths import (
    harden_file,
    packaged_default_settings,
    profiles_dir,
    settings_path,
)


# UI text-size multiplier bounds. 1.0 keeps the original size (the default); the
# upper bound caps how large the program-wide text can grow.
MIN_TEXT_SCALE = 1.0
MAX_TEXT_SCALE = 1.5


def clamp_text_scale(value: float) -> float:
    """Coerce ``value`` to a valid text-size multiplier, falling back to 1.0 for
    anything non-numeric, and clamping into [MIN_TEXT_SCALE, MAX_TEXT_SCALE]."""
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return MIN_TEXT_SCALE
    return max(MIN_TEXT_SCALE, min(MAX_TEXT_SCALE, scale))


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@dataclass
class AppearanceConfig:
    mode: str = "dark"          # "dark" | "light"
    accent: str = "#ffc829"     # hex accent colour applied program-wide
    checkmark_color: str = "#ffc829"     # hex colour of checkmarks program-wide
    checkmark_match_theme: bool = True   # force checkmark colour to the accent
    folder_color: str = "#ffc829"        # hex tint for Files-tab folder icons
    folder_use_default: bool = True      # keep the standard (untinted) folder icon
    # UI text-size multiplier applied to every button/label. 1.0 is the original
    # size (the default); larger values enlarge the text program-wide.
    text_scale: float = 1.0

    def resolved_checkmark(self) -> str:
        """The checkmark colour actually used: the accent when matching the
        theme, otherwise the explicit checkmark colour."""
        return self.accent if self.checkmark_match_theme else self.checkmark_color

    def resolved_folder_color(self) -> str:
        """The folder tint in effect: empty (the standard folder icon) when
        using the default, otherwise the chosen colour."""
        return "" if self.folder_use_default else self.folder_color


@dataclass
class MediaConfig:
    """How scene stills are rendered (resolution + magnification + parallelism).

    ``render_np`` is the number of cores used to render scenes, passed to
    starccm+'s ``-np``: 1 renders serially (the default), and 2..N partitions the
    case across that many ranks (faster and far less memory per rank). N is the
    machine's core count, enforced by the Settings spinbox.

    ``scenes_per_checkout`` is how many scenes are rendered per STAR-CCM+ session
    (one license checkout, the sim loaded once): 1 (the default) renders each
    scene in its own checkout — safest for memory — while higher values batch
    that many scenes per checkout to cut license churn and repeated sim loads, at
    the cost of more memory accumulating within a session.

    ``image_format`` is the rendered image file type ("jpg" or "png"); it sets the
    output file extension, which STAR-CCM+ uses to pick the format.

    ``image_resolution`` is the render resolution ("1080p" or "2160p"), mapped to
    pixel dimensions by :data:`IMAGE_RESOLUTIONS`.

    Defaults to 1080p JPG at 1× magnification."""
    magnification: int = 1
    render_np: int = 1   # cores for parallel rendering; 1 == serial
    scenes_per_checkout: int = 1   # scenes rendered per license checkout
    image_format: str = "jpg"   # rendered image type: "jpg" | "png"
    image_resolution: str = "1080p"   # render resolution: "1080p" | "2160p"

    def dimensions(self) -> tuple[int, int]:
        """The (width, height) in pixels for the configured resolution."""
        return IMAGE_RESOLUTIONS.get(self.image_resolution, IMAGE_RESOLUTIONS["1080p"])


# Image formats offered for scene rendering (file extension == value).
IMAGE_FORMATS = ("jpg", "png")

# Render resolutions offered for scene rendering -> (width, height) in pixels.
IMAGE_RESOLUTIONS = {"1080p": (1920, 1080), "2160p": (3840, 2160)}


@dataclass
class LicenseConfig:
    mode: str = "podkey_server"   # "podkey_server" | "license_file"
    podkey: str = ""
    licpath: str = ""             # <port>@<server>
    license_file: str = ""

    def cli_args(self) -> list[str]:
        """STAR-CCM+ command-line flags for this license configuration."""
        if self.mode == "license_file":
            return ["-licpath", self.license_file] if self.license_file else []
        # podkey_server (default): Power-on-Demand key served via license server
        args: list[str] = ["-power"]
        if self.podkey:
            args += ["-podkey", self.podkey]
        if self.licpath:
            args += ["-licpath", self.licpath]
        return args


@dataclass
class Settings:
    starccm_path: str = ""
    license: LicenseConfig = field(default_factory=LicenseConfig)
    media: MediaConfig = field(default_factory=MediaConfig)
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    default_output_dir: str = ""
    extra_args: list[str] = field(default_factory=list)
    show_full_file_names: bool = False  # file list shows full paths vs. names only
    report_decimals: int = 4      # decimal places shown for report values
    hide_empty_reports: bool = True   # hide reports whose value is ~0
    zero_threshold: float = 1e-5  # |value| below this is treated as 0
    hide_empty_monitors: bool = True  # hide monitor plots whose values are all ~0
    monitor_zero_threshold: float = 1e-5  # |value| below this is treated as 0
    # Window size (in points) of the moving average applied when "Smooth data"
    # is enabled under the plot. 1 leaves the data unchanged.
    moving_average_width: int = 10
    hover_show_monitor_name: bool = False  # include monitor name in the hover label
    hover_x_decimals: int = 0  # decimal places shown for the hover X coordinate
    hover_y_decimals: int = 4  # decimal places shown for the hover Y coordinate
    # Statistics shown in the Shift+drag region table (labels, in catalog order).
    region_stats: list[str] = field(
        default_factory=lambda: ["Avg", "Std Dev", "Range"]
    )
    plot_classification: dict = field(
        default_factory=lambda: {
            "residual_keywords": ["residual", "residuals"],
            "force_keywords": ["force", "drag", "lift", "moment", "cd", "cl"],
        }
    )
    # Show the first-run welcome/setup wizard on startup. Defaults on so new
    # users see it; cleared once they opt out (in the wizard or Misc settings).
    show_setup_on_startup: bool = True
    # Check GitHub for a newer release on startup and offer to update. Defaults
    # on; toggled from Misc settings.
    check_updates_on_startup: bool = True
    # Default selections for the Export dialog (the user can still change them
    # per-export). Formats are the dialog's display strings; the plot theme is a
    # "dark"/"light" mode like appearance.mode.
    export_report_format: str = "CSV"   # CSV | TSV | XLSX | ODS
    export_plot_format: str = "PNG"     # PNG | JPG | TIFF | PDF
    export_plot_theme: str = "dark"     # "dark" | "light"

    # --- persistence -----------------------------------------------------
    @classmethod
    def load(cls) -> "Settings":
        path = settings_path()
        if not path.exists():
            # Seed from the packaged defaults on first run.
            default = packaged_default_settings()
            if default.exists():
                shutil.copy(default, path)
                # shutil.copy carries the source's mode bits; lock the user's
                # copy down before any credentials are written into it.
                harden_file(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        return cls.from_dict(data or {})

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        lic = d.get("license", {}) or {}
        appe = d.get("appearance", {}) or {}
        med = d.get("media", {}) or {}
        return cls(
            starccm_path=d.get("starccm_path", ""),
            license=LicenseConfig(
                mode=lic.get("mode", "podkey_server"),
                podkey=lic.get("podkey", ""),
                licpath=lic.get("licpath", ""),
                license_file=lic.get("license_file", ""),
            ),
            media=MediaConfig(
                magnification=int(med.get("magnification", 1)),
                render_np=int(med.get("render_np", 1)),
                scenes_per_checkout=max(1, int(med.get("scenes_per_checkout", 1))),
                image_format=(
                    str(med.get("image_format", "jpg")).lower()
                    if str(med.get("image_format", "jpg")).lower() in IMAGE_FORMATS
                    else "jpg"
                ),
                image_resolution=(
                    str(med.get("image_resolution", "1080p")).lower()
                    if str(med.get("image_resolution", "1080p")).lower()
                    in IMAGE_RESOLUTIONS
                    else "1080p"
                ),
            ),
            appearance=AppearanceConfig(
                mode=appe.get("mode", "dark"),
                accent=appe.get("accent", "#ffc829"),
                checkmark_color=appe.get("checkmark_color", "#ffc829"),
                checkmark_match_theme=bool(
                    appe.get("checkmark_match_theme", True)
                ),
                folder_color=appe.get("folder_color", "#ffc829"),
                folder_use_default=bool(appe.get("folder_use_default", True)),
                text_scale=clamp_text_scale(appe.get("text_scale", 1.0)),
            ),
            default_output_dir=d.get("default_output_dir", ""),
            extra_args=list(d.get("extra_args", []) or []),
            show_full_file_names=bool(d.get("show_full_file_names", False)),
            report_decimals=int(d.get("report_decimals", 4)),
            hide_empty_reports=bool(d.get("hide_empty_reports", True)),
            zero_threshold=float(d.get("zero_threshold", 1e-5)),
            hide_empty_monitors=bool(d.get("hide_empty_monitors", True)),
            monitor_zero_threshold=float(d.get("monitor_zero_threshold", 1e-5)),
            moving_average_width=max(1, int(d.get("moving_average_width", 10))),
            hover_show_monitor_name=bool(d.get("hover_show_monitor_name", False)),
            hover_x_decimals=int(d.get("hover_x_decimals", 0)),
            hover_y_decimals=int(d.get("hover_y_decimals", 4)),
            region_stats=(
                list(d["region_stats"])
                if isinstance(d.get("region_stats"), list)
                else ["Avg", "Std Dev", "Range"]
            ),
            plot_classification=d.get("plot_classification")
            or cls().plot_classification,
            show_setup_on_startup=bool(d.get("show_setup_on_startup", True)),
            check_updates_on_startup=bool(d.get("check_updates_on_startup", True)),
            export_report_format=str(d.get("export_report_format", "CSV")),
            export_plot_format=str(d.get("export_plot_format", "PNG")),
            export_plot_theme=str(d.get("export_plot_theme", "dark")),
        )

    def to_dict(self) -> dict:
        return {
            "starccm_path": self.starccm_path,
            "license": {
                "mode": self.license.mode,
                "podkey": self.license.podkey,
                "licpath": self.license.licpath,
                "license_file": self.license.license_file,
            },
            "media": {
                "magnification": self.media.magnification,
                "render_np": self.media.render_np,
                "scenes_per_checkout": self.media.scenes_per_checkout,
                "image_format": self.media.image_format,
                "image_resolution": self.media.image_resolution,
            },
            "appearance": {
                "mode": self.appearance.mode,
                "accent": self.appearance.accent,
                "checkmark_color": self.appearance.checkmark_color,
                "checkmark_match_theme": self.appearance.checkmark_match_theme,
                "folder_color": self.appearance.folder_color,
                "folder_use_default": self.appearance.folder_use_default,
                "text_scale": self.appearance.text_scale,
            },
            "default_output_dir": self.default_output_dir,
            "extra_args": self.extra_args,
            "show_full_file_names": self.show_full_file_names,
            "report_decimals": self.report_decimals,
            "hide_empty_reports": self.hide_empty_reports,
            "zero_threshold": self.zero_threshold,
            "hide_empty_monitors": self.hide_empty_monitors,
            "monitor_zero_threshold": self.monitor_zero_threshold,
            "moving_average_width": self.moving_average_width,
            "hover_show_monitor_name": self.hover_show_monitor_name,
            "hover_x_decimals": self.hover_x_decimals,
            "hover_y_decimals": self.hover_y_decimals,
            "region_stats": self.region_stats,
            "plot_classification": self.plot_classification,
            "show_setup_on_startup": self.show_setup_on_startup,
            "check_updates_on_startup": self.check_updates_on_startup,
            "export_report_format": self.export_report_format,
            "export_plot_format": self.export_plot_format,
            "export_plot_theme": self.export_plot_theme,
        }

    def save(self) -> None:
        path = settings_path()
        path.write_text(
            yaml.safe_dump(self.to_dict(), sort_keys=False), encoding="utf-8"
        )
        # The file holds the POD key / license server in plaintext; keep it
        # readable only by the owner (also fixes any pre-existing loose perms).
        harden_file(path)


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
@dataclass
class Profile:
    """A saved selection of which reports/plots to export, plus axis overrides."""
    name: str
    reports: list[str] = field(default_factory=list)   # selected report names
    plots: list[str] = field(default_factory=list)     # selected plot names
    # plot (monitor group) name -> the series (monitors) shown for it. A group
    # absent here defaults to showing all of its monitors.
    monitors: dict[str, list[str]] = field(default_factory=dict)
    # plot name -> "log" | "linear", overriding the auto classification
    axis_overrides: dict[str, str] = field(default_factory=dict)
    # Region statistics shown when the profile was saved (labels). None for
    # profiles saved before this existed — those leave the current stats as-is.
    region_stats: Optional[list[str]] = None

    def path(self) -> Path:
        return profiles_dir() / f"{self.name}.yaml"

    def save(self) -> None:
        self.path().write_text(
            yaml.safe_dump(
                {
                    "name": self.name,
                    "reports": self.reports,
                    "plots": self.plots,
                    "monitors": self.monitors,
                    "axis_overrides": self.axis_overrides,
                    "region_stats": self.region_stats,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, name: str) -> "Profile":
        data = yaml.safe_load(
            (profiles_dir() / f"{name}.yaml").read_text(encoding="utf-8")
        )
        rs = data.get("region_stats")
        return cls(
            name=data["name"],
            reports=data.get("reports", []),
            plots=data.get("plots", []),
            monitors=data.get("monitors", {}) or {},
            axis_overrides=data.get("axis_overrides", {}),
            region_stats=list(rs) if isinstance(rs, list) else None,
        )


# A built-in profile (not stored on disk): selects every available report and
# no monitor plots — the application's default selection state. Resolved at load
# time so "every report" always reflects whatever data is currently loaded.
DEFAULT_PROFILE_NAME = "Default"


def list_profiles() -> list[str]:
    return sorted(p.stem for p in profiles_dir().glob("*.yaml"))


def delete_profile(name: str) -> None:
    """Remove a saved profile. No-op if it doesn't exist."""
    (profiles_dir() / f"{name}.yaml").unlink(missing_ok=True)
