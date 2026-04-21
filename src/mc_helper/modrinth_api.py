"""Shared Modrinth API helpers used by modpack and mod installers."""

import json

import requests

from mc_helper.http_client import get_json

_API_BASE = "https://api.modrinth.com/v2"


def resolve_version(
    session: requests.Session,
    project: str,
    minecraft_version: str | None,
    loader: str | None,
    version_type: str = "release",
    requested_version: str = "LATEST",
) -> dict:
    """Return the best matching version object for *project*."""
    if requested_version and requested_version.upper() != "LATEST":
        versions = get_json(session, f"{_API_BASE}/project/{project}/version")
        for v in versions:  # type: ignore[union-attr]
            if v["version_number"] == requested_version or v["id"] == requested_version:
                return v
        raise ValueError(
            f"Modrinth version '{requested_version}' not found for project '{project}'"
        )

    params: list[str] = []
    if minecraft_version:
        params.append(f'game_versions=["{minecraft_version}"]')
    if loader:
        params.append(f'loaders=["{loader}"]')
    query = "&".join(params)
    url = f"{_API_BASE}/project/{project}/version"
    if query:
        url += f"?{query}"

    versions = get_json(session, url)
    if not versions:
        raise ValueError(
            f"No Modrinth versions found for project '{project}' "
            f"(mc={minecraft_version}, loader={loader})"
        )

    preference = ["release", "beta", "alpha"]
    if version_type in preference:
        preference = [version_type] + [t for t in preference if t != version_type]

    for vtype in preference:
        for v in versions:  # type: ignore[union-attr]
            if v.get("version_type") == vtype:
                return v

    return versions[0]  # type: ignore[index]


def pick_primary_file(version: dict) -> tuple[str, str, str | None, str | None]:
    """Return (url, filename, sha1_or_None, sha512_or_None) for the primary or first file."""
    for f in version.get("files", []):
        if f.get("primary"):
            hashes = f.get("hashes", {})
            return f["url"], f["filename"], hashes.get("sha1"), hashes.get("sha512")
    f = version["files"][0]
    hashes = f.get("hashes", {})
    return f["url"], f["filename"], hashes.get("sha1"), hashes.get("sha512")


def mrpack_url(version: dict) -> str:
    """Pick the primary .mrpack file URL from a version object."""
    for f in version.get("files", []):
        if f.get("primary"):
            return f["url"]
    return version["files"][0]["url"]


def project_id_from_url(url: str) -> str | None:
    """Extract the Modrinth project ID from a CDN URL."""
    parts = url.split("/")
    try:
        idx = parts.index("data")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return None


def resolve_project_slugs(session: requests.Session, project_ids: list[str]) -> dict[str, str]:
    """Batch-resolve Modrinth project IDs to slugs. Returns ``{project_id: slug}``."""
    if not project_ids:
        return {}
    ids_json = json.dumps(project_ids)
    url = f"{_API_BASE}/projects?ids={ids_json}"
    data = get_json(session, url)
    return {item["id"]: item.get("slug", "") for item in data}  # type: ignore[union-attr]
