"""CurseForge modpack installer.

Reference: mc-image-helper/.../curseforge/CurseForgeInstaller.java
Reference: mc-image-helper/.../curseforge/CurseForgeApiClient.java
Reference: docker-minecraft-server/scripts/start-deployAutoCF
API base: https://api.curseforge.com  (requires X-Api-Key header)

Workflow:
  1. Resolve modpack: search by slug → get latest/specific file (skip isServerPack files)
  2. Download modpack ZIP → parse manifest.json
  3. For each required file: GET /v1/mods/{projectId}/files/{fileId} → apply filters
     - Skip client-only mods (gameVersions check)
     - Skip globally excluded slugs (cf-exclude-include.json); resolved via POST /v1/mods
     - Skip user-excluded patterns (matched against fileName)
  4. Extract overrides/ into output_dir
  5. Cleanup stale, save manifest
"""

import fnmatch
import json
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file, get_json
from mc_helper.manifest import Manifest
from mc_helper.utils import extract_zip_overrides

log = logging.getLogger(__name__)

_API_BASE = "https://api.curseforge.com"
_MINECRAFT_GAME_ID = "432"
_MAX_WORKERS = 10
_DATA_DIR = Path(__file__).parent.parent / "data"


def _load_cf_filter() -> dict:
    """Load the bundled CurseForge exclude/include filter file."""
    path = _DATA_DIR / "cf-exclude-include.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"globalExcludes": [], "modpacks": {}}


def _download_url_for_file(file_obj: dict) -> str:
    """Return the download URL, constructing a fallback if the API returns null."""
    url = file_obj.get("downloadUrl")
    if url:
        return url
    # Fallback construction used by mc-image-helper for mods with null downloadUrl
    fid = file_obj["id"]
    name = file_obj["fileName"]
    return f"https://edge.forgecdn.net/files/{fid // 1000}/{fid % 1000}/{name}"


def _is_server_mod(file_obj: dict) -> bool:
    """Return True if the file should be installed server-side.

    Mirrors CurseForgeInstaller.isServerMod(): include if 'Server' is present in
    gameVersions, or if neither 'Client' nor 'Server' is listed (assume server-safe).
    """
    game_versions_lower = [v.lower() for v in file_obj.get("gameVersions", [])]
    if "server" in game_versions_lower:
        return True
    if "client" in game_versions_lower:
        return False
    return True


def _should_include(file_ref: dict, exclude: list[str], force_include: list[str]) -> bool:
    """Pre-download filter on the manifest file reference.

    Checks the ``required`` field and matches *exclude*/*force_include* patterns
    against the numeric project ID (as a string) so that callers can pass raw
    project IDs as filter patterns.  Filename-based and slug-based filtering
    happens later in ``_passes_file_filter`` once the file metadata is available.
    """
    project_id_str = str(file_ref.get("projectID", ""))
    for pat in force_include:
        if fnmatch.fnmatch(project_id_str, pat):
            return True
    for pat in exclude:
        if fnmatch.fnmatch(project_id_str, pat):
            return False
    return file_ref.get("required", True)


def _passes_file_filter(
    file_obj: dict,
    exclude: list[str],
    force_include: list[str],
    excluded_slugs: set[str],
    force_include_slugs: set[str],
    mod_slug: str | None,
) -> bool:
    """Post-metadata filter applied once we have the file object and mod slug.

    Checks (in order):
      1. Force-include by filename pattern → always include
      2. Global slug force-include → always include
      3. Global slug exclude → skip
      4. User filename-pattern exclude → skip
      5. Client-only detection via gameVersions → skip client-only
    """
    file_name = file_obj.get("fileName", "")

    # Force-include wins over everything
    for pat in force_include:
        if fnmatch.fnmatch(file_name, pat):
            return True
    if mod_slug and mod_slug in force_include_slugs:
        return True

    # Global slug exclusion
    if mod_slug and mod_slug in excluded_slugs:
        return False

    # User filename-pattern exclusion (B1 fix: match against fileName, not projectID)
    for pat in exclude:
        if fnmatch.fnmatch(file_name, pat):
            return False

    # Client-only detection (G2 fix)
    return _is_server_mod(file_obj)


