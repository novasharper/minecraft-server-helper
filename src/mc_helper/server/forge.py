"""Forge server installer.

Reference: mc-image-helper/.../forge/ForgeInstallerResolver.java
Reference: mc-image-helper/.../forge/ForgeLikeInstaller.java
Reference: docker-minecraft-server/scripts/start-deployForge

Workflow:
  1. Resolve forge version via promotions_slim.json (supports LATEST / RECOMMENDED)
  2. Download installer JAR from Forge Maven
  3. Run `java -jar forge-installer.jar --installServer` in output_dir
"""

import logging
import subprocess
from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file

log = logging.getLogger(__name__)

_PROMOTIONS_URL = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
_MAVEN_BASE = "https://maven.minecraftforge.net"


def _installer_urls(minecraft_version: str, forge_version: str) -> list[str]:
    """Return candidate installer URLs in priority order.

    Forge has used several version qualifier schemes across its history;
    try each in order until one succeeds.
    """
    mc, fv = minecraft_version, forge_version
    base = f"{_MAVEN_BASE}/net/minecraftforge/forge"
    return [
        f"{base}/{mc}-{fv}/forge-{mc}-{fv}-installer.jar",
        f"{base}/{mc}-{fv}-{mc}/forge-{mc}-{fv}-{mc}-installer.jar",
    ]


class ForgeInstaller:
    """Downloads and runs the Forge server installer."""

    def __init__(
        self,
        minecraft_version: str,
        forge_version: str = "RECOMMENDED",
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.minecraft_version = minecraft_version
        self.forge_version = forge_version
        self.session = session or build_session()
        self.show_progress = show_progress

    def _get_promotions(self) -> dict:
        resp = self.session.get(_PROMOTIONS_URL, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _resolve_forge_version(self) -> str:
        """Resolve LATEST / RECOMMENDED to a concrete Forge version string."""
        normalized = self.forge_version.lower()
        if normalized not in ("latest", "recommended"):
            return self.forge_version

        promos: dict[str, str] = self._get_promotions()["promos"]

        # Keys are like "1.21.1-recommended": "51.0.33"
        options: dict[str, str] = {}
        for key, forge_ver in promos.items():
            parts = key.split("-", 1)
            if len(parts) == 2 and parts[0] == self.minecraft_version:
                options[parts[1].lower()] = forge_ver

        if not options:
            raise ValueError(f"No Forge versions available for Minecraft {self.minecraft_version}")

        if normalized in options:
            return options[normalized]
        # Fall back to whichever promo is available
        return next(iter(options.values()))

    def _download_installer(self, output_dir: Path, resolved: str) -> Path:
        """Try each candidate URL in order; return the path of the downloaded JAR."""
        urls = _installer_urls(self.minecraft_version, resolved)
        last_exc: Exception | None = None
        for url in urls:
            # Use a HEAD request to check existence before committing to download.
            try:
                head = self.session.head(url, timeout=15)
                if head.status_code == 404:
                    log.debug("Forge installer not found at %s, trying next URL", url)
                    continue
                head.raise_for_status()
            except Exception as exc:
                last_exc = exc
                continue
            installer_jar = output_dir / f"forge-{self.minecraft_version}-{resolved}-installer.jar"
            log.debug("Downloading Forge installer: %s", url)
            download_file(
                url, installer_jar, session=self.session, show_progress=self.show_progress
            )
            return installer_jar
        raise RuntimeError(
            f"No Forge installer found for {self.minecraft_version}-{resolved}. "
            f"Tried: {urls}"
        ) from last_exc

    def install(self, output_dir: Path) -> Path:
        """Download and run the Forge installer in *output_dir*.

        Returns the path to ``run.sh`` created by the Forge installer.
        """
        resolved = self._resolve_forge_version()
        log.info("Resolved Forge version: %s", resolved)
        installer_jar = self._download_installer(output_dir, resolved)

        log.info("Running Forge installer (this may take a while)...")
        try:
            subprocess.run(
                ["java", "-jar", str(installer_jar), "--installServer"],
                cwd=output_dir,
                check=True,
            )
        finally:
            installer_jar.unlink(missing_ok=True)
            # The Forge installer leaves a log file alongside the installer JAR
            log_file = installer_jar.with_suffix(installer_jar.suffix + ".log")
            log_file.unlink(missing_ok=True)

        return output_dir / "run.sh"
