"""Tests for pack/serverpack.py."""

import hashlib
import tarfile
import zipfile
from io import BytesIO

import pytest
import responses as rsps_lib

from mc_helper.http_client import build_session
from mc_helper.modpack.custom import (
    ServerPackInstaller,
    _extract_tar,
    _extract_zip,
    _resolve_github_url,
    _sha1_file,
)

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_zip(entries: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _make_tar_gz(entries: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, BytesIO(data))
    buf.seek(0)
    return buf.read()


def _github_release(assets: list[dict]) -> dict:
    return {"tag_name": "v1.0", "assets": assets}


def _asset(name: str, url: str) -> dict:
    return {"name": name, "browser_download_url": url}


# ── _sha1_file ────────────────────────────────────────────────────────────────


def test_sha1_file(tmp_path):
    data = b"hello world"
    f = tmp_path / "test.bin"
    f.write_bytes(data)
    assert _sha1_file(f) == hashlib.sha1(data).hexdigest()


# ── _extract_zip ──────────────────────────────────────────────────────────────


def test_extract_zip_no_strip(tmp_path):
    archive = tmp_path / "pack.zip"
    archive.write_bytes(_make_zip({"mods/jei.jar": b"jar", "config/a.cfg": b"cfg"}))
    dest = tmp_path / "out"
    _extract_zip(archive, dest, strip_components=0)
    assert (dest / "mods" / "jei.jar").read_bytes() == b"jar"
    assert (dest / "config" / "a.cfg").read_bytes() == b"cfg"


def test_extract_zip_strip_one(tmp_path):
    archive = tmp_path / "pack.zip"
    archive.write_bytes(_make_zip({"server/mods/jei.jar": b"jar"}))
    dest = tmp_path / "out"
    _extract_zip(archive, dest, strip_components=1)
    assert (dest / "mods" / "jei.jar").read_bytes() == b"jar"


def test_extract_zip_strip_skips_shallow_entries(tmp_path):
    archive = tmp_path / "pack.zip"
    archive.write_bytes(_make_zip({"root-file.txt": b"root", "sub/file.txt": b"sub"}))
    dest = tmp_path / "out"
    _extract_zip(archive, dest, strip_components=1)
    assert not (dest / "root-file.txt").exists()
    assert (dest / "file.txt").read_bytes() == b"sub"


# ── _extract_tar ──────────────────────────────────────────────────────────────


def test_extract_tar_no_strip(tmp_path):
    archive = tmp_path / "pack.tar.gz"
    archive.write_bytes(_make_tar_gz({"mods/mod.jar": b"jar"}))
    dest = tmp_path / "out"
    _extract_tar(archive, dest, strip_components=0)
    assert (dest / "mods" / "mod.jar").read_bytes() == b"jar"


def test_extract_tar_strip_one(tmp_path):
    archive = tmp_path / "pack.tar.gz"
    archive.write_bytes(_make_tar_gz({"server/mods/mod.jar": b"jar"}))
    dest = tmp_path / "out"
    _extract_tar(archive, dest, strip_components=1)
    assert (dest / "mods" / "mod.jar").read_bytes() == b"jar"


# ── _resolve_github_url ───────────────────────────────────────────────────────


@rsps_lib.activate
def test_resolve_github_latest():
    rsps_lib.add(
        rsps_lib.GET,
        "https://api.github.com/repos/owner/repo/releases/latest",
        json=_github_release([_asset("server.zip", "https://example.com/server.zip")]),
    )
    session = build_session()
    url = _resolve_github_url(session, "owner/repo", "LATEST", None)
    assert url == "https://example.com/server.zip"


@rsps_lib.activate
def test_resolve_github_specific_tag():
    rsps_lib.add(
        rsps_lib.GET,
        "https://api.github.com/repos/owner/repo/releases/tags/v2.0",
        json=_github_release([_asset("server.zip", "https://example.com/v2/server.zip")]),
    )
    session = build_session()
    url = _resolve_github_url(session, "owner/repo", "v2.0", None)
    assert url == "https://example.com/v2/server.zip"


@rsps_lib.activate
def test_resolve_github_asset_glob():
    rsps_lib.add(
        rsps_lib.GET,
        "https://api.github.com/repos/owner/repo/releases/latest",
        json=_github_release(
            [
                _asset("client.zip", "https://example.com/client.zip"),
                _asset("server.zip", "https://example.com/server.zip"),
            ]
        ),
    )
    session = build_session()
    url = _resolve_github_url(session, "owner/repo", "LATEST", "*server*")
    assert url == "https://example.com/server.zip"


@rsps_lib.activate
def test_resolve_github_no_matching_asset_raises():
    rsps_lib.add(
        rsps_lib.GET,
        "https://api.github.com/repos/owner/repo/releases/latest",
        json=_github_release([_asset("client.zip", "https://example.com/client.zip")]),
    )
    session = build_session()
    with pytest.raises(ValueError, match="No asset matching"):
        _resolve_github_url(session, "owner/repo", "LATEST", "*server*")


# ── install ───────────────────────────────────────────────────────────────────


@rsps_lib.activate
def test_install_direct_url_zip(tmp_path):
    zip_bytes = _make_zip({"mods/jei.jar": b"jar-data", "config/a.cfg": b"cfg"})
    rsps_lib.add(rsps_lib.GET, "https://example.com/pack.zip", body=zip_bytes)

    session = build_session()
    ServerPackInstaller(
        url="https://example.com/pack.zip", session=session, show_progress=False
    ).install(tmp_path)

    assert (tmp_path / "mods" / "jei.jar").read_bytes() == b"jar-data"
    assert (tmp_path / "config" / "a.cfg").read_bytes() == b"cfg"


@rsps_lib.activate
def test_install_direct_url_tar_gz(tmp_path):
    tar_bytes = _make_tar_gz({"mods/mod.jar": b"jar-data"})
    rsps_lib.add(rsps_lib.GET, "https://example.com/pack.tar.gz", body=tar_bytes)

    session = build_session()
    ServerPackInstaller(
        url="https://example.com/pack.tar.gz", session=session, show_progress=False
    ).install(tmp_path)

    assert (tmp_path / "mods" / "mod.jar").read_bytes() == b"jar-data"


@rsps_lib.activate
def test_install_github(tmp_path):
    zip_bytes = _make_zip({"mods/mod.jar": b"jar"})
    rsps_lib.add(
        rsps_lib.GET,
        "https://api.github.com/repos/owner/repo/releases/latest",
        json=_github_release([_asset("server.zip", "https://example.com/server.zip")]),
    )
    rsps_lib.add(rsps_lib.GET, "https://example.com/server.zip", body=zip_bytes)

    session = build_session()
    ServerPackInstaller(
        github="owner/repo", asset="*server*", session=session, show_progress=False
    ).install(tmp_path)

    assert (tmp_path / "mods" / "mod.jar").read_bytes() == b"jar"


@rsps_lib.activate
def test_install_skips_if_sha1_matches(tmp_path):
    zip_bytes = _make_zip({"mods/mod.jar": b"jar"})
    sha1 = hashlib.sha1(zip_bytes).hexdigest()

    from mc_helper.manifest import Manifest

    m = Manifest(tmp_path)
    m.pack_sha1 = sha1
    m.save()

    # Register the URL but the download should be made then extraction skipped
    rsps_lib.add(rsps_lib.GET, "https://example.com/pack.zip", body=zip_bytes)

    session = build_session()
    ServerPackInstaller(
        url="https://example.com/pack.zip", session=session, show_progress=False
    ).install(tmp_path)

    # File should NOT be extracted since sha1 matches
    assert not (tmp_path / "mods" / "mod.jar").exists()


@rsps_lib.activate
def test_install_force_update_ignores_sha1(tmp_path):
    zip_bytes = _make_zip({"mods/mod.jar": b"jar"})
    sha1 = hashlib.sha1(zip_bytes).hexdigest()

    from mc_helper.manifest import Manifest

    m = Manifest(tmp_path)
    m.pack_sha1 = sha1
    m.save()

    rsps_lib.add(rsps_lib.GET, "https://example.com/pack.zip", body=zip_bytes)

    session = build_session()
    ServerPackInstaller(
        url="https://example.com/pack.zip",
        force_update=True,
        session=session,
        show_progress=False,
    ).install(tmp_path)

    assert (tmp_path / "mods" / "mod.jar").read_bytes() == b"jar"


@rsps_lib.activate
def test_install_disable_mods(tmp_path):
    zip_bytes = _make_zip({"mods/optifine.jar": b"jar", "mods/other.jar": b"other"})
    rsps_lib.add(rsps_lib.GET, "https://example.com/pack.zip", body=zip_bytes)

    session = build_session()
    ServerPackInstaller(
        url="https://example.com/pack.zip",
        exclude_mods=["optifine.jar"],
        session=session,
        show_progress=False,
    ).install(tmp_path)

    assert not (tmp_path / "mods" / "optifine.jar").exists()
    assert (tmp_path / "mods" / "optifine.jar.disabled").exists()
    assert (tmp_path / "mods" / "other.jar").exists()


def test_install_no_source_raises(tmp_path):
    with pytest.raises(ValueError, match="Either url or github"):
        ServerPackInstaller(show_progress=False).install(tmp_path)
