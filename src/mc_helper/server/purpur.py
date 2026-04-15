"""Purpur server JAR installer.

Reference: mc-image-helper/.../purpur/PurpurDownloadsClient.java
API: https://api.purpurmc.org/v2

Endpoints used:
  GET /v2/purpur/{version}          → { builds: { latest, all: [...] } }
  GET /v2/purpur/{version}/{build}/download  → JAR binary
"""

from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file, get_json

_API_BASE = "https://api.purpurmc.org"


class PurpurInstaller:
    """Downloads the Purpur server JAR."""

    def __init__(
        self,
        minecraft_version: str,
        build: str = "LATEST",
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.minecraft_version = minecraft_version
        self.build = build
        self.session = session or build_session()
        self.show_progress = show_progress

    def _resolve_build(self) -> str:
        """Return the latest build number string for this version."""
        data = get_json(self.session, f"{_API_BASE}/v2/purpur/{self.minecraft_version}")
        latest = data.get("builds", {}).get("latest")
        if not latest:
            raise ValueError(f"No Purpur builds found for Minecraft {self.minecraft_version}")
        return str(latest)

    def install(self, output_dir: Path) -> Path:
        """Download the Purpur server JAR into *output_dir*.

        Returns the path to the downloaded JAR.
        """
        resolved_build = self._resolve_build() if self.build.upper() == "LATEST" else self.build

        url = f"{_API_BASE}/v2/purpur/{self.minecraft_version}/{resolved_build}/download"
        dest = output_dir / f"purpur-{self.minecraft_version}-{resolved_build}.jar"
        download_file(url, dest, session=self.session, show_progress=self.show_progress)
        return dest
