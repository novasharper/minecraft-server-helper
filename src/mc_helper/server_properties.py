from pathlib import Path


def merge_server_properties(path: Path, overrides: dict[str, str | int | bool]) -> None:
    """Write or merge *overrides* into a server.properties file at *path*.

    If the file exists, matching keys are updated in-place preserving comments
    and blank lines; new keys are appended. Creates the file from scratch if absent.
    """
    if path.exists():
        lines: list[str] = []
        seen_keys: set[str] = set()
        for raw in path.read_text().splitlines():
            if "=" in raw and not raw.lstrip().startswith("#"):
                k, _, _ = raw.partition("=")
                k = k.strip()
                if k in overrides:
                    lines.append(f"{k}={overrides[k]}")
                    seen_keys.add(k)
                else:
                    lines.append(raw)
            else:
                lines.append(raw)
        for k, v in overrides.items():
            if k not in seen_keys:
                lines.append(f"{k}={v}")
        path.write_text("\n".join(lines) + "\n")
    else:
        path.write_text("\n".join(f"{k}={v}" for k, v in overrides.items()) + "\n")
