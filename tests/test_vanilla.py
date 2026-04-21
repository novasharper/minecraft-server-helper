"""Tests for server/vanilla.py using mocked HTTP responses."""

import hashlib

import pytest
import responses as rsps_lib
from responses import RequestsMock

from mc_helper.config import ServerConfig
from mc_helper.http_client import build_session
from mc_helper.server.vanilla import VanillaInstaller, resolve_version


def _make_installer(version: str = "1.21.1", session=None, show_progress: bool = False):
    config = ServerConfig(type="vanilla", minecraft_version=version)
    return VanillaInstaller(config, session=session, show_progress=show_progress)


# ── fixtures / helpers ────────────────────────────────────────────────────────

_VERSION_MANIFEST = {
    "latest": {"release": "1.21.1", "snapshot": "24w14a"},
    "versions": [
        {
            "id": "1.21.1",
            "type": "release",
            "url": "https://launchermeta.mojang.com/v1/packages/abc/1.21.1.json",
        },
        {
            "id": "1.20.4",
            "type": "release",
            "url": "https://launchermeta.mojang.com/v1/packages/def/1.20.4.json",
        },
        {
            "id": "24w14a",
            "type": "snapshot",
            "url": "https://launchermeta.mojang.com/v1/packages/ghi/24w14a.json",
        },
    ],
}

_JAR_BYTES = b"fake-jar-content"
_JAR_SHA1 = hashlib.sha1(_JAR_BYTES).hexdigest()


def _version_manifest_detail(version_id: str, jar_url: str) -> dict:
    return {
        "id": version_id,
        "downloads": {
            "server": {
                "url": jar_url,
                "sha1": _JAR_SHA1,
            }
        },
    }


def _register_standard(responses: RequestsMock, version_id: str = "1.21.1") -> str:
    """Register all mocks needed for a standard vanilla install of *version_id*."""
    jar_url = f"https://launcher.mojang.com/v1/objects/fake/{version_id}-server.jar"
    version_url = next(v["url"] for v in _VERSION_MANIFEST["versions"] if v["id"] == version_id)

    responses.add(
        rsps_lib.GET,
        "https://launchermeta.mojang.com/mc/game/version_manifest.json",
        json=_VERSION_MANIFEST,
    )
    responses.add(rsps_lib.GET, version_url, json=_version_manifest_detail(version_id, jar_url))
    responses.add(
        rsps_lib.GET,
        jar_url,
        body=_JAR_BYTES,
        headers={"Content-Length": str(len(_JAR_BYTES))},
    )
    return jar_url


# ── resolve_version ───────────────────────────────────────────────────────────


@rsps_lib.activate
def test_resolve_version_latest():
    rsps_lib.add(
        rsps_lib.GET,
        "https://launchermeta.mojang.com/mc/game/version_manifest.json",
        json=_VERSION_MANIFEST,
    )
    session = build_session()
    assert resolve_version(session, "LATEST") == "1.21.1"


@rsps_lib.activate
def test_resolve_version_snapshot():
    rsps_lib.add(
        rsps_lib.GET,
        "https://launchermeta.mojang.com/mc/game/version_manifest.json",
        json=_VERSION_MANIFEST,
    )
    session = build_session()
    assert resolve_version(session, "SNAPSHOT") == "24w14a"


@rsps_lib.activate
def test_resolve_version_specific():
    rsps_lib.add(
        rsps_lib.GET,
        "https://launchermeta.mojang.com/mc/game/version_manifest.json",
        json=_VERSION_MANIFEST,
    )
    session = build_session()
    assert resolve_version(session, "1.20.4") == "1.20.4"


@rsps_lib.activate
def test_resolve_version_unknown_raises():
    rsps_lib.add(
        rsps_lib.GET,
        "https://launchermeta.mojang.com/mc/game/version_manifest.json",
        json=_VERSION_MANIFEST,
    )
    session = build_session()
    with pytest.raises(ValueError, match="not found"):
        resolve_version(session, "9.99.9")


# ── install ───────────────────────────────────────────────────────────────────


@rsps_lib.activate
def test_install_downloads_jar(tmp_path):
    _register_standard(rsps_lib, "1.21.1")
    session = build_session()
    jar = _make_installer("1.21.1", session=session).install(tmp_path)

    assert jar == tmp_path / "minecraft_server.1.21.1.jar"
    assert jar.exists()
    assert jar.read_bytes() == _JAR_BYTES


@rsps_lib.activate
def test_install_resolves_latest(tmp_path):
    _register_standard(rsps_lib, "1.21.1")
    # version manifest is called twice (resolve + install), add it twice
    rsps_lib.add(
        rsps_lib.GET,
        "https://launchermeta.mojang.com/mc/game/version_manifest.json",
        json=_VERSION_MANIFEST,
    )
    session = build_session()
    jar = _make_installer("LATEST", session=session).install(tmp_path)
    assert jar.name == "minecraft_server.1.21.1.jar"


@rsps_lib.activate
def test_install_verifies_sha1(tmp_path):
    """If the downloaded bytes don't match the sha1, a ValueError is raised."""
    version_url = _VERSION_MANIFEST["versions"][0]["url"]
    jar_url = "https://launcher.mojang.com/v1/objects/fake/1.21.1-server.jar"

    rsps_lib.add(
        rsps_lib.GET,
        "https://launchermeta.mojang.com/mc/game/version_manifest.json",
        json=_VERSION_MANIFEST,
    )
    rsps_lib.add(
        rsps_lib.GET,
        version_url,
        json=_version_manifest_detail("1.21.1", jar_url),
    )
    # Return body that doesn't match the sha1
    rsps_lib.add(rsps_lib.GET, jar_url, body=b"corrupt-data")

    session = build_session()
    with pytest.raises(ValueError, match="SHA-1 mismatch"):
        _make_installer("1.21.1", session=session).install(tmp_path)


@rsps_lib.activate
def test_install_no_server_download_raises(tmp_path):
    version_url = _VERSION_MANIFEST["versions"][0]["url"]
    rsps_lib.add(
        rsps_lib.GET,
        "https://launchermeta.mojang.com/mc/game/version_manifest.json",
        json=_VERSION_MANIFEST,
    )
    rsps_lib.add(
        rsps_lib.GET,
        version_url,
        json={"id": "1.21.1", "downloads": {}},  # no server key
    )
    session = build_session()
    with pytest.raises(ValueError, match="No server download"):
        _make_installer("1.21.1", session=session).install(tmp_path)
