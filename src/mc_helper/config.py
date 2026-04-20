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
    type: Optional[ServerType] = None
    minecraft_version: Optional[str] = None
    loader_version: str = "LATEST"
    output_dir: Path = Path("./server")
    eula: bool = False
    memory: str = "1G"
    properties: dict[str, str | int | bool] = Field(default_factory=dict)


# ── Modpack ───────────────────────────────────────────────────────────────────

ModpackPlatform = Literal["modrinth", "curseforge", "ftb", "github", "url"]
VersionType = Literal["release", "beta", "alpha"]


class ModrinthSource(BaseModel):
    project: str
    version: str = "LATEST"
    version_type: VersionType = "release"


class CurseForgeSource(BaseModel):
    api_key: str
    slug: Optional[str] = None
    file_id: Optional[int] = None
    filename_matcher: Optional[str] = None

    @model_validator(mode="after")
    def _check_slug_or_file_id(self) -> "CurseForgeSource":
        if not self.slug and not self.file_id:
            raise ValueError("source.slug or source.file_id is required for platform 'curseforge'")
        return self


class FTBSource(BaseModel):
    pack_id: int
    version_id: Optional[int] = None
    api_key: Optional[str] = None
    version_type: VersionType = "release"


class GithubSource(BaseModel):
    repo: str
    tag: str = "LATEST"
    asset: Optional[str] = None
    token: Optional[str] = None
    strip_components: int = 0
    force_update: bool = False
    start_artifact: Optional[str] = None


class UrlSource(BaseModel):
    url: str
    token: Optional[str] = None
    strip_components: int = 0
    force_update: bool = False
    start_artifact: Optional[str] = None


Source = ModrinthSource | CurseForgeSource | FTBSource | GithubSource | UrlSource

_SOURCE_MAP: dict[str, type[BaseModel]] = {
    "modrinth": ModrinthSource,
    "curseforge": CurseForgeSource,
    "ftb": FTBSource,
    "github": GithubSource,
    "url": UrlSource,
}


class ModpackConfig(BaseModel):
    platform: ModpackPlatform
    source: Source

    exclude_mods: list[str] = Field(default_factory=list)
    force_include_mods: list[str] = Field(default_factory=list)
    overrides_exclusions: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _parse_source(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        platform = data.get("platform")
        source_raw = data.get("source", {})
        if platform in _SOURCE_MAP:
            data["source"] = _SOURCE_MAP[platform].model_validate(source_raw)
        return data


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


# ── Root ──────────────────────────────────────────────────────────────────────


class RootConfig(BaseModel):
    server: ServerConfig
    modpack: Optional[ModpackConfig] = None
    mods: Optional[ModsConfig] = None

    @model_validator(mode="after")
    def _check_install_mode(self) -> "RootConfig":
        if self.modpack is None:
            if self.server.type is None:
                raise ValueError("server.type is required when not using modpack")
        return self
