"""Forge server installer.

Reference: mc-image-helper/.../forge/ForgeInstallerResolver.java
Reference: mc-image-helper/.../forge/ForgeLikeInstaller.java
Reference: docker-minecraft-server/scripts/start-deployForge

Workflow:
  1. Resolve forge version via promotions_slim.json (supports LATEST / RECOMMENDED)
  2. Download installer JAR from Forge Maven
  3. Run `java -jar forge-installer.jar --installServer` in output_dir
"""

import subprocess
from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file

_PROMOTIONS_URL = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
_MAVEN_BASE = "https://maven.minecraftforge.net"


def _installer_url(minecraft_version: str, forge_version: str) -> str:
    # Forge uses several version qualifier schemes across major versions;
    # we try the primary one and fall back at download time.
    combined = f"{minecraft_version}-{forge_version}"
    return f"{_MAVEN_BASE}/net/minecraftforge/forge" f"/{combined}/forge-{combined}-installer.jar"


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

    def install(self, output_dir: Path) -> None:
        """Download and run the Forge installer in *output_dir*."""
        resolved = self._resolve_forge_version()
        url = _installer_url(self.minecraft_version, resolved)

        installer_jar = output_dir / f"forge-{self.minecraft_version}-{resolved}-installer.jar"
        download_file(url, installer_jar, session=self.session, show_progress=self.show_progress)

        try:
            subprocess.run(
                ["java", "-jar", str(installer_jar), "--installServer"],
                cwd=output_dir,
                check=True,
            )
        finally:
            installer_jar.unlink(missing_ok=True)
