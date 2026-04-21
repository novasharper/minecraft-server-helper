import json

from mc_helper.manifest import Manifest

# ── load / save ───────────────────────────────────────────────────────────────


def test_load_missing_is_noop(tmp_path):
    m = Manifest(tmp_path)
    m.load()  # should not raise
    assert m.files == []
    assert m.mc_version is None


def test_save_creates_file(tmp_path):
    m = Manifest(tmp_path)
    m.mc_version = "1.21.1"
    m.save()
    assert (tmp_path / ".mc-helper-manifest.json").exists()


def test_save_and_reload(tmp_path):
    m = Manifest(tmp_path)
    m.mc_version = "1.21.1"
    m.loader_type = "fabric"
    m.loader_version = "0.15.0"
    m.files = ["mods/fabric-api.jar", "mods/sodium.jar"]
    m.save()

    m2 = Manifest(tmp_path)
    m2.load()
    assert m2.mc_version == "1.21.1"
    assert m2.loader_type == "fabric"
    assert m2.loader_version == "0.15.0"
    assert set(m2.files) == {"mods/fabric-api.jar", "mods/sodium.jar"}


def test_save_writes_timestamp(tmp_path):
    m = Manifest(tmp_path)
    m.save()
    data = json.loads((tmp_path / ".mc-helper-manifest.json").read_text())
    assert "timestamp" in data


def test_save_creates_parent_dirs(tmp_path):
    output_dir = tmp_path / "deep" / "output"
    m = Manifest(output_dir)
    m.save()
    assert (output_dir / ".mc-helper-manifest.json").exists()


# ── pack_sha1 ─────────────────────────────────────────────────────────────────


def test_pack_sha1_roundtrip(tmp_path):
    m = Manifest(tmp_path)
    m.pack_sha1 = "abc123"
    m.save()
    m2 = Manifest(tmp_path)
    m2.load()
    assert m2.pack_sha1 == "abc123"


# ── add_file / files ──────────────────────────────────────────────────────────


def test_add_file(tmp_path):
    m = Manifest(tmp_path)
    m.add_file("mods/jei.jar")
    m.add_file("mods/sodium.jar")
    assert "mods/jei.jar" in m.files
    assert "mods/sodium.jar" in m.files


def test_add_file_no_duplicates(tmp_path):
    m = Manifest(tmp_path)
    m.add_file("mods/jei.jar")
    m.add_file("mods/jei.jar")
    assert m.files.count("mods/jei.jar") == 1


def test_add_file_accepts_path_object(tmp_path):
    from pathlib import Path

    m = Manifest(tmp_path)
    m.add_file(Path("mods/jei.jar"))
    assert "mods/jei.jar" in m.files


# ── files_changed ─────────────────────────────────────────────────────────────


def test_files_changed_false_when_same(tmp_path):
    m = Manifest(tmp_path)
    m.files = ["a.jar", "b.jar"]
    assert m.files_changed(["b.jar", "a.jar"]) is False


def test_files_changed_true_when_different(tmp_path):
    m = Manifest(tmp_path)
    m.files = ["a.jar", "b.jar"]
    assert m.files_changed(["a.jar", "c.jar"]) is True


def test_files_changed_true_when_added(tmp_path):
    m = Manifest(tmp_path)
    m.files = ["a.jar"]
    assert m.files_changed(["a.jar", "b.jar"]) is True


def test_files_changed_true_when_removed(tmp_path):
    m = Manifest(tmp_path)
    m.files = ["a.jar", "b.jar"]
    assert m.files_changed(["a.jar"]) is True


# ── cleanup_stale ─────────────────────────────────────────────────────────────


def test_cleanup_stale_deletes_removed_files(tmp_path):
    (tmp_path / "mods").mkdir()
    old = tmp_path / "mods" / "old.jar"
    old.write_bytes(b"x")
    keep = tmp_path / "mods" / "keep.jar"
    keep.write_bytes(b"x")

    m = Manifest(tmp_path)
    m.files = ["mods/old.jar", "mods/keep.jar"]

    deleted = m.cleanup_stale(new_files=["mods/keep.jar"])
    assert old in deleted
    assert not old.exists()
    assert keep.exists()


def test_cleanup_stale_returns_deleted_paths(tmp_path):
    (tmp_path / "mods").mkdir()
    stale = tmp_path / "mods" / "stale.jar"
    stale.write_bytes(b"x")

    m = Manifest(tmp_path)
    m.files = ["mods/stale.jar"]

    deleted = m.cleanup_stale(new_files=[])
    assert stale in deleted


def test_cleanup_stale_ignores_already_missing(tmp_path):
    m = Manifest(tmp_path)
    m.files = ["mods/ghost.jar"]  # file never created on disk
    deleted = m.cleanup_stale(new_files=[])
    assert deleted == []
