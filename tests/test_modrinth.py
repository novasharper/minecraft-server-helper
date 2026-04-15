"""Tests for modpack/modrinth.py."""

import json
import zipfile
from io import BytesIO

import responses as rsps_lib

from mc_helper.http_client import build_session
from mc_helper.modpack.modrinth import _should_include, install, resolve_version

_API = "https://api.modrinth.com/v2"

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_version(version_type: str = "release", version_number: str = "1.0.0") -> dict:
    return {
        "id": "version-abc",
        "version_number": version_number,
        "version_type": version_type,
        "files": [{"url": "https://cdn.modrinth.com/pack.mrpack", "primary": True}],
        "game_versions": ["1.21.1"],
        "loaders": ["fabric"],
    }


def _make_mrpack(index: dict, overrides: dict[str, bytes] | None = None) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(index))
        for path, data in (overrides or {}).items():
            zf.writestr(f"overrides/{path}", data)
    return buf.getvalue()


def _minimal_index(files: list | None = None) -> dict:
    return {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "1.0.0",
        "name": "Test Pack",
        "dependencies": {"minecraft": "1.21.1", "fabric-loader": "0.15.0"},
        "files": files or [],
    }


# ── _should_include ───────────────────────────────────────────────────────────


def test_should_include_server_unsupported():
    entry = {"path": "mods/client-only.jar", "env": {"server": "unsupported"}, "downloads": []}
    assert _should_include(entry, []) is False


def test_should_include_server_required():
    entry = {"path": "mods/required.jar", "env": {"server": "required"}, "downloads": []}
    assert _should_include(entry, []) is True


def test_should_include_no_env():
    entry = {"path": "mods/noenv.jar", "downloads": []}
    assert _should_include(entry, []) is True


def test_should_include_excluded_by_name():
    entry = {"path": "mods/sodium.jar", "env": {"server": "required"}, "downloads": []}
    assert _should_include(entry, ["sodium.jar"]) is False


def test_should_include_glob_exclusion():
    entry = {"path": "mods/sodium-0.6.0.jar", "env": {}, "downloads": []}
    assert _should_include(entry, ["sodium*"]) is False


# ── resolve_version ───────────────────────────────────────────────────────────


@rsps_lib.activate
def test_resolve_version_latest_picks_first_release():
    versions = [
        _make_version("release", "2.0.0"),
        _make_version("beta", "2.1.0-beta"),
        _make_version("release", "1.0.0"),
    ]
    rsps_lib.add(rsps_lib.GET, f"{_API}/project/my-pack/versions", json=versions)
    session = build_session()
    v = resolve_version(session, "my-pack", "1.21.1", "fabric")
    assert v["version_number"] == "2.0.0"


@rsps_lib.activate
def test_resolve_version_specific():
    versions = [_make_version("release", "1.5.0")]
    rsps_lib.add(
        rsps_lib.GET, f"{_API}/project/my-pack/versions", json=versions
    )
    session = build_session()
    v = resolve_version(session, "my-pack", None, None, requested_version="1.5.0")
    assert v["version_number"] == "1.5.0"


@rsps_lib.activate
def test_resolve_version_not_found_raises():
    rsps_lib.add(rsps_lib.GET, f"{_API}/project/my-pack/versions", json=[])
    session = build_session()
    import pytest
    with pytest.raises(ValueError, match="No Modrinth versions"):
        resolve_version(session, "my-pack", "1.21.1", "fabric")


# ── install ───────────────────────────────────────────────────────────────────


@rsps_lib.activate
def test_install_downloads_files(tmp_path):
    mod_bytes = b"fake-mod-jar"
    index = _minimal_index(files=[
        {
            "path": "mods/fabric-api.jar",
            "env": {"server": "required"},
            "downloads": ["https://cdn.modrinth.com/fabric-api.jar"],
            "hashes": {},
        }
    ])
    mrpack_bytes = _make_mrpack(index)

    rsps_lib.add(
        rsps_lib.GET, f"{_API}/project/test-pack/versions",
        json=[_make_version()],
    )
    rsps_lib.add(rsps_lib.GET, "https://cdn.modrinth.com/pack.mrpack", body=mrpack_bytes)
    rsps_lib.add(rsps_lib.GET, "https://cdn.modrinth.com/fabric-api.jar", body=mod_bytes)

    session = build_session()
    result = install("test-pack", tmp_path, session=session, show_progress=False)

    assert result["name"] == "Test Pack"
    assert (tmp_path / "mods" / "fabric-api.jar").read_bytes() == mod_bytes


