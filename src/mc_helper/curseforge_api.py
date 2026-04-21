"""Shared CurseForge API client used by modpack and mod installers."""

import requests

from mc_helper.http_client import build_session, get_json

_API_BASE = "https://api.curseforge.com"
_MINECRAFT_GAME_ID = "432"
_LOADER_TYPE_MAP = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}


class CurseForgeClient:
    """Thin wrapper around the CurseForge v1 API."""

    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        if session is None:
            self.session = build_session(extra_headers={"X-Api-Key": api_key})
        else:
            self.session = session
            self.session.headers["X-Api-Key"] = api_key

    def search_by_slug(self, slug: str, *, class_id: int) -> dict | None:
        """Search for a mod/pack by slug within *class_id*. Returns the first hit or None."""
        resp = get_json(
            self.session,
            f"{_API_BASE}/v1/mods/search"
            f"?gameId={_MINECRAFT_GAME_ID}&slug={slug}&classId={class_id}",
        )
        data = resp.get("data", [])  # type: ignore[union-attr]
        return data[0] if data else None

    def get_mod_file(self, mod_id: int, file_id: int) -> dict:
        """Return the file object for *mod_id*/*file_id*."""
        resp = get_json(self.session, f"{_API_BASE}/v1/mods/{mod_id}/files/{file_id}")
        return resp["data"]  # type: ignore[index]

    def get_mod_files(self, mod_id: int) -> list[dict]:
        """Return all file objects for *mod_id*."""
        resp = get_json(self.session, f"{_API_BASE}/v1/mods/{mod_id}/files")
        return resp["data"]  # type: ignore[index]

    def get_latest_file(
        self,
        mod_id: int,
        minecraft_version: str | None = None,
        loader: str | None = None,
        loader_type_map: dict[str, int] | None = None,
    ) -> dict:
        """Return the newest file for *mod_id* matching the given filters."""
        effective_map = loader_type_map if loader_type_map is not None else _LOADER_TYPE_MAP
        params: list[str] = []
        if minecraft_version:
            params.append(f"gameVersion={minecraft_version}")
        if loader:
            loader_type = effective_map.get(loader.lower())
            if loader_type is not None:
                params.append(f"modLoaderType={loader_type}")
        url = f"{_API_BASE}/v1/mods/{mod_id}/files"
        if params:
            url += "?" + "&".join(params)
        resp = get_json(self.session, url)
        files = resp["data"]  # type: ignore[index]
        if not files:
            raise ValueError(f"No files found for CurseForge mod {mod_id}")
        return files[0]

    def resolve_slugs(self, project_ids: list[int]) -> dict[int, str]:
        """Batch-resolve project IDs → slugs via POST /v1/mods."""
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

    @staticmethod
    def download_url_for(file_obj: dict) -> str:
        """Return the download URL, constructing a fallback if the API returns null."""
        url = file_obj.get("downloadUrl")
        if url:
            return url
        fid = file_obj["id"]
        name = file_obj["fileName"]
        return f"https://edge.forgecdn.net/files/{fid // 1000}/{fid % 1000}/{name}"

    @staticmethod
    def sha1_of(file_obj: dict) -> str | None:
        """Extract SHA-1 from the hashes array (algo==1)."""
        hashes = file_obj.get("hashes", [])
        return next((h["value"] for h in hashes if h.get("algo") == 1), None)
