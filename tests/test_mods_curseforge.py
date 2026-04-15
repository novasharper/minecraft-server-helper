"""Tests for mods/curseforge.py."""

import pytest
import responses as rsps_lib

from mc_helper.http_client import build_session
from mc_helper.mods.curseforge import install_mod, parse_mod_spec

_API = "https://api.curseforge.com"
_FAKE_KEY = "test-api-key"


# ── parse_mod_spec ────────────────────────────────────────────────────────────


def test_parse_slug():
    assert parse_mod_spec("jei") == ("jei", None)


def test_parse_slug_with_file_id():
    assert parse_mod_spec("jei:4593548") == ("jei", 4593548)


def test_parse_project_id():
    assert parse_mod_spec("238222") == (238222, None)


def test_parse_project_id_with_file_id():
    assert parse_mod_spec("238222:4593548") == (238222, 4593548)


def test_parse_full_url():
    assert parse_mod_spec("https://www.curseforge.com/minecraft/mc-mods/jei") == ("jei", None)


def test_parse_full_url_trailing_slash():
    assert parse_mod_spec("https://www.curseforge.com/minecraft/mc-mods/jei/") == ("jei", None)


# ── helpers ───────────────────────────────────────────────────────────────────


def _mod_search_response(mod_id: int = 238222, slug: str = "jei") -> dict:
    return {"data": [{"id": mod_id, "slug": slug, "name": slug.upper()}]}


def _file_response(file_id: int = 4593548, filename: str = "jei-1.21.1-18.0.jar") -> dict:
    cdn = f"https://edge.forgecdn.net/files/{file_id // 1000}/{file_id % 1000}/{filename}"
    return {
        "data": {
            "id": file_id,
            "fileName": filename,
            "downloadUrl": cdn,
        }
    }


def _files_list_response(file_id: int = 4593548, filename: str = "jei-1.21.1-18.0.jar") -> dict:
    cdn = f"https://edge.forgecdn.net/files/{file_id // 1000}/{file_id % 1000}/{filename}"
    return {
        "data": [
            {
                "id": file_id,
                "fileName": filename,
                "downloadUrl": cdn,
            }
        ]
    }


# ── install_mod ───────────────────────────────────────────────────────────────


@rsps_lib.activate
def test_install_mod_by_slug(tmp_path):
    jar_bytes = b"jei-jar"
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/search?gameId=432&slug=jei&classId=6",
        json=_mod_search_response(),
    )
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/238222/files",
        json=_files_list_response(),
    )
    rsps_lib.add(
        rsps_lib.GET,
        "https://edge.forgecdn.net/files/4593/548/jei-1.21.1-18.0.jar",
        body=jar_bytes,
    )

    session = build_session()
    path = install_mod("jei", tmp_path, api_key=_FAKE_KEY, session=session, show_progress=False)

    assert path == "mods/jei-1.21.1-18.0.jar"
    assert (tmp_path / "mods" / "jei-1.21.1-18.0.jar").read_bytes() == jar_bytes


@rsps_lib.activate
def test_install_mod_by_project_id(tmp_path):
    jar_bytes = b"jei-jar-by-id"
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/238222/files",
        json=_files_list_response(),
    )
    rsps_lib.add(
        rsps_lib.GET,
        "https://edge.forgecdn.net/files/4593/548/jei-1.21.1-18.0.jar",
        body=jar_bytes,
    )

    session = build_session()
    path = install_mod("238222", tmp_path, api_key=_FAKE_KEY, session=session, show_progress=False)

    assert path == "mods/jei-1.21.1-18.0.jar"


@rsps_lib.activate
def test_install_mod_by_slug_with_file_id(tmp_path):
    jar_bytes = b"specific-file-jar"
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/search?gameId=432&slug=jei&classId=6",
        json=_mod_search_response(),
    )
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/238222/files/4593548",
        json=_file_response(),
    )
    rsps_lib.add(
        rsps_lib.GET,
        "https://edge.forgecdn.net/files/4593/548/jei-1.21.1-18.0.jar",
        body=jar_bytes,
    )

    session = build_session()
    path = install_mod(
        "jei:4593548", tmp_path, api_key=_FAKE_KEY, session=session, show_progress=False
    )

    assert path == "mods/jei-1.21.1-18.0.jar"


