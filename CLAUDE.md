# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

`minecraft-server-helper` is a Python CLI (`mc-helper`) that prepares a Minecraft server directory without Docker. It downloads server JARs, installs mod loaders, and fetches modpacks/mods from CurseForge or Modrinth — driven by a single YAML config file.

See `docs/` for user-facing reference documentation.

## Setup

```bash
poetry install
```

## Common Commands

```bash
# Run all tests
poetry run pytest

# Run a single test file
poetry run pytest tests/test_vanilla.py

# Run a single test
poetry run pytest tests/test_curseforge.py::test_resolve_by_slug

# Lint + format
poetry run ruff check src/ tests/
poetry run ruff format src/ tests/

# Validate a config file
poetry run mc-helper validate --config example-config.yaml

# Dry-run setup (no downloads)
poetry run mc-helper setup --config example-config.yaml --dry-run
```

## Architecture

### CLI dispatch (`cli.py`)

The entry point uses `argparse` (not Click). `_cmd_setup` runs the base install mode first, then optionally installs extra mods:

1. `server_pack` → `_setup_server_pack()` → `pack/server_pack.py`
2. `modpack` → `_setup_modpack()` → `modpack/curseforge.py`, `modpack/modrinth.py`, or `modpack/ftb.py`
3. `mods` only → `_setup_mods()` → `_download_mods()` (parallel), then `_install_server_jar()`
4. *(none)* → `_install_server_jar()` only
5. If `mods` is set alongside `server_pack` or `modpack` → `_install_extra_mods()` runs after the base step

`_download_mods()` is a shared helper used by both `_setup_mods()` and `_install_extra_mods()`. After install, `_write_server_files()` always writes `eula.txt`, `server.properties`, and `launch.sh`. Modpack installers handle server JAR installation themselves (embedded in pack metadata); `_install_server_jar()` is only called explicitly for the `mods` and bare-server cases.

### Config (`config.py`)

Pydantic v2 models. YAML is loaded → `${VAR}` env interpolation runs on all string values → `model_validate()`. A `RootConfig` model validator forbids `modpack + server_pack` together; `mods` may be combined with either. The `server.properties` map keys are written verbatim as `server.properties` entries.

### Manifest (`manifest.py`)

`.mc-helper-manifest.json` in `output_dir` tracks `mc_version`, `loader_type`, `loader_version`, `pack_sha1`, and `files: list[str]`. On re-run: stale files (in manifest but not in new list) are deleted; the manifest is rewritten. For `server_pack`, the SHA-1 of the archive is stored; extraction is skipped if it matches and `force_update` is false.

### HTTP (`http_client.py`)

`build_session()` returns a `requests.Session` with 5-attempt exponential backoff (retries on 429/500/502/503/504). `download_file()` streams to disk with a tqdm progress bar and optional SHA-1/SHA-256 verification; the partial file is deleted if verification fails.

### Server installers (`server/`)

Each module exposes an installer class (`VanillaInstaller`, `FabricInstaller`, `ForgeInstaller`, `NeoForgeInstaller`, `PaperInstaller`, `PurpurInstaller`). The constructor takes version and session params; `install(output_dir)` downloads and installs the server. Vanilla, Fabric, Paper, Purpur return the installed JAR `Path`. Forge and NeoForge run `java -jar <installer>.jar --installServer` as a subprocess and return `None` (the installer creates its own `run.sh`).

### Parallelism

`_download_mods()` submits all Modrinth and CurseForge mod downloads to a `ThreadPoolExecutor(max_workers=10)`. Errors are collected per-mod; all are reported before exiting non-zero if any failed. This helper is called by both `_setup_mods()` (mods-only path) and `_install_extra_mods()` (overlay path).

## Reference Sources (in parent repo)

| Topic | Reference |
|---|---|
| Vanilla install | `../docker-minecraft-server/scripts/start-deployVanilla` |
| Fabric install | `../mc-image-helper/src/main/java/me/itzg/helpers/fabric/` |
| Forge install | `../mc-image-helper/src/main/java/me/itzg/helpers/forge/` |
| Paper install | `../mc-image-helper/src/main/java/me/itzg/helpers/paper/` |
| CurseForge modpack | `../mc-image-helper/src/main/java/me/itzg/helpers/curseforge/` |
| Modrinth modpack | `../mc-image-helper/src/main/java/me/itzg/helpers/modrinth/` |
| FTB modpack | `../FTB-Server-Installer/` |
| Server pack extract | `../docker-minecraft-server/scripts/start-setupModpack` |
| Server properties | `../docker-minecraft-server/files/property-definitions.json` |
| Mod filter rules | `../docker-minecraft-server/files/cf-exclude-include.json` |
