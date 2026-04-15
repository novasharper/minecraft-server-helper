import os
import re
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


def _interpolate_env(text: str) -> str:
    """Replace ${VAR} with the value of environment variable VAR."""

    def _replace(match: re.Match) -> str:
        var = match.group(1)
        value = os.environ.get(var)
        if value is None:
            raise ValueError(f"Environment variable '{var}' is not set")
        return value

    return re.sub(r"\$\{([^}]+)\}", _replace, text)


def _interpolate_obj(obj: object) -> object:
    """Recursively interpolate ${VAR} in all string values of a parsed YAML object."""
    if isinstance(obj, str):
        return _interpolate_env(obj)
    if isinstance(obj, dict):
        return {k: _interpolate_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate_obj(item) for item in obj]
    return obj


def load_config(path: str | Path) -> "RootConfig":
    """Load, interpolate, and validate a YAML config file."""
    raw = Path(path).read_text()
    data = yaml.safe_load(raw)
    data = _interpolate_obj(data)
    return RootConfig.model_validate(data)


# ── Server ────────────────────────────────────────────────────────────────────

ServerType = Literal["vanilla", "forge", "neoforge", "fabric", "paper", "purpur"]


class ServerConfig(BaseModel):
    type: ServerType
    minecraft_version: str = "LATEST"
    loader_version: str = "LATEST"
    output_dir: Path = Path("./server")
    eula: bool = False
    memory: str = "1G"
    properties: dict[str, str | int | bool] = Field(default_factory=dict)


# ── Modpack ───────────────────────────────────────────────────────────────────

ModpackPlatform = Literal["modrinth", "curseforge"]
VersionType = Literal["release", "beta", "alpha"]


class ModpackConfig(BaseModel):
    platform: ModpackPlatform

    # Modrinth
    project: Optional[str] = None
    version: str = "LATEST"
    version_type: VersionType = "release"

    # CurseForge
    api_key: Optional[str] = None
    slug: Optional[str] = None
    file_id: Optional[int] = None
    filename_matcher: Optional[str] = None

    # Shared
    exclude_mods: list[str] = Field(default_factory=list)
    force_include_mods: list[str] = Field(default_factory=list)
    overrides_exclusions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_platform_fields(self) -> "ModpackConfig":
        if self.platform == "modrinth" and not self.project:
            raise ValueError("modpack.project is required for platform 'modrinth'")
        if self.platform == "curseforge":
            if not self.api_key:
                raise ValueError("modpack.api_key is required for platform 'curseforge'")
            if not self.slug and not self.file_id:
                raise ValueError(
                    "modpack.slug or modpack.file_id is required for platform 'curseforge'"
                )
        return self


# ── Mods ──────────────────────────────────────────────────────────────────────


class CurseForgeModsConfig(BaseModel):
    api_key: str
    files: list[str] = Field(default_factory=list)


class ModsConfig(BaseModel):
    modrinth: list[str] = Field(default_factory=list)
    curseforge: Optional[CurseForgeModsConfig] = None
    urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_not_empty(self) -> "ModsConfig":
        has_modrinth = bool(self.modrinth)
        has_cf = self.curseforge is not None and bool(self.curseforge.files)
        has_urls = bool(self.urls)
        if not (has_modrinth or has_cf or has_urls):
            raise ValueError("mods must specify at least one of: modrinth, curseforge, urls")
        return self


# ── Server Pack ───────────────────────────────────────────────────────────────


class ServerPackConfig(BaseModel):
    # Source: exactly one of url or github must be set
    url: Optional[str] = None
    github: Optional[str] = None
    tag: str = "LATEST"
    asset: Optional[str] = None
    token: Optional[str] = None

    # Extraction options
    strip_components: int = 0
    disable_mods: list[str] = Field(default_factory=list)
    force_update: bool = False

    @model_validator(mode="after")
    def _check_source(self) -> "ServerPackConfig":
        if self.url and self.github:
            raise ValueError("server_pack: only one of 'url' or 'github' may be set")
        if not self.url and not self.github:
            raise ValueError("server_pack: one of 'url' or 'github' must be set")
        return self


# ── Root ──────────────────────────────────────────────────────────────────────


class RootConfig(BaseModel):
    server: ServerConfig
    modpack: Optional[ModpackConfig] = None
    mods: Optional[ModsConfig] = None
    server_pack: Optional[ServerPackConfig] = None

    @model_validator(mode="after")
    def _check_mutual_exclusion(self) -> "RootConfig":
        active = [
            name
            for name, val in [
                ("modpack", self.modpack),
                ("mods", self.mods),
                ("server_pack", self.server_pack),
            ]
            if val is not None
        ]
        if len(active) > 1:
            raise ValueError(
                f"Exactly one of modpack / mods / server_pack may be set; got: {', '.join(active)}"
            )
        return self
