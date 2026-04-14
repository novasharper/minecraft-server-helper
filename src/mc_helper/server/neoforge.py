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

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file

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


def _list_versions(session: requests.Session, minecraft_version: str) -> list[str]:
    resp = session.get(_maven_metadata_url(minecraft_version), timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    return [v.text for v in root.findall(".//versions/version") if v.text]


def resolve_neoforge_version(
    session: requests.Session, minecraft_version: str, requested: str
) -> str:
    """Resolve LATEST (or None) to a concrete NeoForge version."""
    if requested and requested.upper() != "LATEST":
        return requested

    versions = _list_versions(session, minecraft_version)
    if not versions:
        raise ValueError(f"No NeoForge versions found for Minecraft {minecraft_version}")

    mc_minor = minecraft_version.split(".")[1] if not _use_forge_artifact(minecraft_version) else None

    # Filter to versions matching the MC minor series (e.g. 21.1.x for 1.21.1)
    if mc_minor:
        matching = [v for v in versions if v.startswith(f"{mc_minor}.")]
        if matching:
            versions = matching

    return versions[-1]  # Maven lists oldest→newest; take last


def _installer_url(minecraft_version: str, neoforge_version: str) -> str:
    artifact = _artifact_id(minecraft_version)
    if _use_forge_artifact(minecraft_version):
        ver = f"{minecraft_version}-{neoforge_version}"
    else:
        ver = neoforge_version
    return (
        f"{_MAVEN_BASE}/{_GROUP_PATH}/{artifact}"
        f"/{ver}/{artifact}-{ver}-installer.jar"
    )


def install(
    minecraft_version: str,
    output_dir: Path,
    neoforge_version: str = "LATEST",
    session: requests.Session | None = None,
    show_progress: bool = True,
) -> None:
    """Download and run the NeoForge installer in *output_dir*."""
    if session is None:
        session = build_session()

    resolved = resolve_neoforge_version(session, minecraft_version, neoforge_version)
    url = _installer_url(minecraft_version, resolved)

    installer_jar = output_dir / f"neoforge-{resolved}-installer.jar"
    download_file(url, installer_jar, session=session, show_progress=show_progress)

    try:
        subprocess.run(
            ["java", "-jar", str(installer_jar), "--installServer"],
            cwd=output_dir,
            check=True,
        )
    finally:
        installer_jar.unlink(missing_ok=True)
