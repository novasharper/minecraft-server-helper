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


def resolve_build(session: requests.Session, minecraft_version: str) -> str:
    """Return the latest build number string for *minecraft_version*."""
    data = get_json(session, f"{_API_BASE}/v2/purpur/{minecraft_version}")
    latest = data.get("builds", {}).get("latest")
    if not latest:
        raise ValueError(f"No Purpur builds found for Minecraft {minecraft_version}")
    return str(latest)


def install(
    minecraft_version: str,
    output_dir: Path,
    build: str = "LATEST",
    session: requests.Session | None = None,
    show_progress: bool = True,
) -> Path:
    """Download the Purpur server JAR for *minecraft_version* into *output_dir*.

    Returns the path to the downloaded JAR.
    """
    if session is None:
        session = build_session()

    resolved_build = (
        resolve_build(session, minecraft_version) if build.upper() == "LATEST" else build
    )

    url = f"{_API_BASE}/v2/purpur/{minecraft_version}/{resolved_build}/download"
    dest = output_dir / f"purpur-{minecraft_version}-{resolved_build}.jar"
    download_file(url, dest, session=session, show_progress=show_progress)
    return dest
