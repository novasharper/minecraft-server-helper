import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MANIFEST_FILENAME = ".mc-helper-manifest.json"


class Manifest:
    """Tracks installed files and metadata in <output_dir>/.mc-helper-manifest.json."""

    def __init__(self, output_dir: Path) -> None:
        self.path = output_dir / _MANIFEST_FILENAME
        self._data: dict[str, Any] = {}

    # ── Persistence ───────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load manifest from disk. No-op if the file does not exist."""
        if self.path.exists():
            self._data = json.loads(self.path.read_text())

    def save(self) -> None:
        """Write manifest to disk, creating parent directories as needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data["timestamp"] = datetime.now(timezone.utc).isoformat()
        self.path.write_text(json.dumps(self._data, indent=2))

    # ── Metadata accessors ────────────────────────────────────────────────────

    @property
    def mc_version(self) -> str | None:
        return self._data.get("mc_version")

    @mc_version.setter
    def mc_version(self, value: str) -> None:
        self._data["mc_version"] = value

    @property
    def loader_type(self) -> str | None:
        return self._data.get("loader_type")

    @loader_type.setter
    def loader_type(self, value: str) -> None:
        self._data["loader_type"] = value

    @property
    def loader_version(self) -> str | None:
        return self._data.get("loader_version")

    @loader_version.setter
    def loader_version(self, value: str) -> None:
        self._data["loader_version"] = value

    @property
    def pack_sha1(self) -> str | None:
        return self._data.get("pack_sha1")

    @pack_sha1.setter
    def pack_sha1(self, value: str) -> None:
        self._data["pack_sha1"] = value

    # ── File tracking ─────────────────────────────────────────────────────────

    @property
    def files(self) -> list[str]:
        return self._data.get("files", [])

    @files.setter
    def files(self, value: list[str]) -> None:
        self._data["files"] = value

    def add_file(self, path: str | Path) -> None:
        """Record a file path (relative to output_dir) as managed."""
        entry = str(path)
        if entry not in self.files:
            current = self.files
            current.append(entry)
            self.files = current

    def files_changed(self, new_files: list[str]) -> bool:
        """Return True if *new_files* differs from the tracked file list."""
        return sorted(self.files) != sorted(new_files)

    def cleanup_stale(self, output_dir: Path, new_files: list[str]) -> list[Path]:
        """Delete files that are tracked in the manifest but absent from *new_files*.

        Returns the list of deleted paths.
        """
        new_set = set(new_files)
        deleted: list[Path] = []
        for entry in self.files:
            if entry not in new_set:
                target = output_dir / entry
                if target.exists():
                    target.unlink()
                    deleted.append(target)
        return deleted