@rsps_lib.activate
def test_install_mod_by_project_id_with_file_id(tmp_path):
    jar_bytes = b"direct-file-jar"
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/238222/files/4593548",
        json=_file_response(),
    )
    rsps_lib.add(
        rsps_lib.GET,
        "https://edge.forgecdn.net/files/4593/548/jei-1.21.1-18.0.jar",
        body=jar_bytes,
    )

    session = build_session()
    path = install_mod(
        "238222:4593548", tmp_path, api_key=_FAKE_KEY, session=session, show_progress=False
    )

    assert path == "mods/jei-1.21.1-18.0.jar"


@rsps_lib.activate
def test_install_mod_by_url(tmp_path):
    jar_bytes = b"url-resolved-jar"
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/search?gameId=432&slug=jei&classId=6",
        json=_mod_search_response(),
    )
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/238222/files",
        json=_files_list_response(),
    )
    rsps_lib.add(
        rsps_lib.GET,
        "https://edge.forgecdn.net/files/4593/548/jei-1.21.1-18.0.jar",
        body=jar_bytes,
    )

    session = build_session()
    path = install_mod(
        "https://www.curseforge.com/minecraft/mc-mods/jei",
        tmp_path,
        api_key=_FAKE_KEY,
        session=session,
        show_progress=False,
    )

    assert path == "mods/jei-1.21.1-18.0.jar"


@rsps_lib.activate
def test_install_mod_slug_not_found_raises(tmp_path):
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/search?gameId=432&slug=nonexistent&classId=6",
        json={"data": []},
    )

    session = build_session()
    with pytest.raises(ValueError, match="not found for slug"):
        install_mod(
            "nonexistent", tmp_path, api_key=_FAKE_KEY, session=session, show_progress=False
        )


@rsps_lib.activate
def test_install_mod_no_files_raises(tmp_path):
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/238222/files",
        json={"data": []},
    )

    session = build_session()
    with pytest.raises(ValueError, match="No files found"):
        install_mod("238222", tmp_path, api_key=_FAKE_KEY, session=session, show_progress=False)


@rsps_lib.activate
def test_install_mod_null_download_url_uses_fallback(tmp_path):
    """Files with null downloadUrl should fall back to the forgecdn.net URL."""
    jar_bytes = b"fallback-cdn-jar"
    file_id = 5000001
    filename = "mod-1.0.jar"
    fallback_url = f"https://edge.forgecdn.net/files/{file_id // 1000}/{file_id % 1000}/{filename}"

    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/238222/files",
        json={"data": [{"id": file_id, "fileName": filename, "downloadUrl": None}]},
    )
    rsps_lib.add(rsps_lib.GET, fallback_url, body=jar_bytes)

    session = build_session()
    path = install_mod("238222", tmp_path, api_key=_FAKE_KEY, session=session, show_progress=False)

    assert path == f"mods/{filename}"
    assert (tmp_path / "mods" / filename).read_bytes() == jar_bytes


@rsps_lib.activate
def test_install_mod_with_mc_version_filter(tmp_path):
    """Passing minecraft_version should append gameVersion to the files query."""
    jar_bytes = b"mc-filtered-jar"
    rsps_lib.add(
        rsps_lib.GET,
        f"{_API}/v1/mods/238222/files?gameVersion=1.21.1",
        json=_files_list_response(),
    )
    rsps_lib.add(
        rsps_lib.GET,
        "https://edge.forgecdn.net/files/4593/548/jei-1.21.1-18.0.jar",
        body=jar_bytes,
    )

    session = build_session()
    install_mod(
        "238222", tmp_path,
        api_key=_FAKE_KEY,
        minecraft_version="1.21.1",
        session=session,
        show_progress=False,
    )

    assert (tmp_path / "mods" / "jei-1.21.1-18.0.jar").exists()
