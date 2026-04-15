"""Fabric server launcher installer.

Reference: mc-image-helper/.../fabric/FabricMetaClient.java
Reference: mc-image-helper/.../fabric/FabricLauncherInstaller.java
API base: https://meta.fabricmc.net
"""

from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file, get_json

_META_BASE = "https://meta.fabricmc.net"


class FabricInstaller:
    """Downloads the Fabric server launcher JAR."""

    def __init__(
        self,
        minecraft_version: str,
        loader_version: str = "LATEST",
        installer_version: str = "LATEST",
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.minecraft_version = minecraft_version
        self.loader_version = loader_version
        self.installer_version = installer_version
        self.session = session or build_session()
        self.show_progress = show_progress

    def _resolve_loader_version(self) -> str:
        if self.loader_version.upper() != "LATEST":
            return self.loader_version
        versions = get_json(
            self.session, f"{_META_BASE}/v2/versions/loader/{self.minecraft_version}"
        )
        if not versions:
            raise ValueError(
                f"No Fabric loader versions found for Minecraft {self.minecraft_version}"
            )
        return versions[0]["loader"]["version"]

    def _resolve_installer_version(self) -> str:
        if self.installer_version.upper() != "LATEST":
            return self.installer_version
        versions = get_json(self.session, f"{_META_BASE}/v2/versions/installer")
        if not versions:
            raise ValueError("No Fabric installer versions found")
        return versions[0]["version"]

    def install(self, output_dir: Path) -> Path:
        """Download the Fabric server launcher JAR into *output_dir*.

        Returns the path to the downloaded JAR.
        """
        resolved_loader = self._resolve_loader_version()
        resolved_installer = self._resolve_installer_version()

        url = (
            f"{_META_BASE}/v2/versions/loader"
            f"/{self.minecraft_version}/{resolved_loader}/{resolved_installer}/server/jar"
        )

        dest = output_dir / "fabric-server-launch.jar"
        download_file(url, dest, session=self.session, show_progress=self.show_progress)
        return dest
