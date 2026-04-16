"""Modrinth modpack installer.

Reference: mc-image-helper/.../modrinth/ModrinthPackInstaller.java
Reference: mc-image-helper/.../modrinth/ModrinthApiPackFetcher.java
Reference: mc-image-helper/.../modrinth/model/ModpackIndex.java
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

import fnmatch
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file, get_json
from mc_helper.manifest import Manifest
from mc_helper.utils import extract_zip_overrides

_API_BASE = "https://api.modrinth.com/v2"
_MAX_WORKERS = 10
_DATA_DIR = Path(__file__).parent.parent / "data"


def _load_mr_filter() -> dict:
    """Load the bundled Modrinth exclude/include filter file."""
    path = _DATA_DIR / "modrinth-exclude-include.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"globalExcludes": [], "globalForceIncludes": [], "modpacks": {}}


def _project_id_from_url(url: str) -> str | None:
    """Extract the Modrinth project ID from a CDN URL.

    CDN URLs follow the pattern:
    ``https://cdn.modrinth.com/data/{project_id}/versions/{version_id}/{filename}``
    """
    parts = url.split("/")
    try:
        idx = parts.index("data")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return None


def _resolve_project_slugs(session: requests.Session, project_ids: list[str]) -> dict[str, str]:
    """Batch-resolve Modrinth project IDs to slugs.

    Returns ``{project_id: slug}``.
    """
    if not project_ids:
        return {}
    ids_json = json.dumps(project_ids)
    url = f"{_API_BASE}/projects?ids={ids_json}"
    data = get_json(session, url)
    return {item["id"]: item.get("slug", "") for item in data}  # type: ignore[union-attr]


def resolve_version(
    session: requests.Session,
    project: str,
    minecraft_version: str | None,
    loader: str | None,
    version_type: str = "release",
    requested_version: str = "LATEST",
) -> dict:
    """Return the best matching version object for the project."""
    if requested_version and requested_version.upper() != "LATEST":
        # Specific version number or ID — try direct lookup first
        versions = get_json(session, f"{_API_BASE}/project/{project}/version")
        for v in versions:
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

    # Prefer requested version_type, fall back to whatever is available
    preference = ["release", "beta", "alpha"]
    if version_type in preference:
        preference = [version_type] + [t for t in preference if t != version_type]

    for vtype in preference:
        for v in versions:
            if v.get("version_type") == vtype:
                return v

    return versions[0]


def _mrpack_url(version: dict) -> str:
    """Pick the primary .mrpack file from a version object."""
    for f in version.get("files", []):
        if f.get("primary"):
            return f["url"]
    # Fall back to first file
    return version["files"][0]["url"]


def _should_include(
    file_entry: dict,
    exclusions: list[str],
    excluded_slugs: set[str] | None = None,
    force_include_slugs: set[str] | None = None,
    project_slug: str | None = None,
) -> bool:
    """Return True if the modpack file should be installed server-side.

    Checks (in order):
      1. Global slug force-include → always include
      2. Global slug exclude → skip
      3. User filename-pattern exclude → skip
      4. Client-only detection via env.server == "unsupported" → skip
    """
    if force_include_slugs and project_slug and project_slug in force_include_slugs:
        return True
    if excluded_slugs and project_slug and project_slug in excluded_slugs:
        return False
    path = file_entry.get("path", "")
    for pattern in exclusions:
        if fnmatch.fnmatch(Path(path).name, pattern):
            return False
    env = file_entry.get("env", {})
    if env.get("server") == "unsupported":
        return False
    return True


class ModrinthPackInstaller:
    """Installs a Modrinth modpack."""

    def __init__(
        self,
        project: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
        version_type: str = "release",
        requested_version: str = "LATEST",
        exclude_mods: list[str] | None = None,
        overrides_exclusions: list[str] | None = None,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.project = project
        self.minecraft_version = minecraft_version
        self.loader = loader
        self.version_type = version_type
        self.requested_version = requested_version
        self.exclude_mods = exclude_mods or []
        self.overrides_exclusions = overrides_exclusions or []
        self.session = session or build_session()
        self.show_progress = show_progress

    def install(self, output_dir: Path) -> dict:
        """Install the Modrinth modpack into *output_dir*.

        Returns the index dict (modrinth.index.json contents).
        """
        manifest = Manifest(output_dir)
        manifest.load()

        # 1. Resolve version
        version = resolve_version(
            self.session,
            self.project,
            self.minecraft_version,
            self.loader,
            self.version_type,
            self.requested_version,
        )
        mrpack_url = _mrpack_url(version)

        # 2. Download .mrpack to a temp file
        tmp_mrpack = output_dir / ".mc-helper-mrpack.tmp"
        output_dir.mkdir(parents=True, exist_ok=True)
        download_file(
            mrpack_url, tmp_mrpack, session=self.session, show_progress=self.show_progress
        )

        try:
            with zipfile.ZipFile(tmp_mrpack) as zf:
                # 3. Parse modrinth.index.json
                index = json.loads(zf.read("modrinth.index.json"))

                # G1: load global exclude/include filter and batch-resolve slugs
                mr_filter = _load_mr_filter()
                pack_slug = self.project or ""
                pack_overrides = mr_filter.get("modpacks", {}).get(pack_slug, {})

                global_excluded_slugs: set[str] = set(
                    s.lower() for s in mr_filter.get("globalExcludes", [])
                )
                global_excluded_slugs.update(
                    s.lower() for s in pack_overrides.get("excludes", [])
                )

                global_force_include_slugs: set[str] = set(
                    s.lower() for s in mr_filter.get("globalForceIncludes", [])
                )
                global_force_include_slugs.update(
                    s.lower() for s in pack_overrides.get("forceIncludes", [])
                )

                # Batch-resolve project IDs to slugs from CDN URLs
                all_files = index.get("files", [])
                raw_ids = [
                    pid
                    for f in all_files
                    for url in f.get("downloads", [])[:1]
                    if (pid := _project_id_from_url(url)) is not None
                ]
                unique_ids = list(dict.fromkeys(raw_ids))  # deduplicate, preserve order
                slug_map = _resolve_project_slugs(self.session, unique_ids)
                # Build a per-file lookup: url → project_slug
                file_slug_map: dict[int, str | None] = {}
                for i, f in enumerate(all_files):
                    urls = f.get("downloads", [])
                    pid = _project_id_from_url(urls[0]) if urls else None
                    file_slug_map[i] = slug_map.get(pid, "").lower() if pid else None

                # 4+5. Download modpack files (parallel)
                files_to_install = [
                    (i, f)
                    for i, f in enumerate(all_files)
                    if _should_include(
                        f,
                        self.exclude_mods,
                        global_excluded_slugs,
                        global_force_include_slugs,
                        file_slug_map.get(i),
                    )
                ]
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

                # 6. Extract overrides
                override_files = extract_zip_overrides(
                    zf, output_dir, ["overrides", "server-overrides"], self.overrides_exclusions
                )
                new_files.extend(override_files)

            # 8. Cleanup stale + save manifest
            manifest.cleanup_stale(output_dir, new_files)
            manifest.files = new_files
            deps = index.get("dependencies", {})
            manifest.mc_version = deps.get("minecraft", self.minecraft_version)
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
