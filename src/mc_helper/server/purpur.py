"""Purpur server JAR installer.

Reference: mc-image-helper/.../purpur/PurpurDownloadsClient.java
API: https://api.purpurmc.org/v2

Endpoints used:
  GET /v2/purpur/{version}          → { builds: { latest, all: [...] } }
  GET /v2/purpur/{version}/{build}/download  → JAR binary
"""

import logging
from pathlib import Path

import requests

from mc_helper.config import ServerConfig
from mc_helper.http_client import download_file, get_json

from .base import ServerInstaller

log = logging.getLogger(__name__)

_API_BASE = "https://api.purpurmc.org"


class PurpurInstaller(ServerInstaller):
    """Downloads the Purpur server JAR."""

    def __init__(
        self,
        config: ServerConfig,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        super().__init__(config, session=session, show_progress=show_progress)

    def _resolve_build(self) -> str:
        data = get_json(self.session, f"{_API_BASE}/v2/purpur/{self.config.minecraft_version}")
        latest = data.get("builds", {}).get("latest")  # type: ignore[union-attr]
        if not latest:
            raise ValueError(
                f"No Purpur builds found for Minecraft {self.config.minecraft_version}"
            )
        return str(latest)

    def install(self, output_dir: Path) -> Path:
        """Download the Purpur server JAR into *output_dir*.

        Returns the path to the downloaded JAR.
        """
        resolved_build = self._resolve_build()
        log.info("Resolved Purpur build: %s", resolved_build)

        mc = self.config.minecraft_version
        url = f"{_API_BASE}/v2/purpur/{mc}/{resolved_build}/download"
        log.debug("Downloading Purpur JAR: %s", url)
        dest = output_dir / f"purpur-{mc}-{resolved_build}.jar"
        download_file(url, dest, session=self.session, show_progress=self.show_progress)
        return dest
