"""Tests for modpack/curseforge.py."""

import json
import zipfile
from io import BytesIO

import pytest
import responses as rsps_lib

from mc_helper.http_client import build_session
from mc_helper.modpack.curseforge import (
    CurseForgePackInstaller,
    _download_url_for_file,
    _is_server_mod,
    _passes_file_filter,
    _should_include,
)

_API = "https://api.curseforge.com"

# ── helpers ───────────────────────────────────────────────────────────────────


def _add_batch_slugs_mock(mod_data: list[dict] | None = None) -> None:
    """Register a mock for POST /v1/mods (batch slug resolution)."""
    rsps_lib.add(
        rsps_lib.POST,
        f"{_API}/v1/mods",
        json={"data": mod_data or []},
    )


def _make_mod_file(file_id: int = 1001, name: str = "testmod-1.0.jar") -> dict:
    return {
        "id": file_id,
        "fileName": name,
        "downloadUrl": f"https://edge.forgecdn.net/files/{file_id // 1000}/{file_id % 1000}/{name}",
        "gameVersions": ["1.21.1"],
        "isServerPack": False,
    }


def _make_modpack_zip(manifest: dict, overrides: dict[str, bytes] | None = None) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for path, data in (overrides or {}).items():
            zf.writestr(f"overrides/{path}", data)
    return buf.getvalue()


def _minimal_manifest(files: list | None = None) -> dict:
    return {
        "minecraft": {
            "version": "1.21.1",
            "modLoaders": [{"id": "forge-47.2.0", "primary": True}],
        },
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "name": "Test Pack",
        "version": "1.0.0",
        "overrides": "overrides",
        "files": files or [],
    }


# ── _download_url_for_file ────────────────────────────────────────────────────


def test_download_url_uses_api_url():
    f = {"id": 4001, "fileName": "jei.jar", "downloadUrl": "https://example.com/jei.jar"}
    assert _download_url_for_file(f) == "https://example.com/jei.jar"


def test_download_url_fallback_when_null():
    f = {"id": 4001001, "fileName": "jei.jar", "downloadUrl": None}
    url = _download_url_for_file(f)
    assert "4001" in url
    assert "jei.jar" in url


# ── _should_include ───────────────────────────────────────────────────────────


def test_should_include_required():
    assert _should_include({"projectID": 123, "required": True}, [], []) is True


def test_should_include_not_required():
    assert _should_include({"projectID": 123, "required": False}, [], []) is False


def test_should_include_excluded():
    assert _should_include({"projectID": 123, "required": True}, ["123"], []) is False


def test_should_include_force_include_overrides_exclude():
    assert _should_include({"projectID": 123, "required": False}, ["123"], ["123"]) is True


# ── resolve_modpack (via install flow) ────────────────────────────────────────


@rsps_lib.activate
def test_resolve_by_slug(tmp_path):
    mod_id = 555
    file_id = 1001
    mod_file = _make_mod_file(file_id)
    pack_zip = _make_modpack_zip(_minimal_manifest())

    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/search",
        json={"data": [{"id": mod_id, "slug": "test-pack"}]},
    )
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/{mod_id}/files",
        json={"data": [mod_file]},
    )
    rsps_lib.add(
        rsps_lib.GET,
        mod_file["downloadUrl"],
        body=pack_zip,
    )
    _add_batch_slugs_mock()  # no files in manifest → empty batch call

    session = build_session()
    result = CurseForgePackInstaller(
        "fake-key", slug="test-pack", session=session, show_progress=False
    ).install(tmp_path)
    assert result["name"] == "Test Pack"


@rsps_lib.activate
def test_resolve_by_mod_id(tmp_path):
    mod_id = 555
    file_id = 1001
    mod_file = _make_mod_file(file_id)
    pack_zip = _make_modpack_zip(_minimal_manifest())

    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/{mod_id}/files",
        json={"data": [mod_file]},
    )
    rsps_lib.add(rsps_lib.GET, mod_file["downloadUrl"], body=pack_zip)
    _add_batch_slugs_mock()

    session = build_session()
    result = CurseForgePackInstaller(
        "fake-key", mod_id=mod_id, session=session, show_progress=False
    ).install(tmp_path)
    assert result["name"] == "Test Pack"


