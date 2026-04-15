"""Vanilla Minecraft server JAR installer.

Reference: docker-minecraft-server/scripts/start-deployVanilla
API: https://launchermeta.mojang.com/mc/game/version_manifest.json
"""

from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file

_VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json"


class VanillaInstaller:
    """Downloads the vanilla Minecraft server JAR."""

    def __init__(
        self,
        minecraft_version: str,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.minecraft_version = minecraft_version
        self.session = session or build_session()
        self.show_progress = show_progress

    def _get_manifest(self) -> dict:
        resp = self.session.get(_VERSION_MANIFEST_URL, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def resolve_version(self) -> str:
        """Resolve 'LATEST', 'SNAPSHOT', or a specific version string to a concrete version ID."""
        manifest = self._get_manifest()
        normalized = self.minecraft_version.upper()

        if normalized == "LATEST":
            return manifest["latest"]["release"]
        if normalized == "SNAPSHOT":
            return manifest["latest"]["snapshot"]

        ids = {v["id"] for v in manifest["versions"]}
        if self.minecraft_version not in ids:
            raise ValueError(
                f"Minecraft version '{self.minecraft_version}' not found in version manifest"
            )
        return self.minecraft_version

    def install(self, output_dir: Path) -> Path:
        """Download the vanilla server JAR into *output_dir*.

        Resolves 'LATEST' / 'SNAPSHOT' automatically.
        Returns the path to the downloaded JAR.
        """
        version = self.resolve_version()

        # Find the version-specific manifest URL
        manifest = self._get_manifest()
        entry = next((v for v in manifest["versions"] if v["id"] == version), None)
        if entry is None:
            raise ValueError(f"No manifest entry for version '{version}'")

        # Fetch the version manifest to get the server download URL + sha1
        resp = self.session.get(entry["url"], timeout=30)
        resp.raise_for_status()
        version_data = resp.json()

        server_info = version_data.get("downloads", {}).get("server")
        if not server_info:
            raise ValueError(f"No server download available for Minecraft {version}")

        url = server_info["url"]
        sha1 = server_info.get("sha1")

        dest = output_dir / f"minecraft_server.{version}.jar"
        download_file(
            url, dest, session=self.session, expected_sha1=sha1, show_progress=self.show_progress
        )
        return dest


def resolve_version(session: requests.Session, requested: str) -> str:
    """Resolve 'LATEST', 'SNAPSHOT', or a specific version string to a concrete version ID."""
    return VanillaInstaller(requested, session=session).resolve_version()
