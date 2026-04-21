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

import json
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from mc_helper.config import CurseForgeSource, ModpackConfig
from mc_helper.curseforge_api import CurseForgeClient
from mc_helper.http_client import download_file
from mc_helper.manifest import Manifest

from ._archives import extract_zip_overrides
from ._filters import load_exclude_include, matches_any

log = logging.getLogger(__name__)

_MAX_WORKERS = 10
_MODPACK_CLASS_ID = 4471
_MOD_CLASS_ID = 6


def _is_server_mod(file_obj: dict) -> bool:
    """Return True if the file should be installed server-side."""
    game_versions_lower = [v.lower() for v in file_obj.get("gameVersions", [])]
    if "server" in game_versions_lower:
        return True
    if "client" in game_versions_lower:
        return False
    return True


def _should_include(file_ref: dict, exclude: list[str], force_include: list[str]) -> bool:
    """Pre-download filter on the manifest file reference (uses numeric project ID)."""
    project_id_str = str(file_ref.get("projectID", ""))
    for pat in force_include:
        if matches_any([pat], project_id_str):
            return True
    for pat in exclude:
        if matches_any([pat], project_id_str):
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
    """Post-metadata filter: filename patterns, global slugs, client-only."""
    file_name = file_obj.get("fileName", "")

    if matches_any(force_include, file_name):
        return True
    if mod_slug and mod_slug in force_include_slugs:
        return True
    if mod_slug and mod_slug in excluded_slugs:
        return False
    if matches_any(exclude, file_name):
        return False
    return _is_server_mod(file_obj)


class CurseForgePackInstaller:
    """Installs a CurseForge modpack."""

    def __init__(
        self,
        source: CurseForgeSource,
        modpack: ModpackConfig,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.source = source
        self.modpack = modpack
        self.show_progress = show_progress
        self.cf = CurseForgeClient(source.api_key, session=session)

    def _get_modpack_file(self, mod_id: int) -> dict:
        """Return the client pack file object, skipping isServerPack entries."""
        file_id = self.source.file_id
        if file_id is not None:
            return self.cf.get_mod_file(mod_id, file_id)

        files = self.cf.get_mod_files(mod_id)
        if not files:
            raise ValueError(f"No files found for CurseForge mod {mod_id}")

        files = [f for f in files if not f.get("isServerPack")]

        matcher = self.source.filename_matcher
        if matcher is not None:
            files = [f for f in files if matcher in f["fileName"]]
            if not files:
                raise ValueError(
                    f"No non-server-pack files matching {matcher!r} found for "
                    f"CurseForge mod {mod_id}"
                )
        if not files:
            raise ValueError(f"No non-server-pack files found for CurseForge mod {mod_id}")
        return files[0]

    def install(self, output_dir: Path) -> dict:
        """Install the CurseForge modpack into *output_dir*.

        Returns the parsed manifest.json dict.
        """
        manifest = Manifest(output_dir)
        manifest.load()

        # 1. Resolve modpack mod + file
        mod_id: int | None = None
        slug = self.source.slug
        if slug:
            mod_obj = self.cf.search_by_slug(slug, class_id=_MODPACK_CLASS_ID)
            if mod_obj is None:
                raise ValueError(f"CurseForge modpack not found for slug '{slug}'")
            mod_id = mod_obj["id"]
            log.info("Resolved CurseForge modpack '%s' → mod_id=%d", slug, mod_id)
        else:
            raise ValueError("source.slug is required for CurseForge modpacks")

        pack_file = self._get_modpack_file(mod_id)
        log.info("Using modpack file: %s (id=%d)", pack_file.get("fileName"), pack_file.get("id"))
        pack_url = CurseForgeClient.download_url_for(pack_file)
        log.debug("Downloading modpack ZIP: %s", pack_url)

        # 2. Download ZIP
        tmp_zip = output_dir / ".mc-helper-curseforge.tmp.zip"
        output_dir.mkdir(parents=True, exist_ok=True)
        download_file(pack_url, tmp_zip, session=self.cf.session, show_progress=self.show_progress)

        exclude = self.modpack.exclude_mods or []
        force_include = self.modpack.force_include_mods or []
        overrides_excl = self.modpack.overrides_exclusions or []

        try:
            with zipfile.ZipFile(tmp_zip) as zf:
                pack_manifest = json.loads(zf.read("manifest.json"))

                overrides_dir = pack_manifest.get("overrides", "overrides")
                file_refs: list[dict] = pack_manifest.get("files", [])

                filtered_refs = [
                    ref for ref in file_refs if _should_include(ref, exclude, force_include)
                ]

                cf_filter = load_exclude_include("cf")
                pack_overrides = cf_filter.get("modpacks", {}).get(slug or "", {})

                global_excluded_slugs: set[str] = set(cf_filter.get("globalExcludes", []))
                global_excluded_slugs.update(pack_overrides.get("excludes", []))

                global_force_include_slugs: set[str] = set(cf_filter.get("globalForceIncludes", []))
                global_force_include_slugs.update(pack_overrides.get("forceIncludes", []))

                project_ids = [ref["projectID"] for ref in filtered_refs]
                slug_map = self.cf.resolve_slugs(project_ids)

                log.info(
                    "Downloading %d mod file(s) (%d skipped as optional/excluded)...",
                    len(filtered_refs),
                    len(file_refs) - len(filtered_refs),
                )

                new_files: list[str] = []
                cf = self.cf

                def _download_mod(ref: dict) -> str | None:
                    file_obj = cf.get_mod_file(ref["projectID"], ref["fileID"])
                    mod_slug = slug_map.get(ref["projectID"])
                    if not _passes_file_filter(
                        file_obj,
                        exclude,
                        force_include,
                        global_excluded_slugs,
                        global_force_include_slugs,
                        mod_slug,
                    ):
                        return None
                    url = CurseForgeClient.download_url_for(file_obj)
                    fname = file_obj["fileName"]
                    dest = output_dir / "mods" / fname
                    sha1 = CurseForgeClient.sha1_of(file_obj)
                    download_file(
                        url, dest, session=cf.session, expected_sha1=sha1, show_progress=False
                    )
                    return str(Path("mods") / fname)

                with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                    futures = {pool.submit(_download_mod, ref): ref for ref in filtered_refs}
                    for fut in as_completed(futures):
                        result = fut.result()
                        if result is not None:
                            new_files.append(result)

                override_files = extract_zip_overrides(
                    zf, output_dir, [overrides_dir], overrides_excl
                )
                log.info("Extracted %d override file(s)", len(override_files))
                new_files.extend(override_files)

            manifest.cleanup_stale(new_files)
            manifest.files = new_files
            mc_info = pack_manifest.get("minecraft", {})
            manifest.mc_version = mc_info.get("version")
            mod_loaders = mc_info.get("modLoaders", [])
            if mod_loaders:
                primary = next((ml for ml in mod_loaders if ml.get("primary")), mod_loaders[0])
                loader_id: str = primary["id"]
                parts = loader_id.split("-", 1)
                manifest.loader_type = parts[0]
                manifest.loader_version = parts[1] if len(parts) > 1 else loader_id
            manifest.save()

        finally:
            tmp_zip.unlink(missing_ok=True)

        return pack_manifest
