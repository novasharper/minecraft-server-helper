"""Tests for modpack/curseforge.py."""

import json
import zipfile
from io import BytesIO

import pytest
import responses as rsps_lib

from mc_helper.http_client import build_session
from mc_helper.modpack.curseforge import (
    _download_url_for_file,
    _should_include,
    install,
)

_API = "https://api.curseforge.com"

# ── helpers ───────────────────────────────────────────────────────────────────


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

    session = build_session()
    result = install("fake-key", tmp_path, slug="test-pack", session=session, show_progress=False)
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

    session = build_session()
    result = install("fake-key", tmp_path, mod_id=mod_id, session=session, show_progress=False)
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
        rsps_lib.GET, f"{_API}/v1/mods/{mod_id}/files",
        json={"data": [pack_file]},
    )
    rsps_lib.add(rsps_lib.GET, pack_file["downloadUrl"], body=pack_zip)
    rsps_lib.add(
        rsps_lib.GET, f"{_API}/v1/mods/100/files/{mod_file_id}",
        json={"data": dep_mod_file},
    )
    rsps_lib.add(rsps_lib.GET, dep_mod_file["downloadUrl"], body=b"fake-jar")

    session = build_session()
    install("fake-key", tmp_path, mod_id=mod_id, session=session, show_progress=False)

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
        rsps_lib.GET, f"{_API}/v1/mods/{mod_id}/files",
        json={"data": [pack_file]},
    )
    rsps_lib.add(rsps_lib.GET, pack_file["downloadUrl"], body=pack_zip)

    session = build_session()
    install("fake-key", tmp_path, mod_id=mod_id, session=session, show_progress=False)

    assert (tmp_path / "config" / "server.cfg").read_bytes() == b"key=value"


@rsps_lib.activate
def test_install_writes_manifest(tmp_path):
    mod_id = 555
    file_id = 2000
    pack_file = _make_mod_file(file_id, "testpack.zip")
    pack_file["downloadUrl"] = "https://edge.forgecdn.net/files/2/0/testpack.zip"
    pack_zip = _make_modpack_zip(_minimal_manifest())

    rsps_lib.add(
        rsps_lib.GET, f"{_API}/v1/mods/{mod_id}/files",
        json={"data": [pack_file]},
    )
    rsps_lib.add(rsps_lib.GET, pack_file["downloadUrl"], body=pack_zip)

    session = build_session()
    install("fake-key", tmp_path, mod_id=mod_id, session=session, show_progress=False)

    from mc_helper.manifest import Manifest
    m = Manifest(tmp_path)
    m.load()
    assert m.mc_version == "1.21.1"
    assert m.loader_type == "forge"
    assert m.loader_version == "47.2.0"


@rsps_lib.activate
def test_install_no_slug_no_mod_id_raises(tmp_path):
    with pytest.raises(ValueError, match="slug or mod_id"):
        install("fake-key", tmp_path, show_progress=False)