@rsps_lib.activate
def test_install_skips_client_only(tmp_path):
    index = _minimal_index(files=[
        {
            "path": "mods/client-only.jar",
            "env": {"server": "unsupported"},
            "downloads": ["https://cdn.modrinth.com/client-only.jar"],
            "hashes": {},
        }
    ])
    mrpack_bytes = _make_mrpack(index)

    rsps_lib.add(rsps_lib.GET, f"{_API}/project/test-pack/versions", json=[_make_version()])
    rsps_lib.add(rsps_lib.GET, "https://cdn.modrinth.com/pack.mrpack", body=mrpack_bytes)
    # client-only should NOT be downloaded — no mock registered for it

    session = build_session()
    install("test-pack", tmp_path, session=session, show_progress=False)

    assert not (tmp_path / "mods" / "client-only.jar").exists()


@rsps_lib.activate
def test_install_extracts_overrides(tmp_path):
    index = _minimal_index()
    mrpack_bytes = _make_mrpack(index, overrides={"config/server.cfg": b"setting=true"})

    rsps_lib.add(rsps_lib.GET, f"{_API}/project/test-pack/versions", json=[_make_version()])
    rsps_lib.add(rsps_lib.GET, "https://cdn.modrinth.com/pack.mrpack", body=mrpack_bytes)

    session = build_session()
    install("test-pack", tmp_path, session=session, show_progress=False)

    assert (tmp_path / "config" / "server.cfg").read_bytes() == b"setting=true"


@rsps_lib.activate
def test_install_writes_manifest(tmp_path):
    index = _minimal_index()
    mrpack_bytes = _make_mrpack(index)

    rsps_lib.add(rsps_lib.GET, f"{_API}/project/test-pack/versions", json=[_make_version()])
    rsps_lib.add(rsps_lib.GET, "https://cdn.modrinth.com/pack.mrpack", body=mrpack_bytes)

    session = build_session()
    install("test-pack", tmp_path, session=session, show_progress=False)

    from mc_helper.manifest import Manifest
    m = Manifest(tmp_path)
    m.load()
    assert m.mc_version == "1.21.1"
    assert m.loader_type == "fabric"
    assert m.loader_version == "0.15.0"


@rsps_lib.activate
def test_install_normalizes_loader_type_fabric(tmp_path):
    """Modrinth dep key 'fabric-loader' must be saved as 'fabric', not raw."""
    index = _minimal_index()  # dependencies: {"minecraft": "1.21.1", "fabric-loader": "0.15.0"}
    mrpack_bytes = _make_mrpack(index)

    rsps_lib.add(rsps_lib.GET, f"{_API}/project/fabric-pack/versions", json=[_make_version()])
    rsps_lib.add(rsps_lib.GET, "https://cdn.modrinth.com/pack.mrpack", body=mrpack_bytes)

    session = build_session()
    install("fabric-pack", tmp_path, session=session, show_progress=False)

    from mc_helper.manifest import Manifest
    m = Manifest(tmp_path)
    m.load()
    assert m.loader_type == "fabric", f"Expected 'fabric', got {m.loader_type!r}"


@rsps_lib.activate
def test_install_prefers_sha512_over_sha1(tmp_path):
    """When a modpack file provides sha512, it should be used instead of sha1."""
    import hashlib
    mod_bytes = b"some-mod-content"
    sha512_hex = hashlib.sha512(mod_bytes).hexdigest()

    index = _minimal_index(files=[
        {
            "path": "mods/mod.jar",
            "env": {"server": "required"},
            "downloads": ["https://cdn.modrinth.com/mod.jar"],
            "hashes": {"sha512": sha512_hex, "sha1": "wrongsha1"},
        }
    ])
    mrpack_bytes = _make_mrpack(index)

    rsps_lib.add(rsps_lib.GET, f"{_API}/project/sha-pack/versions", json=[_make_version()])
    rsps_lib.add(rsps_lib.GET, "https://cdn.modrinth.com/pack.mrpack", body=mrpack_bytes)
    rsps_lib.add(rsps_lib.GET, "https://cdn.modrinth.com/mod.jar", body=mod_bytes)

    session = build_session()
    # Should not raise even though sha1 is wrong — sha512 is used instead
    install("sha-pack", tmp_path, session=session, show_progress=False)
    assert (tmp_path / "mods" / "mod.jar").read_bytes() == mod_bytes