class CurseForgePackInstaller:
    """Installs a CurseForge modpack."""

    def __init__(
        self,
        api_key: str,
        slug: str | None = None,
        mod_id: int | None = None,
        file_id: int | None = None,
        filename_matcher: str | None = None,
        exclude_mods: list[str] | None = None,
        force_include_mods: list[str] | None = None,
        overrides_exclusions: list[str] | None = None,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.api_key = api_key
        self.slug = slug
        self.mod_id = mod_id
        self.file_id = file_id
        self.filename_matcher = filename_matcher
        self.exclude_mods = exclude_mods or []
        self.force_include_mods = force_include_mods or []
        self.overrides_exclusions = overrides_exclusions or []
        self.show_progress = show_progress

        if session is None:
            self.session = build_session(extra_headers={"X-Api-Key": api_key})
        else:
            self.session = session
            self.session.headers["X-Api-Key"] = api_key

    def _search_modpack(self, slug: str) -> dict:
        """Return the mod object for the given slug (must be a modpack)."""
        resp = get_json(
            self.session,
            f"{_API_BASE}/v1/mods/search"
            f"?gameId={_MINECRAFT_GAME_ID}&slug={slug}&classId=4471",  # 4471 = Modpacks class
        )
        data = resp.get("data", [])  # type: ignore[union-attr]
        if not data:
            raise ValueError(f"CurseForge modpack not found for slug '{slug}'")
        return data[0]

    def _get_modpack_file(
        self,
        mod_id: int,
        file_id: int | None,
        filename_matcher: str | None = None,
    ) -> dict:
        """Return the client pack file object, skipping isServerPack entries."""
        if file_id is not None:
            resp = get_json(self.session, f"{_API_BASE}/v1/mods/{mod_id}/files/{file_id}")
            return resp["data"]  # type: ignore[index]

        resp = get_json(self.session, f"{_API_BASE}/v1/mods/{mod_id}/files")
        files = resp["data"]  # type: ignore[index]
        if not files:
            raise ValueError(f"No files found for CurseForge mod {mod_id}")

        # G3 fix: exclude server-pack files (they have no manifest.json)
        files = [f for f in files if not f.get("isServerPack")]

        if filename_matcher is not None:
            files = [f for f in files if filename_matcher in f["fileName"]]
            if not files:
                raise ValueError(
                    f"No non-server-pack files matching {filename_matcher!r} found for "
                    f"CurseForge mod {mod_id}"
                )
        if not files:
            raise ValueError(
                f"No non-server-pack files found for CurseForge mod {mod_id}"
            )
        return files[0]

    def _get_mod_file(self, project_id: int, file_id: int) -> dict:
        resp = get_json(self.session, f"{_API_BASE}/v1/mods/{project_id}/files/{file_id}")
        return resp["data"]  # type: ignore[index]

    def _resolve_mod_slugs(self, project_ids: list[int]) -> dict[int, str]:
        """Batch-resolve project IDs to slugs via POST /v1/mods.

        Returns a mapping of {project_id: slug}.
        """
        if not project_ids:
            return {}
        resp = self.session.post(
            f"{_API_BASE}/v1/mods",
            json={"modIds": project_ids},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return {item["id"]: item.get("slug", "") for item in data}

    def install(self, output_dir: Path) -> dict:
        """Install the CurseForge modpack into *output_dir*.

        Returns the parsed manifest.json dict.
        """
        manifest = Manifest(output_dir)
        manifest.load()

        # 1. Resolve modpack mod + file
        mod_id = self.mod_id
        if mod_id is None:
            if not self.slug:
                raise ValueError("Either slug or mod_id must be provided")
            mod_obj = self._search_modpack(self.slug)
            mod_id = mod_obj["id"]
            log.info("Resolved CurseForge modpack '%s' → mod_id=%d", self.slug, mod_id)

        pack_file = self._get_modpack_file(mod_id, self.file_id, self.filename_matcher)
        log.info("Using modpack file: %s (id=%d)", pack_file.get("fileName"), pack_file.get("id"))
        pack_url = _download_url_for_file(pack_file)
        log.debug("Downloading modpack ZIP: %s", pack_url)

        # 2. Download ZIP
        tmp_zip = output_dir / ".mc-helper-curseforge.tmp.zip"
        output_dir.mkdir(parents=True, exist_ok=True)
        download_file(pack_url, tmp_zip, session=self.session, show_progress=self.show_progress)

        try:
            with zipfile.ZipFile(tmp_zip) as zf:
                pack_manifest = json.loads(zf.read("manifest.json"))

                overrides_dir = pack_manifest.get("overrides", "overrides")
                file_refs: list[dict] = pack_manifest.get("files", [])

                # First-pass filter: required field + numeric project-ID patterns
                filtered_refs = [
                    ref
                    for ref in file_refs
                    if _should_include(ref, self.exclude_mods, self.force_include_mods)
                ]

                # G1 fix: load global exclude/include filter and batch-resolve slugs
                cf_filter = _load_cf_filter()
                modpack_slug = self.slug or ""
                modpack_overrides = cf_filter.get("modpacks", {}).get(modpack_slug, {})

                global_excluded_slugs: set[str] = set(cf_filter.get("globalExcludes", []))
                global_excluded_slugs.update(modpack_overrides.get("excludes", []))

                global_force_include_slugs: set[str] = set(
                    cf_filter.get("globalForceIncludes", [])
                )
                global_force_include_slugs.update(modpack_overrides.get("forceIncludes", []))

                # Batch-resolve slugs for all candidate project IDs
                project_ids = [ref["projectID"] for ref in filtered_refs]
                slug_map = self._resolve_mod_slugs(project_ids)

                log.info(
                    "Downloading %d mod file(s) (%d skipped as optional/excluded)...",
                    len(filtered_refs), len(file_refs) - len(filtered_refs),
                )
                # 3. Download each mod file in parallel
                new_files: list[str] = []
                session = self.session
                exclude = self.exclude_mods
                force_include = self.force_include_mods

                def _download_mod(ref: dict) -> str | None:
                    file_obj = self._get_mod_file(ref["projectID"], ref["fileID"])
                    mod_slug = slug_map.get(ref["projectID"])

                    # Post-metadata filter: filename patterns, global slugs, client-only
                    if not _passes_file_filter(
                        file_obj,
                        exclude,
                        force_include,
                        global_excluded_slugs,
                        global_force_include_slugs,
                        mod_slug,
                    ):
                        return None

                    url = _download_url_for_file(file_obj)
                    fname = file_obj["fileName"]
                    dest = output_dir / "mods" / fname
                    hashes = file_obj.get("hashes", [])
                    sha1 = next((h["value"] for h in hashes if h.get("algo") == 1), None)
                    download_file(
                        url, dest, session=session, expected_sha1=sha1, show_progress=False
                    )
                    return str(Path("mods") / fname)

                with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                    futures = {pool.submit(_download_mod, ref): ref for ref in filtered_refs}
                    for fut in as_completed(futures):
                        result = fut.result()
                        if result is not None:
                            new_files.append(result)

                # 4. Extract overrides
                override_files = extract_zip_overrides(
                    zf, output_dir, [overrides_dir], self.overrides_exclusions
                )
                log.info("Extracted %d override file(s)", len(override_files))
                new_files.extend(override_files)

            # 5. Cleanup stale + save manifest
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
