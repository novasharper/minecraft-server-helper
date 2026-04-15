"""Tests for http_client.py — download_file hash verification."""

import hashlib

import pytest
import responses as rsps_lib

from mc_helper.http_client import build_session, download_file

_URL = "https://example.com/file.jar"


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha512(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


@rsps_lib.activate
def test_download_no_verification(tmp_path):
    data = b"hello"
    rsps_lib.add(rsps_lib.GET, _URL, body=data)
    dest = tmp_path / "file.jar"
    result = download_file(_URL, dest, session=build_session(), show_progress=False)
    assert result == dest
    assert dest.read_bytes() == data


@rsps_lib.activate
def test_download_sha1_pass(tmp_path):
    data = b"hello"
    rsps_lib.add(rsps_lib.GET, _URL, body=data)
    dest = tmp_path / "file.jar"
    session = build_session()
    download_file(_URL, dest, expected_sha1=_sha1(data), session=session, show_progress=False)
    assert dest.read_bytes() == data


@rsps_lib.activate
def test_download_sha1_fail(tmp_path):
    data = b"hello"
    rsps_lib.add(rsps_lib.GET, _URL, body=data)
    dest = tmp_path / "file.jar"
    session = build_session()
    with pytest.raises(ValueError, match="SHA-1 mismatch"):
        download_file(_URL, dest, expected_sha1="wronghash", session=session, show_progress=False)
    assert not dest.exists()


@rsps_lib.activate
def test_download_sha256_pass(tmp_path):
    data = b"hello"
    rsps_lib.add(rsps_lib.GET, _URL, body=data)
    dest = tmp_path / "file.jar"
    session = build_session()
    download_file(_URL, dest, expected_sha256=_sha256(data), session=session, show_progress=False)
    assert dest.read_bytes() == data


@rsps_lib.activate
def test_download_sha256_fail(tmp_path):
    data = b"hello"
    rsps_lib.add(rsps_lib.GET, _URL, body=data)
    dest = tmp_path / "file.jar"
    session = build_session()
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        download_file(_URL, dest, expected_sha256="wronghash", session=session, show_progress=False)
    assert not dest.exists()


@rsps_lib.activate
def test_download_sha512_pass(tmp_path):
    data = b"hello"
    rsps_lib.add(rsps_lib.GET, _URL, body=data)
    dest = tmp_path / "file.jar"
    session = build_session()
    download_file(_URL, dest, expected_sha512=_sha512(data), session=session, show_progress=False)
    assert dest.read_bytes() == data


@rsps_lib.activate
def test_download_sha512_fail(tmp_path):
    data = b"hello"
    rsps_lib.add(rsps_lib.GET, _URL, body=data)
    dest = tmp_path / "file.jar"
    session = build_session()
    with pytest.raises(ValueError, match="SHA-512 mismatch"):
        download_file(_URL, dest, expected_sha512="wronghash", session=session, show_progress=False)
    assert not dest.exists()
