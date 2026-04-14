"""Vanilla Minecraft server JAR installer.

Reference: docker-minecraft-server/scripts/start-deployVanilla
API: https://launchermeta.mojang.com/mc/game/version_manifest.json
"""

from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file

_VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json"


def _get_manifest(session: requests.Session) -> dict:
    resp = session.get(_VERSION_MANIFEST_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


def resolve_version(session: requests.Session, requested: str) -> str:
    """Resolve 'LATEST', 'SNAPSHOT', or a specific version string to a concrete version ID."""
    manifest = _get_manifest(session)
    normalized = requested.upper()

    if normalized == "LATEST":
        return manifest["latest"]["release"]
    if normalized == "SNAPSHOT":
        return manifest["latest"]["snapshot"]

    ids = {v["id"] for v in manifest["versions"]}
    if requested not in ids:
        raise ValueError(f"Minecraft version '{requested}' not found in version manifest")
    return requested


def install(
    minecraft_version: str,
    output_dir: Path,
    session: requests.Session | None = None,
    show_progress: bool = True,
) -> Path:
    """Download the vanilla server JAR for *minecraft_version* into *output_dir*.

    Resolves 'LATEST' / 'SNAPSHOT' automatically.
    Returns the path to the downloaded JAR.
    """
    if session is None:
        session = build_session()

    version = resolve_version(session, minecraft_version)

    # Find the version-specific manifest URL
    manifest = _get_manifest(session)
    entry = next((v for v in manifest["versions"] if v["id"] == version), None)
    if entry is None:
        raise ValueError(f"No manifest entry for version '{version}'")

    # Fetch the version manifest to get the server download URL + sha1
    resp = session.get(entry["url"], timeout=30)
    resp.raise_for_status()
    version_data = resp.json()

    server_info = version_data.get("downloads", {}).get("server")
    if not server_info:
        raise ValueError(f"No server download available for Minecraft {version}")

    url = server_info["url"]
    sha1 = server_info.get("sha1")

    dest = output_dir / f"minecraft_server.{version}.jar"
    download_file(url, dest, session=session, expected_sha1=sha1, show_progress=show_progress)
    return dest
