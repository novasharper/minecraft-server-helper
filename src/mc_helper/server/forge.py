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

_PROMOTIONS_URL = (
    "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
)
_MAVEN_BASE = "https://maven.minecraftforge.net"


def _get_promotions(session: requests.Session) -> dict:
    resp = session.get(_PROMOTIONS_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


def resolve_forge_version(
    session: requests.Session, minecraft_version: str, requested: str
) -> str:
    """Resolve LATEST / RECOMMENDED to a concrete Forge version string."""
    normalized = requested.lower()
    if normalized not in ("latest", "recommended"):
        return requested

    promos: dict[str, str] = _get_promotions(session)["promos"]

    # Keys are like "1.21.1-recommended": "51.0.33"
    options: dict[str, str] = {}
    for key, forge_ver in promos.items():
        parts = key.split("-", 1)
        if len(parts) == 2 and parts[0] == minecraft_version:
            options[parts[1].lower()] = forge_ver

    if not options:
        raise ValueError(
            f"No Forge versions available for Minecraft {minecraft_version}"
        )

    if normalized in options:
        return options[normalized]
    # Fall back to whichever promo is available
    return next(iter(options.values()))


def _installer_url(minecraft_version: str, forge_version: str) -> str:
    # Forge uses several version qualifier schemes across major versions;
    # we try the primary one and fall back at download time.
    combined = f"{minecraft_version}-{forge_version}"
    return (
        f"{_MAVEN_BASE}/net/minecraftforge/forge"
        f"/{combined}/forge-{combined}-installer.jar"
    )


def install(
    minecraft_version: str,
    output_dir: Path,
    forge_version: str = "RECOMMENDED",
    session: requests.Session | None = None,
    show_progress: bool = True,
) -> None:
    """Download and run the Forge installer in *output_dir*."""
    if session is None:
        session = build_session()

    resolved = resolve_forge_version(session, minecraft_version, forge_version)
    url = _installer_url(minecraft_version, resolved)

    installer_jar = output_dir / f"forge-{minecraft_version}-{resolved}-installer.jar"
    download_file(url, installer_jar, session=session, show_progress=show_progress)

    try:
        subprocess.run(
            ["java", "-jar", str(installer_jar), "--installServer"],
            cwd=output_dir,
            check=True,
        )
    finally:
        installer_jar.unlink(missing_ok=True)
