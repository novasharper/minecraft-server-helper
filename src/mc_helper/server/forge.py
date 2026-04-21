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
from pathlib import Path

import requests

from mc_helper.config import ServerConfig
from mc_helper.http_client import download_file, get_json

from .base import ServerInstaller, run_java_installer

log = logging.getLogger(__name__)

_PROMOTIONS_URL = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
_MAVEN_BASE = "https://maven.minecraftforge.net"


def _installer_urls(minecraft_version: str, forge_version: str) -> list[str]:
    """Return candidate installer URLs in priority order."""
    mc, fv = minecraft_version, forge_version
    base = f"{_MAVEN_BASE}/net/minecraftforge/forge"
    return [
        f"{base}/{mc}-{fv}/forge-{mc}-{fv}-installer.jar",
        f"{base}/{mc}-{fv}-{mc}/forge-{mc}-{fv}-{mc}-installer.jar",
    ]


class ForgeInstaller(ServerInstaller):
    """Downloads and runs the Forge server installer."""

    def __init__(
        self,
        config: ServerConfig,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        super().__init__(config, session=session, show_progress=show_progress)

    def _resolve_forge_version(self) -> str:
        """Resolve LATEST / RECOMMENDED to a concrete Forge version string."""
        forge_version = self.config.loader_version
        normalized = forge_version.lower()
        if normalized not in ("latest", "recommended"):
            return forge_version

        promos: dict[str, str] = get_json(self.session, _PROMOTIONS_URL)["promos"]  # type: ignore[index]
        mc = self.config.minecraft_version

        options: dict[str, str] = {}
        for key, forge_ver in promos.items():
            parts = key.split("-", 1)
            if len(parts) == 2 and parts[0] == mc:
                options[parts[1].lower()] = forge_ver

        if not options:
            raise ValueError(f"No Forge versions available for Minecraft {mc}")

        if normalized in options:
            return options[normalized]
        return next(iter(options.values()))

    def _download_installer(self, output_dir: Path, resolved: str) -> Path:
        """Try each candidate URL in order; return the path of the downloaded JAR."""
        mc = self.config.minecraft_version
        urls = _installer_urls(mc, resolved)
        last_exc: Exception | None = None
        for url in urls:
            try:
                head = self.session.head(url, timeout=15)
                if head.status_code == 404:
                    log.debug("Forge installer not found at %s, trying next URL", url)
                    continue
                head.raise_for_status()
            except Exception as exc:
                last_exc = exc
                continue
            installer_jar = output_dir / f"forge-{mc}-{resolved}-installer.jar"
            log.debug("Downloading Forge installer: %s", url)
            download_file(
                url, installer_jar, session=self.session, show_progress=self.show_progress
            )
            return installer_jar
        raise RuntimeError(
            f"No Forge installer found for {mc}-{resolved}. Tried: {urls}"
        ) from last_exc

    def install(self, output_dir: Path) -> Path:
        """Download and run the Forge installer in *output_dir*.

        Returns the path to ``run.sh`` created by the Forge installer.
        """
        resolved = self._resolve_forge_version()
        log.info("Resolved Forge version: %s", resolved)
        installer_jar = self._download_installer(output_dir, resolved)
        log.info("Running Forge installer (this may take a while)...")
        return run_java_installer(installer_jar, output_dir)