# ── full install workflow ─────────────────────────────────────────────────────


@rsps_lib.activate
def test_install_downloads_mods(tmp_path):
    mod_id = 555
    pack_file_id = 2000
    mod_file_id = 3001
    dep_mod_file = _make_mod_file(mod_file_id, "jei-1.0.jar")

    manifest_data = _minimal_manifest(
        files=[{"projectID": 100, "fileID": mod_file_id, "required": True}]
    )
    pack_file = _make_mod_file(pack_file_id, "testpack-1.0.zip")
    pack_file["downloadUrl"] = "https://edge.forgecdn.net/files/2/0/testpack-1.0.zip"
    pack_zip = _make_modpack_zip(manifest_data)

    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/{mod_id}/files",
        json={"data": [pack_file]},
    )
    rsps_lib.add(rsps_lib.GET, pack_file["downloadUrl"], body=pack_zip)
    _add_batch_slugs_mock([{"id": 100, "slug": "jei"}])
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/100/files/{mod_file_id}",
        json={"data": dep_mod_file},
    )
    rsps_lib.add(rsps_lib.GET, dep_mod_file["downloadUrl"], body=b"fake-jar")

    session = build_session()
    CurseForgePackInstaller(
        "fake-key", mod_id=mod_id, session=session, show_progress=False
    ).install(tmp_path)

    assert (tmp_path / "mods" / "jei-1.0.jar").read_bytes() == b"fake-jar"


@rsps_lib.activate
def test_install_extracts_overrides(tmp_path):
    mod_id = 555
    file_id = 2000
    pack_file = _make_mod_file(file_id, "testpack.zip")
    pack_file["downloadUrl"] = "https://edge.forgecdn.net/files/2/0/testpack.zip"
    pack_zip = _make_modpack_zip(
        _minimal_manifest(),
        overrides={"config/server.cfg": b"key=value"},
    )

    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/{mod_id}/files",
        json={"data": [pack_file]},
    )
    rsps_lib.add(rsps_lib.GET, pack_file["downloadUrl"], body=pack_zip)
    _add_batch_slugs_mock()

    session = build_session()
    CurseForgePackInstaller(
        "fake-key", mod_id=mod_id, session=session, show_progress=False
    ).install(tmp_path)

    assert (tmp_path / "config" / "server.cfg").read_bytes() == b"key=value"


@rsps_lib.activate
def test_install_writes_manifest(tmp_path):
    mod_id = 555
    file_id = 2000
    pack_file = _make_mod_file(file_id, "testpack.zip")
    pack_file["downloadUrl"] = "https://edge.forgecdn.net/files/2/0/testpack.zip"
    pack_zip = _make_modpack_zip(_minimal_manifest())

    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/{mod_id}/files",
        json={"data": [pack_file]},
    )
    rsps_lib.add(rsps_lib.GET, pack_file["downloadUrl"], body=pack_zip)
    _add_batch_slugs_mock()

    session = build_session()
    CurseForgePackInstaller(
        "fake-key", mod_id=mod_id, session=session, show_progress=False
    ).install(tmp_path)

    from mc_helper.manifest import Manifest

    m = Manifest(tmp_path)
    m.load()
    assert m.mc_version == "1.21.1"
    assert m.loader_type == "forge"
    assert m.loader_version == "47.2.0"


@rsps_lib.activate
def test_install_no_slug_no_mod_id_raises(tmp_path):
    with pytest.raises(ValueError, match="slug or mod_id"):
        CurseForgePackInstaller("fake-key", show_progress=False).install(tmp_path)


# ── hash verification for mod downloads ──────────────────────────────────────


