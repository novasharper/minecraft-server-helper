"""Tests for modpack/ftb.py."""

import pytest
import responses as rsps_lib

from mc_helper.http_client import build_session
from mc_helper.manifest import Manifest
from mc_helper.modpack.ftb import FTBPackInstaller, _ftb_get, _should_include

_API = "https://api.feed-the-beast.com/v1/modpacks"
_PACK_ID = 7

# ── helpers ───────────────────────────────────────────────────────────────────


def _pack_response(versions: list[dict]) -> dict:
    return {"status": "success", "id": _PACK_ID, "name": "Test Pack", "versions": versions}


def _version_entry(vid: int, vtype: str = "release") -> dict:
    return {"id": vid, "name": f"v{vid}", "type": vtype, "private": False}


def _version_detail(
    vid: int, files: list[dict] | None = None, targets: list[dict] | None = None
) -> dict:
    return {
        "status": "success",
        "id": vid,
        "name": f"v{vid}",
        "type": "release",
        "files": files or [],
        "targets": targets
        or [
            {"type": "game", "name": "minecraft", "version": "1.21.1"},
            {"type": "modloader", "name": "neoforge", "version": "21.1.50"},
        ],
    }


def _file_entry(
    name: str = "mod.jar",
    path: str = "mods",
    url: str = "https://cdn.ftb.cloud/mod.jar",
    sha1: str = "",
    clientonly: bool = False,
    mirrors: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "path": path,
        "url": url,
        "sha1": sha1,
        "clientonly": clientonly,
        "mirrors": mirrors or [],
    }


# ── _should_include ───────────────────────────────────────────────────────────


def test_should_include_clientonly_excluded():
    assert _should_include(_file_entry(clientonly=True), []) is False


def test_should_include_normal_file():
    assert _should_include(_file_entry(), []) is True


def test_should_include_exclude_pattern():
    assert _should_include(_file_entry(name="jei-1.21.jar"), ["jei-*"]) is False


def test_should_include_no_match_pattern():
    assert _should_include(_file_entry(name="sodium.jar"), ["jei-*"]) is True


# ── _ftb_get ──────────────────────────────────────────────────────────────────


@rsps_lib.activate
def test_ftb_get_success():
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response([]))
    session = build_session()
    data = _ftb_get(f"{_API}/modpack/{_PACK_ID}", "public", session)
    assert data["status"] == "success"


@rsps_lib.activate
def test_ftb_get_no_auth_for_public():
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response([]))
    session = build_session()
    _ftb_get(f"{_API}/modpack/{_PACK_ID}", "public", session)
    assert "Authorization" not in rsps_lib.calls[0].request.headers


@rsps_lib.activate
def test_ftb_get_sends_auth_for_custom_key():
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response([]))
    session = build_session()
    _ftb_get(f"{_API}/modpack/{_PACK_ID}", "my-secret-key", session)
    assert rsps_lib.calls[0].request.headers.get("Authorization") == "Bearer my-secret-key"


@rsps_lib.activate
def test_ftb_get_raises_on_error_status():
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/modpack/999",
        json={"status": "error", "message": "Pack not found"},
    )
    session = build_session()
    with pytest.raises(ValueError, match="Pack not found"):
        _ftb_get(f"{_API}/modpack/999", "public", session)


# ── FTBPackInstaller._resolve_version_id ──────────────────────────────────────


@rsps_lib.activate
def test_resolve_latest_release():
    versions = [
        _version_entry(300, "release"),
        _version_entry(200, "release"),
        _version_entry(100, "beta"),
    ]
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response(versions))
    installer = FTBPackInstaller(pack_id=_PACK_ID, session=build_session())
    assert installer._resolve_version_id() == 300


@rsps_lib.activate
def test_resolve_by_explicit_version_id():
    # No pack API call should be made when version_id is given
    installer = FTBPackInstaller(pack_id=_PACK_ID, version_id=42, session=build_session())
    assert installer._resolve_version_id() == 42
    assert len(rsps_lib.calls) == 0


