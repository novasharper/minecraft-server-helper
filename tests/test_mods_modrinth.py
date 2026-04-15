"""Tests for mods/modrinth.py."""

import pytest
import responses as rsps_lib

from mc_helper.http_client import build_session
from mc_helper.mods.modrinth import install_mod, parse_mod_spec

_API = "https://api.modrinth.com/v2"


# ── parse_mod_spec ────────────────────────────────────────────────────────────


def test_parse_bare_slug():
    assert parse_mod_spec("fabric-api") == ("fabric-api", "LATEST")


def test_parse_slug_with_version():
    assert parse_mod_spec("fabric-api:0.119.2+1.21.4") == ("fabric-api", "0.119.2+1.21.4")


def test_parse_project_id():
    assert parse_mod_spec("P7dR8mSH") == ("P7dR8mSH", "LATEST")


def test_parse_project_id_with_version_id():
    assert parse_mod_spec("P7dR8mSH:abc123") == ("P7dR8mSH", "abc123")


# ── install_mod ───────────────────────────────────────────────────────────────


_SHA1 = {
    b"fake-jar-content": "3e7ad2d49a6bf15bcf72d77e06cb211c6960c830",
    b"specific-version-jar": "ddd786a9f6c6ee30398d6d3ddd872dfddc9968c4",
    b"data": "a17c9aaa61e80a1bf71d0d850af4e5baa9800bbd",
    b"beta-jar": "6af68bba79eced2776a8ad2affa7f9ae04bea41c",
}


def _make_version(
    version_number: str = "0.100.0+1.21.1",
    version_type: str = "release",
    filename: str = "fabric-api-0.100.0+1.21.1.jar",
    sha1: str = "3e7ad2d49a6bf15bcf72d77e06cb211c6960c830",
) -> dict:
    return {
        "id": "ver-001",
        "version_number": version_number,
        "version_type": version_type,
        "files": [
            {
                "url": f"https://cdn.modrinth.com/{filename}",
                "filename": filename,
                "primary": True,
                "hashes": {"sha1": sha1},
            }
        ],
        "game_versions": ["1.21.1"],
        "loaders": ["fabric"],
    }


@rsps_lib.activate
def test_install_mod_downloads_jar(tmp_path):
    jar_bytes = b"fake-jar-content"
    version = _make_version()
    rsps_lib.add(rsps_lib.GET, f"{_API}/project/fabric-api/versions", json=[version])
    rsps_lib.add(
        rsps_lib.GET,
        "https://cdn.modrinth.com/fabric-api-0.100.0+1.21.1.jar",
        body=jar_bytes,
    )

    session = build_session()
    path = install_mod(
        "fabric-api", tmp_path,
        minecraft_version="1.21.1", loader="fabric",
        session=session, show_progress=False,
    )

    assert path == "mods/fabric-api-0.100.0+1.21.1.jar"
    assert (tmp_path / "mods" / "fabric-api-0.100.0+1.21.1.jar").read_bytes() == jar_bytes


@rsps_lib.activate
def test_install_mod_specific_version(tmp_path):
    jar_bytes = b"specific-version-jar"
    version = _make_version(
        version_number="0.90.0+1.20.4", filename="fabric-api-0.90.0+1.20.4.jar",
        sha1=_SHA1[b"specific-version-jar"],
    )
    rsps_lib.add(rsps_lib.GET, f"{_API}/project/fabric-api/versions", json=[version])
    rsps_lib.add(
        rsps_lib.GET,
        "https://cdn.modrinth.com/fabric-api-0.90.0+1.20.4.jar",
        body=jar_bytes,
    )

    session = build_session()
    path = install_mod(
        "fabric-api:0.90.0+1.20.4", tmp_path,
        session=session, show_progress=False,
    )

    assert path == "mods/fabric-api-0.90.0+1.20.4.jar"
    assert (tmp_path / "mods" / "fabric-api-0.90.0+1.20.4.jar").read_bytes() == jar_bytes


@rsps_lib.activate
def test_install_mod_creates_mods_subdir(tmp_path):
    jar_bytes = b"fake-jar-content"
    version = _make_version()
    rsps_lib.add(rsps_lib.GET, f"{_API}/project/fabric-api/versions", json=[version])
    rsps_lib.add(rsps_lib.GET, "https://cdn.modrinth.com/fabric-api-0.100.0+1.21.1.jar", body=jar_bytes)

    session = build_session()
    install_mod("fabric-api", tmp_path, session=session, show_progress=False)

    assert (tmp_path / "mods").is_dir()


@rsps_lib.activate
def test_install_mod_falls_back_to_first_file_when_no_primary(tmp_path):
    jar_bytes = b"fallback-jar"
    version = {
        "id": "ver-002",
        "version_number": "1.0.0",
        "version_type": "release",
        "files": [
            {
                "url": "https://cdn.modrinth.com/mod-1.0.0.jar",
                "filename": "mod-1.0.0.jar",
                "primary": False,
                "hashes": {},
            }
        ],
        "game_versions": ["1.21.1"],
        "loaders": ["fabric"],
    }
    rsps_lib.add(rsps_lib.GET, f"{_API}/project/some-mod/versions", json=[version])
    rsps_lib.add(rsps_lib.GET, "https://cdn.modrinth.com/mod-1.0.0.jar", body=jar_bytes)

    session = build_session()
    path = install_mod("some-mod", tmp_path, session=session, show_progress=False)

    assert path == "mods/mod-1.0.0.jar"
    assert (tmp_path / "mods" / "mod-1.0.0.jar").read_bytes() == jar_bytes


@rsps_lib.activate
def test_install_mod_version_not_found_raises(tmp_path):
    rsps_lib.add(rsps_lib.GET, f"{_API}/project/no-such-mod/versions", json=[])

    session = build_session()
    with pytest.raises(ValueError, match="No Modrinth versions"):
        install_mod("no-such-mod", tmp_path, minecraft_version="1.21.1", session=session, show_progress=False)


@rsps_lib.activate
def test_install_mod_beta_fallback(tmp_path):
    """When only beta versions exist, the installer should still pick one."""
    jar_bytes = b"beta-jar"
    version = _make_version(
        version_type="beta", filename="mod-2.0-beta.jar", version_number="2.0-beta",
        sha1=_SHA1[b"beta-jar"],
    )
    rsps_lib.add(rsps_lib.GET, f"{_API}/project/beta-mod/versions", json=[version])
    rsps_lib.add(rsps_lib.GET, "https://cdn.modrinth.com/mod-2.0-beta.jar", body=jar_bytes)

    session = build_session()
    path = install_mod("beta-mod", tmp_path, session=session, show_progress=False)

    assert path == "mods/mod-2.0-beta.jar"