@rsps_lib.activate
def test_install_verifies_mod_hash(tmp_path):
    """Mod files with hashes in the API response should be SHA-1 verified."""
    mod_id = 555
    pack_file_id = 2000
    mod_file_id = 3001

    dep_mod_file = {
        "id": mod_file_id,
        "fileName": "jei-1.0.jar",
        "downloadUrl": "https://edge.forgecdn.net/files/3/1/jei-1.0.jar",
        "gameVersions": ["1.21.1"],
        "hashes": [{"algo": 1, "value": "aabbccdd" * 5}],  # wrong SHA-1
    }

    manifest_data = _minimal_manifest(
        files=[{"projectID": 100, "fileID": mod_file_id, "required": True}]
    )
    pack_file = _make_mod_file(pack_file_id, "testpack-1.0.zip")
    pack_file["downloadUrl"] = "https://edge.forgecdn.net/files/2/0/testpack-1.0.zip"
    pack_zip = _make_modpack_zip(manifest_data)

    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/{mod_id}/files",
        json={"data": [pack_file]},
    )
    rsps_lib.add(rsps_lib.GET, pack_file["downloadUrl"], body=pack_zip)
    _add_batch_slugs_mock([{"id": 100, "slug": "jei"}])
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/100/files/{mod_file_id}",
        json={"data": dep_mod_file},
    )
    rsps_lib.add(
        rsps_lib.GET,
        dep_mod_file["downloadUrl"],
        body=b"fake-jar-content",  # hash of this won't match "aabbccdd" * 5
    )

    session = build_session()
    with pytest.raises(ValueError, match="SHA-1 mismatch"):
        CurseForgePackInstaller(
            "fake-key", mod_id=mod_id, session=session, show_progress=False
        ).install(tmp_path)


@rsps_lib.activate
def test_install_skips_hash_when_none(tmp_path):
    """Mod files without hashes in the API response should download without error."""
    mod_id = 555
    pack_file_id = 2000
    mod_file_id = 3001

    dep_mod_file = {
        "id": mod_file_id,
        "fileName": "jei-1.0.jar",
        "downloadUrl": "https://edge.forgecdn.net/files/3/1/jei-1.0.jar",
        "gameVersions": ["1.21.1"],
        "hashes": [],  # no hashes provided
    }

    manifest_data = _minimal_manifest(
        files=[{"projectID": 100, "fileID": mod_file_id, "required": True}]
    )
    pack_file = _make_mod_file(pack_file_id, "testpack-1.0.zip")
    pack_file["downloadUrl"] = "https://edge.forgecdn.net/files/2/0/testpack-1.0.zip"
    pack_zip = _make_modpack_zip(manifest_data)

    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/{mod_id}/files",
        json={"data": [pack_file]},
    )
    rsps_lib.add(rsps_lib.GET, pack_file["downloadUrl"], body=pack_zip)
    _add_batch_slugs_mock([{"id": 100, "slug": "jei"}])
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/100/files/{mod_file_id}",
        json={"data": dep_mod_file},
    )
    rsps_lib.add(rsps_lib.GET, dep_mod_file["downloadUrl"], body=b"fake-jar-content")

    session = build_session()
    CurseForgePackInstaller(
        "fake-key", mod_id=mod_id, session=session, show_progress=False
    ).install(tmp_path)
    assert (tmp_path / "mods" / "jei-1.0.jar").exists()


# ── _is_server_mod ────────────────────────────────────────────────────────────


def test_is_server_mod_server_tag():
    assert _is_server_mod({"gameVersions": ["1.21.1", "Server"]}) is True


def test_is_server_mod_client_only():
    assert _is_server_mod({"gameVersions": ["1.21.1", "Client"]}) is False


def test_is_server_mod_no_side_tag():
    # No Client or Server tag → assume server-safe
    assert _is_server_mod({"gameVersions": ["1.21.1", "Forge"]}) is True


def test_is_server_mod_empty():
    assert _is_server_mod({}) is True


# ── _passes_file_filter ───────────────────────────────────────────────────────


def test_passes_file_filter_normal():
    f = {"fileName": "jei-1.0.jar", "gameVersions": ["1.21.1"]}
    assert _passes_file_filter(f, [], [], set(), set(), "jei") is True