@rsps_lib.activate
def test_resolve_beta_when_no_release():
    versions = [_version_entry(100, "beta"), _version_entry(50, "alpha")]
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response(versions))
    installer = FTBPackInstaller(pack_id=_PACK_ID, version_type="beta", session=build_session())
    assert installer._resolve_version_id() == 100


@rsps_lib.activate
def test_resolve_falls_back_to_first_when_no_type_match():
    versions = [_version_entry(200, "beta"), _version_entry(100, "alpha")]
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response(versions))
    installer = FTBPackInstaller(pack_id=_PACK_ID, version_type="release", session=build_session())
    # Falls back to first (highest id) when no release found
    assert installer._resolve_version_id() == 200


# ── FTBPackInstaller.install ──────────────────────────────────────────────────


@rsps_lib.activate
def test_install_downloads_files(tmp_path):
    mod_bytes = b"fake-mod-content"
    files = [_file_entry(name="mymod.jar", url="https://cdn.ftb.cloud/mymod.jar")]
    rsps_lib.add(
        rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response([_version_entry(1)])
    )
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}/1", json=_version_detail(1, files=files))
    rsps_lib.add(rsps_lib.GET, "https://cdn.ftb.cloud/mymod.jar", body=mod_bytes)

    FTBPackInstaller(pack_id=_PACK_ID, session=build_session()).install(tmp_path)

    assert (tmp_path / "mods" / "mymod.jar").read_bytes() == mod_bytes


@rsps_lib.activate
def test_install_skips_client_only_files(tmp_path):
    files = [
        _file_entry(name="server.jar", url="https://cdn.ftb.cloud/server.jar"),
        _file_entry(name="client.jar", url="https://cdn.ftb.cloud/client.jar", clientonly=True),
    ]
    rsps_lib.add(
        rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response([_version_entry(1)])
    )
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}/1", json=_version_detail(1, files=files))
    rsps_lib.add(rsps_lib.GET, "https://cdn.ftb.cloud/server.jar", body=b"server")
    # client.jar must NOT be requested

    FTBPackInstaller(pack_id=_PACK_ID, session=build_session()).install(tmp_path)

    assert (tmp_path / "mods" / "server.jar").exists()
    assert not (tmp_path / "mods" / "client.jar").exists()


@rsps_lib.activate
def test_install_applies_exclude_mods_pattern(tmp_path):
    files = [
        _file_entry(name="jei-1.21.jar", url="https://cdn.ftb.cloud/jei.jar"),
        _file_entry(name="sodium.jar", url="https://cdn.ftb.cloud/sodium.jar"),
    ]
    rsps_lib.add(
        rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response([_version_entry(1)])
    )
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}/1", json=_version_detail(1, files=files))
    rsps_lib.add(rsps_lib.GET, "https://cdn.ftb.cloud/sodium.jar", body=b"sodium")
    # jei.jar must NOT be requested

    FTBPackInstaller(pack_id=_PACK_ID, exclude_mods=["jei-*"], session=build_session()).install(
        tmp_path
    )

    assert (tmp_path / "mods" / "sodium.jar").exists()
    assert not (tmp_path / "mods" / "jei-1.21.jar").exists()


@rsps_lib.activate
def test_install_saves_manifest(tmp_path):
    targets = [
        {"type": "game", "name": "minecraft", "version": "1.21.1"},
        {"type": "modloader", "name": "neoforge", "version": "21.1.50"},
    ]
    rsps_lib.add(
        rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response([_version_entry(1)])
    )
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/modpack/{_PACK_ID}/1",
        json=_version_detail(1, files=[], targets=targets),
    )

    FTBPackInstaller(pack_id=_PACK_ID, session=build_session()).install(tmp_path)

    m = Manifest(tmp_path)
    m.load()
    assert m.mc_version == "1.21.1"
    assert m.loader_type == "neoforge"
    assert m.loader_version == "21.1.50"


