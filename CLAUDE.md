# CLAUDE.md

This file provides guidance to Claude Code when working in this directory.

## What This Is

`minecraft-server-helper` is a Python CLI (`mc-helper`) that prepares a Minecraft server directory without Docker. It downloads server JARs, installs mod loaders, and fetches modpacks/mods from CurseForge or Modrinth — driven by a single YAML config file.

See `PLAN.md` for full design details and `TODO.md` for implementation status.

## Project Layout

```
minecraft-server-helper/
├── pyproject.toml
├── example-config.yaml
├── src/
│   └── mc_helper/
│       ├── cli.py              # Click entry point: setup, validate, status
│       ├── config.py           # Pydantic v2 models + YAML loader
│       ├── http_client.py      # requests.Session with retry + tqdm progress
│       ├── manifest.py         # JSON state tracking (.mc-helper-manifest.json)
│       ├── utils.py            # version comparison, glob cleanup, env interpolation
│       ├── server/             # vanilla, fabric, forge, neoforge, paper, purpur
│       ├── modpack/            # curseforge, modrinth
│       ├── pack/               # server_pack (pre-assembled ZIP/tar.gz)
│       └── mods/               # individual mod installers
└── tests/
```

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

# Set up a server
poetry run mc-helper setup --config example-config.yaml
```

## Key Design Decisions

- **Config**: Pydantic v2 models; `${VAR}` env interpolation before validation; exactly one of `modpack` / `mods` / `server_pack` must be present.
- **HTTP**: `requests.Session` with 5-attempt exponential backoff; `download_file()` shows tqdm progress.
- **Manifest**: `.mc-helper-manifest.json` in `output_dir` tracks installed files; re-runs skip unchanged, delete stale.
- **Parallelism**: Individual mod downloads use `ThreadPoolExecutor` (max 10 workers).
- **Server pack**: SHA-1 checksum stored in manifest; skips re-extraction if unchanged and `force_update` is false.

## Reference Sources (in parent repo)

| Topic | Reference |
|---|---|
| Vanilla install | `../docker-minecraft-server/scripts/start-deployVanilla` |
| Fabric install | `../mc-image-helper/src/main/java/me/itzg/helpers/fabric/` |
| Forge install | `../mc-image-helper/src/main/java/me/itzg/helpers/forge/` |
| Paper install | `../mc-image-helper/src/main/java/me/itzg/helpers/paper/` |
| CurseForge modpack | `../mc-image-helper/src/main/java/me/itzg/helpers/curseforge/` |
| Modrinth modpack | `../mc-image-helper/src/main/java/me/itzg/helpers/modrinth/` |
| Server pack extract | `../docker-minecraft-server/scripts/start-setupModpack` |
| Server properties | `../docker-minecraft-server/files/property-definitions.json` |
| Mod filter rules | `../docker-minecraft-server/files/cf-exclude-include.json` |
