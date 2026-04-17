"""PaperMC server JAR installer.

Reference: mc-image-helper/.../paper/PaperDownloadsClient.java
Reference: mc-image-helper/.../paper/InstallPaperCommand.java
API: https://fill.papermc.io  (v3)

Endpoint used:
  GET /v3/projects/{project}/versions/{version}/builds/latest
  Response: { id, channel, downloads: { "server:default": { name, url, checksums: { sha256 } } } }
"""

import logging
from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file, get_json

log = logging.getLogger(__name__)

_API_BASE = "https://fill.papermc.io"


class PaperInstaller:
    """Downloads the latest PaperMC (or Folia/Waterfall) server JAR."""

    def __init__(
        self,
        minecraft_version: str,
        project: str = "paper",
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.minecraft_version = minecraft_version
        self.project = project
        self.session = session or build_session()
        self.show_progress = show_progress

    def _get_latest_build(self) -> dict:
        """Return the latest build response dict for this project/version."""
        url = (
            f"{_API_BASE}/v3/projects/{self.project}"
            f"/versions/{self.minecraft_version}/builds/latest"
        )
        return get_json(self.session, url)

    def install(self, output_dir: Path) -> Path:
        """Download the latest Paper build into *output_dir*.

        Returns the path to the downloaded JAR.
        """
        build = self._get_latest_build()
        download_info = build.get("downloads", {}).get("server:default")
        if not download_info:
            raise ValueError(
                f"No server download found in Paper build response for "
                f"{self.project} {self.minecraft_version}"
            )

        url = download_info["url"]
        name = download_info["name"]
        sha256 = download_info.get("checksums", {}).get("sha256")
        log.info("Resolved %s build: %s", self.project, build.get("id", "?"))
        log.debug("Downloading %s JAR: %s", self.project, url)

        dest = output_dir / name
        download_file(
            url,
            dest,
            session=self.session,
            expected_sha256=sha256,
            show_progress=self.show_progress,
        )
        return dest
