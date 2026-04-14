# minecraft-server-helper

A standalone Python CLI (`mc-helper`) that prepares a Minecraft server directory without Docker. It downloads server JARs, installs mod loaders (Vanilla, Fabric, Forge, NeoForge, Paper, Purpur), and fetches modpacks or mods from CurseForge or Modrinth — all driven by a single YAML config file.

## Features

- **Server types**: Vanilla, Fabric, Forge, NeoForge, Paper, Purpur
- **Modpacks**: CurseForge and Modrinth modpack installation
- **Individual mods**: Modrinth and CurseForge mod resolution by slug, ID, or version
- **Server packs**: Pre-assembled ZIP/tar.gz from direct URL or GitHub release assets
- **Idempotent**: Manifest-tracked state skips unchanged files and removes stale ones on re-run
- **Config-driven**: One YAML file covers server type, properties, mods, and output location

## Installation

Requires Python 3.11+ and [Poetry](https://python-poetry.org/).

```bash
poetry install
```

## Usage

```bash
# Validate a config file
mc-helper validate --config example-config.yaml

# Set up a server
mc-helper setup --config example-config.yaml

# Check installed state
mc-helper status --config example-config.yaml
```

## Configuration

A minimal `config.yaml`:

```yaml
server:
  type: fabric
  minecraft_version: "1.21.1"
  loader_version: LATEST
  output_dir: ./server
  eula: true
  memory: 2G
  properties:
    difficulty: normal
    max_players: 20
    motd: "A Minecraft Server"

modpack:
  platform: modrinth
  project: "better-mc-fabric"
  version: LATEST
```

See `example-config.yaml` for the full schema covering all three modes (`modpack`, `mods`, `server_pack`) and `PLAN.md` for complete design documentation.

Environment variables are interpolated using `${VAR}` syntax before validation (useful for API keys like `${CF_API_KEY}`).

## Development

```bash
poetry install

poetry run pytest                                                 # all tests
poetry run pytest tests/test_vanilla.py                           # one file
poetry run pytest tests/test_curseforge.py::test_resolve_by_slug  # one test

poetry run ruff check src/ tests/
poetry run ruff format src/ tests/
```

## License

Copyright 2026 Pat Long

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.

## Attribution

This project draws heavily on design patterns, API knowledge, and logic from the [itzg](https://github.com/itzg) Minecraft server toolchain:

- **[itzg/docker-minecraft-server](https://github.com/itzg/docker-minecraft-server)** — Reference for server deployment scripts (Vanilla, Fabric, Forge, Paper, etc.), server property definitions, CurseForge/Modrinth exclude-include rules, and modpack extraction logic. Licensed under the Apache License 2.0.

- **[itzg/mc-image-helper](https://github.com/itzg/mc-image-helper)** — Reference for CurseForge and Modrinth installer workflows, Fabric/Forge/Paper API clients, manifest tracking patterns, and version resolution logic. Licensed under the MIT License.

- **[itzg/easy-add](https://github.com/itzg/easy-add)** — Reference for ZIP and tar.gz archive extraction with `strip_components` support. Licensed under the MIT License.

- **[itzg/mc-server-runner](https://github.com/itzg/mc-server-runner)** — Reference for graceful JVM process management. Licensed under the MIT License.

This project is not affiliated with or endorsed by itzg. Minecraft is a trademark of Mojang Studios / Microsoft.