def test_passes_file_filter_client_only_excluded():
    f = {"fileName": "jei-1.0.jar", "gameVersions": ["Client"]}
    assert _passes_file_filter(f, [], [], set(), set(), "jei") is False


def test_passes_file_filter_global_slug_excluded():
    f = {"fileName": "jei-1.0.jar", "gameVersions": ["1.21.1"]}
    assert _passes_file_filter(f, [], [], {"jei"}, set(), "jei") is False


def test_passes_file_filter_force_include_overrides_slug_exclude():
    f = {"fileName": "jei-1.0.jar", "gameVersions": ["Client"]}
    # Force-include by slug wins even over client-only
    assert _passes_file_filter(f, [], [], {"jei"}, {"jei"}, "jei") is True


def test_passes_file_filter_filename_exclude():
    f = {"fileName": "jei-1.0.jar", "gameVersions": ["1.21.1"]}
    assert _passes_file_filter(f, ["jei-*"], [], set(), set(), None) is False


# ── G3: isServerPack filter ───────────────────────────────────────────────────


@rsps_lib.activate
def test_install_skips_server_pack_files(tmp_path):
    """isServerPack=True files must be skipped when selecting the pack file."""
    mod_id = 555
    server_pack = _make_mod_file(1000, "testpack-server.zip")
    server_pack["isServerPack"] = True
    client_pack = _make_mod_file(1001, "testpack-client.zip")
    client_pack["isServerPack"] = False
    client_pack["downloadUrl"] = "https://edge.forgecdn.net/files/1/1/testpack-client.zip"
    pack_zip = _make_modpack_zip(_minimal_manifest())

    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/{mod_id}/files",
        json={"data": [server_pack, client_pack]},
    )
    rsps_lib.add(rsps_lib.GET, client_pack["downloadUrl"], body=pack_zip)
    _add_batch_slugs_mock()

    session = build_session()
    result = CurseForgePackInstaller(
        "fake-key", mod_id=mod_id, session=session, show_progress=False
    ).install(tmp_path)
    assert result["name"] == "Test Pack"  # successfully used the client pack


# ── G1: global slug exclusion ─────────────────────────────────────────────────


@rsps_lib.activate
def test_install_global_slug_excludes_mod(tmp_path, tmp_path_factory, monkeypatch):
    """Mods whose slug appears in globalExcludes must be skipped."""
    mod_id = 555
    pack_file_id = 2000
    mod_file_id = 3001

    dep_mod_file = _make_mod_file(mod_file_id, "jei-1.0.jar")
    manifest_data = _minimal_manifest(
        files=[{"projectID": 100, "fileID": mod_file_id, "required": True}]
    )
    pack_file = _make_mod_file(pack_file_id, "testpack-1.0.zip")
    pack_file["downloadUrl"] = "https://edge.forgecdn.net/files/2/0/testpack-1.0.zip"
    pack_zip = _make_modpack_zip(manifest_data)

    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/{mod_id}/files",
        json={"data": [pack_file]},
    )
    rsps_lib.add(rsps_lib.GET, pack_file["downloadUrl"], body=pack_zip)
    # Resolve slug for project 100 → "jei" (which is in globalExcludes of the real filter file)
    _add_batch_slugs_mock([{"id": 100, "slug": "jei"}])
    # dep_mod_file API call and download should NOT be made if slug is excluded
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/100/files/{mod_file_id}",
        json={"data": dep_mod_file},
    )
    rsps_lib.add(rsps_lib.GET, dep_mod_file["downloadUrl"], body=b"fake-jar")

    # Patch the filter to have "jei" as a globalExclude
    import mc_helper.modpack.curseforge as cf_mod

    monkeypatch.setattr(
        cf_mod, "_load_cf_filter", lambda: {"globalExcludes": ["jei"], "modpacks": {}}
    )

    session = build_session()
    CurseForgePackInstaller(
        "fake-key", mod_id=mod_id, session=session, show_progress=False
    ).install(tmp_path)

    # jei.jar must NOT have been downloaded
    assert not (tmp_path / "mods" / "jei-1.0.jar").exists()
