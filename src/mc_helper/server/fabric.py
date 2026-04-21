"""Fabric server launcher installer.

Reference: mc-image-helper/.../fabric/FabricMetaClient.java
Reference: mc-image-helper/.../fabric/FabricLauncherInstaller.java
API base: https://meta.fabricmc.net
"""

import logging
from pathlib import Path

import requests

from mc_helper.config import ServerConfig
from mc_helper.http_client import download_file, get_json

from .base import ServerInstaller

log = logging.getLogger(__name__)

_META_BASE = "https://meta.fabricmc.net"


class FabricInstaller(ServerInstaller):
    """Downloads the Fabric server launcher JAR."""

    def __init__(
        self,
        config: ServerConfig,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        super().__init__(config, session=session, show_progress=show_progress)

    def _resolve_loader_version(self) -> str:
        loader_version = self.config.loader_version
        if loader_version.upper() != "LATEST":
            return loader_version
        mc = self.config.minecraft_version
        versions = get_json(self.session, f"{_META_BASE}/v2/versions/loader/{mc}")
        stable = [v for v in versions if v.get("loader", {}).get("stable")]  # type: ignore[union-attr]
        candidates = stable or list(versions)  # type: ignore[arg-type]
        if not candidates:
            raise ValueError(f"No Fabric loader versions found for Minecraft {mc}")
        return candidates[0]["loader"]["version"]

    def _resolve_installer_version(self) -> str:
        versions = get_json(self.session, f"{_META_BASE}/v2/versions/installer")
        stable = [v for v in versions if v.get("stable")]  # type: ignore[union-attr]
        candidates = stable or list(versions)  # type: ignore[arg-type]
        if not candidates:
            raise ValueError("No Fabric installer versions found")
        return candidates[0]["version"]

    def install(self, output_dir: Path) -> Path:
        """Download the Fabric server launcher JAR into *output_dir*.

        Returns the path to the downloaded JAR.
        """
        resolved_loader = self._resolve_loader_version()
        resolved_installer = self._resolve_installer_version()
        log.info("Resolved Fabric loader %s, installer %s", resolved_loader, resolved_installer)

        mc = self.config.minecraft_version
        url = (
            f"{_META_BASE}/v2/versions/loader"
            f"/{mc}/{resolved_loader}/{resolved_installer}/server/jar"
        )

        dest = output_dir / "fabric-server-launch.jar"
        log.debug("Downloading Fabric server JAR: %s", url)
        download_file(url, dest, session=self.session, show_progress=self.show_progress)
        return dest
