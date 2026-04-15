"""Modrinth individual mod installer.

Reference: mc-image-helper/.../modrinth/ (version resolution)
Reference: docker-minecraft-server/docs/variables.md (MODRINTH_PROJECTS formats)

Spec formats:
  fabric-api                → latest release for mc/loader
  fabric-api:0.119.2+1.21.4 → specific version number
  P7dR8mSH                  → project ID (latest release)
  P7dR8mSH:abc123           → project ID + version ID
"""

from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file
from mc_helper.modpack.modrinth import resolve_version


def parse_mod_spec(spec: str) -> tuple[str, str]:
    """Return (project_slug_or_id, version_or_LATEST).

    Splits on the first colon: ``fabric-api:0.119.2+1.21.4`` → ``("fabric-api", "0.119.2+1.21.4")``.
    Bare specs return ``"LATEST"`` as the version.
    """
    if ":" in spec:
        slug, version = spec.split(":", 1)
        return slug, version
    return spec, "LATEST"


def _pick_primary_file(version: dict) -> tuple[str, str, str | None]:
    """Return (url, filename, sha1_or_None) for the primary or first file in the version."""
    for f in version.get("files", []):
        if f.get("primary"):
            return f["url"], f["filename"], f.get("hashes", {}).get("sha1")
    f = version["files"][0]
    return f["url"], f["filename"], f.get("hashes", {}).get("sha1")


def install_mod(
    spec: str,
    output_dir: Path,
    minecraft_version: str | None = None,
    loader: str | None = None,
    version_type: str = "release",
    session: requests.Session | None = None,
    show_progress: bool = True,
) -> str:
    """Download a single Modrinth mod JAR to ``output_dir/mods/``.

    Returns the relative path written (e.g. ``"mods/fabric-api-0.x.x.jar"``).
    """
    if session is None:
        session = build_session()

    project, requested_version = parse_mod_spec(spec)
    version = resolve_version(
        session, project, minecraft_version, loader, version_type, requested_version
    )
    url, filename, sha1 = _pick_primary_file(version)

    dest = output_dir / "mods" / filename
    download_file(url, dest, session=session, expected_sha1=sha1, show_progress=show_progress)
    return str(Path("mods") / filename)
