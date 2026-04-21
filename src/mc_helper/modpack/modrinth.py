"""Modrinth modpack installer.

Reference: mc-image-helper/.../modrinth/ModrinthPackInstaller.java
Reference: mc-image-helper/.../modrinth/ModrinthApiPackFetcher.java
Reference: docker-minecraft-server/scripts/start-deployModrinth
API base: https://api.modrinth.com/v2

Workflow:
  1. Resolve project version via /v2/project/{id}/versions
  2. Download .mrpack (ZIP)
  3. Parse modrinth.index.json: dependencies (loader), files[]
  4. Skip files where env.server == "unsupported"
  5. Download files to output_dir/<path>
  6. Extract overrides/ and server-overrides/ into output_dir
  7. Auto-install mod loader based on dependencies
  8. Cleanup stale files, save manifest
"""

import json
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from mc_helper.config import ModpackConfig, ModrinthSource, ServerConfig
from mc_helper.http_client import build_session, download_file
from mc_helper.manifest import Manifest
from mc_helper.modrinth_api import (
    mrpack_url,
    project_id_from_url,
    resolve_project_slugs,
    resolve_version,
)

from ._archives import extract_zip_overrides
from ._filters import load_exclude_include, matches_any

log = logging.getLogger(__name__)

_MAX_WORKERS = 10


def _should_include(
    file_entry: dict,
    exclusions: list[str],
    excluded_slugs: set[str],
    force_include_slugs: set[str],
    project_slug: str | None,
) -> bool:
    if project_slug and project_slug in force_include_slugs:
        return True
    if project_slug and project_slug in excluded_slugs:
        return False
    if matches_any(exclusions, Path(file_entry.get("path", "")).name):
        return False
    if file_entry.get("env", {}).get("server") == "unsupported":
        return False
    return True


class ModrinthPackInstaller:
    """Installs a Modrinth modpack."""

    def __init__(
        self,
        source: ModrinthSource,
        server: ServerConfig,
        modpack: ModpackConfig,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.source = source
        self.server = server
        self.modpack = modpack
        self.session = session or build_session()
        self.show_progress = show_progress

    def install(self, output_dir: Path) -> dict:
        """Install the Modrinth modpack into *output_dir*.

        Returns the index dict (modrinth.index.json contents).
        """
        manifest = Manifest(output_dir)
        manifest.load()

        loader = (
            self.server.type
            if self.server.type not in (None, "vanilla", "paper", "purpur")
            else None
        )

        version = resolve_version(
            self.session,
            self.source.project,
            self.server.minecraft_version,
            loader,
            self.source.version_type,
            self.source.version,
        )
        log.info(
            "Resolved Modrinth version: %s (%s)",
            version.get("version_number"),
            version.get("id"),
        )
        pack_url = mrpack_url(version)
        log.debug("Downloading .mrpack: %s", pack_url)

        tmp_mrpack = output_dir / ".mc-helper-mrpack.tmp"
        output_dir.mkdir(parents=True, exist_ok=True)
        download_file(pack_url, tmp_mrpack, session=self.session, show_progress=self.show_progress)

        exclude = self.modpack.exclude_mods or []
        overrides_excl = self.modpack.overrides_exclusions or []

        try:
            with zipfile.ZipFile(tmp_mrpack) as zf:
                index = json.loads(zf.read("modrinth.index.json"))

                mr_filter = load_exclude_include("mr")
                pack_slug = self.source.project or ""
                pack_overrides = mr_filter.get("modpacks", {}).get(pack_slug, {})

                global_excluded_slugs: set[str] = set(
                    s.lower() for s in mr_filter.get("globalExcludes", [])
                )
                global_excluded_slugs.update(s.lower() for s in pack_overrides.get("excludes", []))

                global_force_include_slugs: set[str] = set(
                    s.lower() for s in mr_filter.get("globalForceIncludes", [])
                )
                global_force_include_slugs.update(
                    s.lower() for s in pack_overrides.get("forceIncludes", [])
                )

                all_files = index.get("files", [])
                raw_ids = [
                    pid
                    for f in all_files
                    for url in f.get("downloads", [])[:1]
                    if (pid := project_id_from_url(url)) is not None
                ]
                unique_ids = list(dict.fromkeys(raw_ids))
                slug_map = resolve_project_slugs(self.session, unique_ids)
                file_slug_map: dict[int, str | None] = {}
                for i, f in enumerate(all_files):
                    urls = f.get("downloads", [])
                    pid = project_id_from_url(urls[0]) if urls else None
                    file_slug_map[i] = slug_map.get(pid, "").lower() if pid else None

                files_to_install = [
                    (i, f)
                    for i, f in enumerate(all_files)
                    if _should_include(
                        f,
                        exclude,
                        global_excluded_slugs,
                        global_force_include_slugs,
                        file_slug_map.get(i),
                    )
                ]
                skipped = len(all_files) - len(files_to_install)
                log.info(
                    "Downloading %d modpack file(s) (%d skipped as client-only/excluded)...",
                    len(files_to_install),
                    skipped,
                )
                new_files: list[str] = []
                session = self.session

                def _download_entry(entry: dict) -> str:
                    rel_path = entry["path"]
                    dest = output_dir / rel_path
                    url = entry["downloads"][0]
                    hashes = entry.get("hashes", {})
                    sha512 = hashes.get("sha512")
                    sha1 = hashes.get("sha1") if not sha512 else None
                    download_file(
                        url,
                        dest,
                        session=session,
                        expected_sha512=sha512,
                        expected_sha1=sha1,
                        show_progress=False,
                    )
                    return rel_path

                with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                    futures = {pool.submit(_download_entry, f): f for _, f in files_to_install}
                    for fut in as_completed(futures):
                        new_files.append(fut.result())

                override_files = extract_zip_overrides(
                    zf, output_dir, ["overrides", "server-overrides"], overrides_excl
                )
                log.info("Extracted %d override file(s)", len(override_files))
                new_files.extend(override_files)

            manifest.cleanup_stale(new_files)
            manifest.files = new_files
            deps = index.get("dependencies", {})
            manifest.mc_version = deps.get("minecraft", self.server.minecraft_version)
            _loader_key_map = {
                "fabric-loader": "fabric",
                "quilt-loader": "quilt",
                "forge": "forge",
                "neoforge": "neoforge",
            }
            for dep_key, normalized in _loader_key_map.items():
                if dep_key in deps:
                    manifest.loader_type = normalized
                    manifest.loader_version = deps[dep_key]
                    break
            manifest.save()

        finally:
            tmp_mrpack.unlink(missing_ok=True)

        return index
