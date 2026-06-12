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
    packaged_default_settings,
    profiles_dir,
    settings_path,
)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@dataclass
class AppearanceConfig:
    mode: str = "dark"          # "dark" | "light"
    accent: str = "#ffc829"     # hex accent colour applied program-wide


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
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    default_output_dir: str = ""
    extra_args: list[str] = field(default_factory=list)
    plot_classification: dict = field(
        default_factory=lambda: {
            "residual_keywords": ["residual", "residuals"],
            "force_keywords": ["force", "drag", "lift", "moment", "cd", "cl"],
        }
    )

    # --- persistence -----------------------------------------------------
    @classmethod
    def load(cls) -> "Settings":
        path = settings_path()
        if not path.exists():
            # Seed from the packaged defaults on first run.
            default = packaged_default_settings()
            if default.exists():
                shutil.copy(default, path)
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
        return cls.from_dict(data or {})

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        lic = d.get("license", {}) or {}
        appe = d.get("appearance", {}) or {}
        return cls(
            starccm_path=d.get("starccm_path", ""),
            license=LicenseConfig(
                mode=lic.get("mode", "podkey_server"),
                podkey=lic.get("podkey", ""),
                licpath=lic.get("licpath", ""),
                license_file=lic.get("license_file", ""),
            ),
            appearance=AppearanceConfig(
                mode=appe.get("mode", "dark"),
                accent=appe.get("accent", "#ffc829"),
            ),
            default_output_dir=d.get("default_output_dir", ""),
            extra_args=list(d.get("extra_args", []) or []),
            plot_classification=d.get("plot_classification")
            or cls().plot_classification,
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
            "appearance": {
                "mode": self.appearance.mode,
                "accent": self.appearance.accent,
            },
            "default_output_dir": self.default_output_dir,
            "extra_args": self.extra_args,
            "plot_classification": self.plot_classification,
        }

    def save(self) -> None:
        settings_path().write_text(yaml.safe_dump(self.to_dict(), sort_keys=False))


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
@dataclass
class Profile:
    """A saved selection of which reports/plots to export, plus axis overrides."""
    name: str
    reports: list[str] = field(default_factory=list)   # selected report names
    plots: list[str] = field(default_factory=list)     # selected plot names
    # plot name -> "log" | "linear", overriding the auto classification
    axis_overrides: dict[str, str] = field(default_factory=dict)

    def path(self) -> Path:
        return profiles_dir() / f"{self.name}.yaml"

    def save(self) -> None:
        self.path().write_text(
            yaml.safe_dump(
                {
                    "name": self.name,
                    "reports": self.reports,
                    "plots": self.plots,
                    "axis_overrides": self.axis_overrides,
                },
                sort_keys=False,
            )
        )

    @classmethod
    def load(cls, name: str) -> "Profile":
        data = yaml.safe_load((profiles_dir() / f"{name}.yaml").read_text())
        return cls(
            name=data["name"],
            reports=data.get("reports", []),
            plots=data.get("plots", []),
            axis_overrides=data.get("axis_overrides", {}),
        )


def list_profiles() -> list[str]:
    return sorted(p.stem for p in profiles_dir().glob("*.yaml"))
