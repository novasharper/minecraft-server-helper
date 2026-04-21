"""Vanilla Minecraft server JAR installer.

Reference: docker-minecraft-server/scripts/start-deployVanilla
API: https://launchermeta.mojang.com/mc/game/version_manifest.json
"""

import logging
from pathlib import Path

import requests

from mc_helper.config import ServerConfig
from mc_helper.http_client import download_file, get_json

from .base import ServerInstaller

log = logging.getLogger(__name__)

_VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json"


def resolve_version(session: requests.Session, requested: str) -> str:
    """Resolve 'LATEST', 'SNAPSHOT', or a specific version string to a concrete version ID."""
    manifest = get_json(session, _VERSION_MANIFEST_URL)
    normalized = requested.upper()

    if normalized == "LATEST":
        return manifest["latest"]["release"]  # type: ignore[index]
    if normalized == "SNAPSHOT":
        return manifest["latest"]["snapshot"]  # type: ignore[index]

    ids = {v["id"] for v in manifest["versions"]}  # type: ignore[index]
    if requested not in ids:
        raise ValueError(f"Minecraft version '{requested}' not found in version manifest")
    return requested


class VanillaInstaller(ServerInstaller):
    """Downloads the vanilla Minecraft server JAR."""

    def __init__(
        self,
        config: ServerConfig,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        super().__init__(config, session=session, show_progress=show_progress)

    def resolve_version(self) -> str:
        """Resolve 'LATEST', 'SNAPSHOT', or a specific version to a concrete version ID."""
        return resolve_version(self.session, self.config.minecraft_version or "LATEST")

    def install(self, output_dir: Path) -> Path:
        """Download the vanilla server JAR into *output_dir*.

        Returns the path to the downloaded JAR.
        """
        version = self.resolve_version()
        log.info("Resolved Minecraft version: %s", version)

        manifest = get_json(self.session, _VERSION_MANIFEST_URL)
        entry = next((v for v in manifest["versions"] if v["id"] == version), None)  # type: ignore[union-attr]
        if entry is None:
            raise ValueError(f"No manifest entry for version '{version}'")

        version_data = get_json(self.session, entry["url"])
        server_info = version_data.get("downloads", {}).get("server")  # type: ignore[union-attr]
        if not server_info:
            raise ValueError(f"No server download available for Minecraft {version}")

        url = server_info["url"]
        sha1 = server_info.get("sha1")

        dest = output_dir / f"minecraft_server.{version}.jar"
        log.debug("Downloading vanilla server JAR: %s", url)
        download_file(
            url, dest, session=self.session, expected_sha1=sha1, show_progress=self.show_progress
        )
        return dest
