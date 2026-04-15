"""CurseForge individual mod installer.

Reference: mc-image-helper/.../curseforge/CurseForgeApiClient.java
Reference: docker-minecraft-server/docs/variables.md (CURSEFORGE_FILES formats)

Spec formats:
  jei                                    → latest file for mc version (slug)
  jei:4593548                            → specific file ID by slug
  238222                                 → project ID (latest file)
  238222:4593548                         → project ID + file ID
  https://www.curseforge.com/.../jei     → page URL (slug extracted)
"""

from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file
from mc_helper.modpack.curseforge import _download_url_for_file, _get_json

_API_BASE = "https://api.curseforge.com"
_MINECRAFT_GAME_ID = "432"
_MOD_CLASS_ID = 6


def parse_mod_spec(spec: str) -> tuple[str | int, int | None]:
    """Return (slug_or_project_id, file_id_or_None).

    - Full URL  → slug extracted from the last path segment
    - ``slug:file_id`` or ``project_id:file_id`` → both parts parsed
    - Numeric string → project ID
    - Plain string → slug
    """
    if spec.startswith("http"):
        slug = spec.rstrip("/").split("/")[-1]
        return slug, None
    if ":" in spec:
        left, right = spec.split(":", 1)
        project: str | int = int(left) if left.isdigit() else left
        return project, int(right)
    if spec.isdigit():
        return int(spec), None
    return spec, None


def _resolve_project_id(session: requests.Session, slug: str) -> int:
    """Return the CurseForge project ID for the given mod slug."""
    resp = _get_json(
        session,
        f"{_API_BASE}/v1/mods/search"
        f"?gameId={_MINECRAFT_GAME_ID}&slug={slug}&classId={_MOD_CLASS_ID}",
    )
    data = resp.get("data", [])  # type: ignore[union-attr]
    if not data:
        raise ValueError(f"CurseForge mod not found for slug '{slug}'")
    return data[0]["id"]


def _get_latest_file(
    session: requests.Session, project_id: int, minecraft_version: str | None
) -> dict:
    """Return the newest compatible file object for *project_id*."""
    url = f"{_API_BASE}/v1/mods/{project_id}/files"
    if minecraft_version:
        url += f"?gameVersion={minecraft_version}"
    resp = _get_json(session, url)
    files = resp["data"]  # type: ignore[index]
    if not files:
        raise ValueError(f"No files found for CurseForge mod {project_id}")
    return files[0]


def install_mod(
    spec: str,
    output_dir: Path,
    api_key: str,
    minecraft_version: str | None = None,
    session: requests.Session | None = None,
    show_progress: bool = True,
) -> str:
    """Download a single CurseForge mod JAR to ``output_dir/mods/``.

    Returns the relative path written (e.g. ``"mods/jei-1.21.1-18.0.0.1.jar"``).
    """
    if session is None:
        session = build_session(extra_headers={"X-Api-Key": api_key})
    else:
        session.headers["X-Api-Key"] = api_key

    project, file_id = parse_mod_spec(spec)

    project_id: int = (
        project if isinstance(project, int) else _resolve_project_id(session, project)
    )

    if file_id is not None:
        resp = _get_json(session, f"{_API_BASE}/v1/mods/{project_id}/files/{file_id}")
        file_obj = resp["data"]  # type: ignore[index]
    else:
        file_obj = _get_latest_file(session, project_id, minecraft_version)

    url = _download_url_for_file(file_obj)
    filename = file_obj["fileName"]
    dest = output_dir / "mods" / filename
    download_file(url, dest, session=session, show_progress=show_progress)
    return str(Path("mods") / filename)
