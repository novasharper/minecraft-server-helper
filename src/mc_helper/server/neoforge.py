"""NeoForge server installer.

Reference: mc-image-helper/.../forge/NeoForgeInstallerResolver.java
Reference: docker-minecraft-server/scripts/start-deployNeoForge

NeoForge uses Maven metadata XML to list available versions.
For Minecraft 1.20.1 the artifact ID is "forge" (forge-like); for all later
versions it is "neoforge" and the version string is independent of the
Minecraft version (it starts with the MC minor version, e.g. 21.1.x for 1.21.1).

Workflow:
  1. Fetch Maven metadata XML to list available versions
  2. Pick LATEST or a specific version
  3. Download installer JAR
  4. Run `java -jar neoforge-installer.jar --installServer` in output_dir
"""

import logging
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file

log = logging.getLogger(__name__)

_MAVEN_BASE = "https://maven.neoforged.net/releases"
_GROUP_PATH = "net/neoforged"
_FORGE_LIKE_MC = "1.20.1"


def _use_forge_artifact(minecraft_version: str) -> bool:
    return minecraft_version == _FORGE_LIKE_MC


def _artifact_id(minecraft_version: str) -> str:
    return "forge" if _use_forge_artifact(minecraft_version) else "neoforge"


def _maven_metadata_url(minecraft_version: str) -> str:
    artifact = _artifact_id(minecraft_version)
    return f"{_MAVEN_BASE}/{_GROUP_PATH}/{artifact}/maven-metadata.xml"


def _installer_url(minecraft_version: str, neoforge_version: str) -> str:
    artifact = _artifact_id(minecraft_version)
    if _use_forge_artifact(minecraft_version):
        ver = f"{minecraft_version}-{neoforge_version}"
    else:
        ver = neoforge_version
    return f"{_MAVEN_BASE}/{_GROUP_PATH}/{artifact}" f"/{ver}/{artifact}-{ver}-installer.jar"


class NeoForgeInstaller:
    """Downloads and runs the NeoForge server installer."""

    def __init__(
        self,
        minecraft_version: str,
        neoforge_version: str = "LATEST",
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.minecraft_version = minecraft_version
        self.neoforge_version = neoforge_version
        self.session = session or build_session()
        self.show_progress = show_progress

    def _list_versions(self) -> list[str]:
        resp = self.session.get(_maven_metadata_url(self.minecraft_version), timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        return [v.text for v in root.findall(".//versions/version") if v.text]

    def _resolve_neoforge_version(self) -> str:
        """Resolve LATEST (or None) to a concrete NeoForge version."""
        if self.neoforge_version and self.neoforge_version.upper() != "LATEST":
            return self.neoforge_version

        versions = self._list_versions()
        if not versions:
            raise ValueError(f"No NeoForge versions found for Minecraft {self.minecraft_version}")

        # Build version prefix: NeoForge uses "{mc_minor}.{mc_patch}.x" format.
        # e.g. MC 1.21.1 → NeoForge 21.1.x; MC 1.21 → NeoForge 21.0.x
        mc_prefix: str | None = None
        if not _use_forge_artifact(self.minecraft_version):
            parts = self.minecraft_version.split(".")
            mc_minor = parts[1] if len(parts) > 1 else "0"
            mc_patch = parts[2] if len(parts) > 2 else "0"
            mc_prefix = f"{mc_minor}.{mc_patch}."

        # Filter to versions matching the exact MC minor+patch series
        if mc_prefix:
            matching = [v for v in versions if v.startswith(mc_prefix)]
            if matching:
                versions = matching

        return versions[-1]  # Maven lists oldest→newest; take last

    def install(self, output_dir: Path) -> None:
        """Download and run the NeoForge installer in *output_dir*."""
        resolved = self._resolve_neoforge_version()
        log.info("Resolved NeoForge version: %s", resolved)
        url = _installer_url(self.minecraft_version, resolved)

        installer_jar = output_dir / f"neoforge-{resolved}-installer.jar"
        log.debug("Downloading NeoForge installer: %s", url)
        download_file(url, installer_jar, session=self.session, show_progress=self.show_progress)

        log.info("Running NeoForge installer (this may take a while)...")
        try:
            subprocess.run(
                ["java", "-jar", str(installer_jar), "--installServer"],
                cwd=output_dir,
                check=True,
            )
        finally:
            installer_jar.unlink(missing_ok=True)
