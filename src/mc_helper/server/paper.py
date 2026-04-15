"""PaperMC server JAR installer.

Reference: mc-image-helper/.../paper/PaperDownloadsClient.java
Reference: mc-image-helper/.../paper/InstallPaperCommand.java
API: https://fill.papermc.io  (v3)

Endpoint used:
  GET /v3/projects/{project}/versions/{version}/builds/latest
  Response: { id, channel, downloads: { "server:default": { name, url, checksums: { sha256 } } } }
"""

from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file, get_json

_API_BASE = "https://fill.papermc.io"


def resolve_version(session: requests.Session, minecraft_version: str) -> str:
    """Pass-through — Paper versions map 1:1 to Minecraft versions."""
    return minecraft_version


def get_latest_build(session: requests.Session, project: str, version: str) -> dict:
    """Return the latest build response dict for *project* / *version*."""
    url = f"{_API_BASE}/v3/projects/{project}/versions/{version}/builds/latest"
    return get_json(session, url)


def install(
    minecraft_version: str,
    output_dir: Path,
    project: str = "paper",
    session: requests.Session | None = None,
    show_progress: bool = True,
) -> Path:
    """Download the latest Paper (or Folia/Waterfall) build for *minecraft_version*.

    Returns the path to the downloaded JAR.
    """
    if session is None:
        session = build_session()

    build = get_latest_build(session, project, minecraft_version)
    download_info = build.get("downloads", {}).get("server:default")
    if not download_info:
        raise ValueError(
            f"No server download found in Paper build response for {project} {minecraft_version}"
        )

    url = download_info["url"]
    name = download_info["name"]
    sha256 = download_info.get("checksums", {}).get("sha256")

    dest = output_dir / name
    download_file(url, dest, session=session, expected_sha256=sha256, show_progress=show_progress)
    return dest
