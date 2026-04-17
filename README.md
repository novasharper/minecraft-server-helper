# minecraft-server-helper

A standalone Python CLI (`mc-helper`) that prepares a Minecraft server directory without Docker. It downloads server JARs, installs mod loaders (Vanilla, Fabric, Forge, NeoForge, Paper, Purpur), and fetches modpacks or mods from CurseForge, Modrinth, or FTB — all driven by a single YAML config file.

## Features

- **Seven server types**: Vanilla, Fabric, Forge, NeoForge, Paper, Purpur
- **Modpacks**: CurseForge, Modrinth, and FTB modpack installation with override extraction
- **Individual mods**: Modrinth and CurseForge mod resolution by slug, ID, or version; parallel downloads
- **Server packs**: Pre-assembled ZIP/tar.gz/tar.bz2 from direct URL or GitHub release asset
- **Idempotent**: Manifest-tracked state skips unchanged files and removes stale ones on re-run
- **Config-driven**: One YAML file covers server type, properties, mods, and output location
- **Dry-run mode**: Preview all actions without downloading or writing anything

## Installation

Requires Python 3.11+ and [Poetry](https://python-poetry.org/).

```bash
poetry install
```

## Quick start

```bash
# 1. Write a config file (see Configuration below)
# 2. Validate it
mc-helper validate --config config.yaml

# 3. Set up the server
mc-helper setup --config config.yaml

# 4. Check installed state
mc-helper status --config config.yaml
```

After a successful `setup` run, `output_dir` contains the server JAR (or extracted server pack), `eula.txt`, `server.properties`, and an executable `launch.sh`.

## Commands

| Command | Description |
|---|---|
| `setup --config FILE` | Download and install everything. |
| `setup --config FILE --dry-run` | Print what would be done without downloading anything. |
| `setup --config FILE --output-dir DIR` | Override `server.output_dir` from the config. |
| `validate --config FILE` | Validate the config file and exit. |
| `status --config FILE` | Show the installed state from the manifest. |

## Configuration

A config file has one required `server` section and one or more optional install sections. `modpack` and `server_pack` are mutually exclusive base install modes; `mods` may be combined with either to add extra mods on top. Omitting all three installs only the server JAR.

### Minimal example — Modrinth modpack

```yaml
server:
  type: fabric
  minecraft_version: "1.21.1"
  output_dir: ./server
  eula: true
  memory: 2G
  properties:
    difficulty: normal
    max-players: 20
    motd: "My Server"

modpack:
  platform: modrinth
  project: "better-mc-fabric"
  version: LATEST
```

### Minimal example — FTB modpack

```yaml
server:
  type: neoforge
  minecraft_version: "1.21.1"
  output_dir: ./server
  eula: true

modpack:
  platform: ftb
  pack_id: 7
  version_type: release   # release | beta | alpha; omit version_id to use latest
```

### Minimal example — individual mods

```yaml
server:
  type: fabric
  minecraft_version: "1.21.1"
  output_dir: ./server
  eula: true

mods:
  modrinth:
    - fabric-api
    - "sodium:mc1.21-0.6.0"
  curseforge:
    api_key: ${CF_API_KEY}
    files:
      - jei
```

### Minimal example — server pack

```yaml
server:
  type: fabric
  minecraft_version: "1.21.1"
  output_dir: ./server
  eula: true

server_pack:
  github: "ATM-Team/ATM-10"
  tag: LATEST
  asset: "*server*"
```

### Adding extra mods to a modpack or server pack

`mods` can be combined with `modpack` or `server_pack` to layer additional mods on top of the base install:

```yaml
server:
  type: fabric
  minecraft_version: "1.21.1"
  output_dir: ./server
  eula: true

modpack:
  platform: modrinth
  project: "better-mc-fabric"

mods:
  modrinth:
    - iris
    - bobby
```

The base pack installs first, then the extra mods are downloaded into `<output_dir>/mods/`. On re-run the extra mods are always re-installed after the pack (the pack's cleanup removes them; they are re-downloaded immediately after).

See [`example-config.yaml`](example-config.yaml) for the full annotated schema covering every field and option. Full reference documentation is in [`docs/`](docs/):

- [`docs/configuration.md`](docs/configuration.md) — complete field reference for all sections
- [`docs/cli.md`](docs/cli.md) — command reference and generated file descriptions
- [`docs/server-types.md`](docs/server-types.md) — per-type version resolution and installation details
- [`docs/how-it-works.md`](docs/how-it-works.md) — manifest tracking, HTTP behaviour, archive extraction

### Environment variable interpolation

Any `${VAR}` in the config is replaced with the environment variable value before parsing. Useful for API keys:

```yaml
modpack:
  api_key: ${CF_API_KEY}
```

## Development

```bash
poetry install

poetry run pytest                                                   # all unit tests
poetry run pytest tests/test_vanilla.py                             # one file
poetry run pytest tests/test_curseforge.py::test_resolve_by_slug    # one test

# End-to-end tests (requires podman or docker; makes real network requests)
bash tests/e2e/run_tests.sh

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
