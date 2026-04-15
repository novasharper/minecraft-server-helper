"""Fabric server launcher installer.

Reference: mc-image-helper/.../fabric/FabricMetaClient.java
Reference: mc-image-helper/.../fabric/FabricLauncherInstaller.java
API base: https://meta.fabricmc.net
"""

from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file, get_json

_META_BASE = "https://meta.fabricmc.net"


def resolve_loader_version(
    session: requests.Session, minecraft_version: str, requested: str
) -> str:
    """Return the concrete loader version to use."""
    if requested.upper() != "LATEST":
        return requested
    versions = get_json(
        session, f"{_META_BASE}/v2/versions/loader/{minecraft_version}"
    )
    if not versions:
        raise ValueError(
            f"No Fabric loader versions found for Minecraft {minecraft_version}"
        )
    return versions[0]["loader"]["version"]


def resolve_installer_version(session: requests.Session, requested: str) -> str:
    """Return the concrete installer version to use."""
    if requested.upper() != "LATEST":
        return requested
    versions = get_json(session, f"{_META_BASE}/v2/versions/installer")
    if not versions:
        raise ValueError("No Fabric installer versions found")
    return versions[0]["version"]


def install(
    minecraft_version: str,
    output_dir: Path,
    loader_version: str = "LATEST",
    installer_version: str = "LATEST",
    session: requests.Session | None = None,
    show_progress: bool = True,
) -> Path:
    """Download the Fabric server launcher JAR into *output_dir*.

    Returns the path to the downloaded JAR.
    """
    if session is None:
        session = build_session()

    resolved_loader = resolve_loader_version(session, minecraft_version, loader_version)
    resolved_installer = resolve_installer_version(session, installer_version)

    url = (
        f"{_META_BASE}/v2/versions/loader"
        f"/{minecraft_version}/{resolved_loader}/{resolved_installer}/server/jar"
    )

    dest = output_dir / "fabric-server-launch.jar"
    download_file(url, dest, session=session, show_progress=show_progress)
    return dest