@rsps_lib.activate
def test_install_saves_file_list_in_manifest(tmp_path):
    files = [_file_entry(name="mod.jar", url="https://cdn.ftb.cloud/mod.jar")]
    rsps_lib.add(
        rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response([_version_entry(1)])
    )
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}/1", json=_version_detail(1, files=files))
    rsps_lib.add(rsps_lib.GET, "https://cdn.ftb.cloud/mod.jar", body=b"data")

    FTBPackInstaller(pack_id=_PACK_ID, session=build_session()).install(tmp_path)

    m = Manifest(tmp_path)
    m.load()
    assert "mods/mod.jar" in m.files


@rsps_lib.activate
def test_install_deletes_stale_files(tmp_path):
    # Pre-existing file tracked by old manifest
    stale = tmp_path / "mods" / "old.jar"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"old")
    m = Manifest(tmp_path)
    m.files = ["mods/old.jar"]
    m.mc_version = "1.20.1"
    m.loader_type = "neoforge"
    m.loader_version = "20.1.0"
    m.save()

    # New version has a different file
    files = [_file_entry(name="new.jar", url="https://cdn.ftb.cloud/new.jar")]
    rsps_lib.add(
        rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response([_version_entry(2)])
    )
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}/2", json=_version_detail(2, files=files))
    rsps_lib.add(rsps_lib.GET, "https://cdn.ftb.cloud/new.jar", body=b"new")

    FTBPackInstaller(pack_id=_PACK_ID, session=build_session()).install(tmp_path)

    assert not stale.exists()
    assert (tmp_path / "mods" / "new.jar").exists()


@rsps_lib.activate
def test_install_uses_mirror_on_primary_failure(tmp_path):
    mirror_url = "https://mirror.ftb.cloud/mod.jar"
    files = [_file_entry(name="mod.jar", url="https://cdn.ftb.cloud/mod.jar", mirrors=[mirror_url])]
    rsps_lib.add(
        rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response([_version_entry(1)])
    )
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}/1", json=_version_detail(1, files=files))
    # Primary returns 404; mirror succeeds
    rsps_lib.add(rsps_lib.GET, "https://cdn.ftb.cloud/mod.jar", status=404)
    rsps_lib.add(rsps_lib.GET, mirror_url, body=b"mod-data")

    FTBPackInstaller(pack_id=_PACK_ID, session=build_session()).install(tmp_path)

    assert (tmp_path / "mods" / "mod.jar").read_bytes() == b"mod-data"


@rsps_lib.activate
def test_install_sha1_verified(tmp_path):
    import hashlib

    mod_bytes = b"verified-content"
    sha1 = hashlib.sha1(mod_bytes).hexdigest()
    files = [_file_entry(name="mod.jar", url="https://cdn.ftb.cloud/mod.jar", sha1=sha1)]
    rsps_lib.add(
        rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response([_version_entry(1)])
    )
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}/1", json=_version_detail(1, files=files))
    rsps_lib.add(rsps_lib.GET, "https://cdn.ftb.cloud/mod.jar", body=mod_bytes)

    FTBPackInstaller(pack_id=_PACK_ID, session=build_session()).install(tmp_path)

    assert (tmp_path / "mods" / "mod.jar").read_bytes() == mod_bytes


@rsps_lib.activate
def test_install_files_nested_path(tmp_path):
    """Files with a non-'mods' path are placed in the correct subdirectory."""
    files = [_file_entry(name="server.cfg", path="config", url="https://cdn.ftb.cloud/server.cfg")]
    rsps_lib.add(
        rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}", json=_pack_response([_version_entry(1)])
    )
    rsps_lib.add(rsps_lib.GET, f"{_API}/modpack/{_PACK_ID}/1", json=_version_detail(1, files=files))
    rsps_lib.add(rsps_lib.GET, "https://cdn.ftb.cloud/server.cfg", body=b"cfg-data")

    FTBPackInstaller(pack_id=_PACK_ID, session=build_session()).install(tmp_path)

    assert (tmp_path / "config" / "server.cfg").read_bytes() == b"cfg-data"
