"""CurseForge modpack installer.

Reference: mc-image-helper/.../curseforge/CurseForgeInstaller.java
Reference: mc-image-helper/.../curseforge/CurseForgeApiClient.java
Reference: docker-minecraft-server/scripts/start-deployAutoCF
API base: https://api.curseforge.com  (requires X-Api-Key header)

Workflow:
  1. Resolve modpack: search by slug → get latest/specific file
  2. Download modpack ZIP → parse manifest.json
  3. For each required file: GET /v1/mods/{projectId}/files/{fileId} → download
  4. Apply exclude/force-include lists, skip client-only (isServerPack check omitted;
     CurseForge doesn't reliably mark client-only mods — we install everything required)
  5. Extract overrides/ into output_dir
  6. Cleanup stale, save manifest
"""

import fnmatch
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file, get_json
from mc_helper.manifest import Manifest
from mc_helper.utils import extract_zip_overrides

_API_BASE = "https://api.curseforge.com"
_MINECRAFT_GAME_ID = "432"
_MOD_CLASS_ID = 6          # "Mods" class in CurseForge taxonomy
_MAX_WORKERS = 10


def _search_modpack(session: requests.Session, slug: str) -> dict:
    """Return the mod object for the given slug (must be a modpack)."""
    resp = get_json(
        session,
        f"{_API_BASE}/v1/mods/search"
        f"?gameId={_MINECRAFT_GAME_ID}&slug={slug}&classId=4471",  # 4471 = Modpacks class
    )
    data = resp.get("data", [])  # type: ignore[union-attr]
    if not data:
        raise ValueError(f"CurseForge modpack not found for slug '{slug}'")
    return data[0]


def _get_modpack_file(
    session: requests.Session,
    mod_id: int,
    file_id: int | None,
    filename_matcher: str | None = None,
) -> dict:
    """Return the file object. If file_id is None, returns the latest file."""
    if file_id is not None:
        resp = get_json(session, f"{_API_BASE}/v1/mods/{mod_id}/files/{file_id}")
        return resp["data"]  # type: ignore[index]

    resp = get_json(session, f"{_API_BASE}/v1/mods/{mod_id}/files")
    files = resp["data"]  # type: ignore[index]
    if not files:
        raise ValueError(f"No files found for CurseForge mod {mod_id}")
    # Files are returned newest-first
    if filename_matcher is not None:
        files = [f for f in files if filename_matcher in f["fileName"]]
        if not files:
            raise ValueError(
                f"No files matching {filename_matcher!r} found for CurseForge mod {mod_id}"
            )
    return files[0]


def _get_mod_file(session: requests.Session, project_id: int, file_id: int) -> dict:
    resp = get_json(session, f"{_API_BASE}/v1/mods/{project_id}/files/{file_id}")
    return resp["data"]  # type: ignore[index]


def _download_url_for_file(file_obj: dict) -> str:
    """Return the download URL, constructing a fallback if the API returns null."""
    url = file_obj.get("downloadUrl")
    if url:
        return url
    # Fallback construction used by mc-image-helper for mods with null downloadUrl
    fid = file_obj["id"]
    name = file_obj["fileName"]
    return f"https://edge.forgecdn.net/files/{fid // 1000}/{fid % 1000}/{name}"


def _should_include(file_ref: dict, exclude: list[str], force_include: list[str]) -> bool:
    name = str(file_ref.get("projectID", ""))
    for pat in force_include:
        if fnmatch.fnmatch(name, pat):
            return True
    for pat in exclude:
        if fnmatch.fnmatch(name, pat):
            return False
    return file_ref.get("required", True)


def install(
    api_key: str,
    output_dir: Path,
    slug: str | None = None,
    mod_id: int | None = None,
    file_id: int | None = None,
    filename_matcher: str | None = None,
    exclude_mods: list[str] | None = None,
    force_include_mods: list[str] | None = None,
    overrides_exclusions: list[str] | None = None,
    session: requests.Session | None = None,
    show_progress: bool = True,
) -> dict:
    """Install a CurseForge modpack into output_dir.

    Returns the parsed manifest.json dict.
    """
    if session is None:
        session = build_session(extra_headers={"X-Api-Key": api_key})
    else:
        session.headers["X-Api-Key"] = api_key

    exclude_mods = exclude_mods or []
    force_include_mods = force_include_mods or []
    overrides_exclusions = overrides_exclusions or []

    manifest = Manifest(output_dir)
    manifest.load()

    # 1. Resolve modpack mod + file
    if mod_id is None:
        if not slug:
            raise ValueError("Either slug or mod_id must be provided")
        mod_obj = _search_modpack(session, slug)
        mod_id = mod_obj["id"]

    pack_file = _get_modpack_file(session, mod_id, file_id, filename_matcher)
    pack_url = _download_url_for_file(pack_file)

    # 2. Download ZIP
    tmp_zip = output_dir / ".mc-helper-curseforge.tmp.zip"
    output_dir.mkdir(parents=True, exist_ok=True)
    download_file(pack_url, tmp_zip, session=session, show_progress=show_progress)

    try:
        with zipfile.ZipFile(tmp_zip) as zf:
            pack_manifest = json.loads(zf.read("manifest.json"))

            overrides_dir = pack_manifest.get("overrides", "overrides")
            file_refs: list[dict] = pack_manifest.get("files", [])

            # Filter by exclude/force-include
            filtered = [
                ref for ref in file_refs
                if _should_include(ref, exclude_mods, force_include_mods)
            ]

            # 3. Download each mod file in parallel
            new_files: list[str] = []

            def _download_mod(ref: dict) -> str:
                file_obj = _get_mod_file(session, ref["projectID"], ref["fileID"])
                url = _download_url_for_file(file_obj)
                fname = file_obj["fileName"]
                dest = output_dir / "mods" / fname
                hashes = file_obj.get("hashes", [])
                sha1 = next((h["value"] for h in hashes if h.get("algo") == 1), None)
                download_file(url, dest, session=session, expected_sha1=sha1, show_progress=False)
                return str(Path("mods") / fname)

            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                futures = {pool.submit(_download_mod, ref): ref for ref in filtered}
                for fut in as_completed(futures):
                    new_files.append(fut.result())

            # 5. Extract overrides
            override_files = extract_zip_overrides(
                zf, output_dir, [overrides_dir], overrides_exclusions
            )
            new_files.extend(override_files)

        # 6. Cleanup stale + save manifest
        manifest.cleanup_stale(output_dir, new_files)
        manifest.files = new_files
        mc_info = pack_manifest.get("minecraft", {})
        manifest.mc_version = mc_info.get("version")
        mod_loaders = mc_info.get("modLoaders", [])
        if mod_loaders:
            primary = next((ml for ml in mod_loaders if ml.get("primary")), mod_loaders[0])
            loader_id: str = primary["id"]  # e.g. "forge-47.2.0" or "neoforge-21.1.0"
            parts = loader_id.split("-", 1)
            manifest.loader_type = parts[0]
            manifest.loader_version = parts[1] if len(parts) > 1 else loader_id
        manifest.save()

    finally:
        tmp_zip.unlink(missing_ok=True)

    return pack_manifest
