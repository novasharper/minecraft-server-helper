# minecraft-server-helper — Implementation Plan

## Context

This Python tool provides a standalone, YAML-driven CLI to prepare a Minecraft server directory without Docker — downloading server JARs, installing mod loaders, and fetching modpacks/mods from CurseForge or Modrinth. It targets four scenarios: vanilla server, modpack-based server, custom mod list, and pre-assembled server pack.

---

## Project Layout

```
minecraft-server-helper/
├── pyproject.toml
├── PLAN.md                     (this file)
├── TODO.md
├── example-config.yaml
├── src/
│   └── mc_helper/
│       ├── __init__.py
│       ├── cli.py              # Click entry point: setup, validate, status
│       ├── config.py           # Pydantic v2 models + YAML loader
│       ├── http_client.py      # requests.Session with retry + User-Agent
│       ├── manifest.py         # JSON state tracking (.mc-helper-manifest.json)
│       ├── utils.py            # version comparison, glob cleanup, env interpolation
│       ├── server/
│       │   ├── vanilla.py
│       │   ├── fabric.py
│       │   ├── forge.py
│       │   ├── neoforge.py
│       │   ├── paper.py
│       │   └── purpur.py
│       ├── modpack/
│       │   ├── curseforge.py
│       │   └── modrinth.py
│       ├── pack/
│       │   └── server_pack.py  # pre-assembled server pack (GitHub or direct URL)
│       └── mods/
│           ├── curseforge.py
│           └── modrinth.py
└── tests/
    ├── test_config.py
    ├── test_manifest.py
    ├── test_vanilla.py
    ├── test_curseforge.py
    ├── test_modrinth.py
    └── test_server_pack.py
```

---

## YAML Configuration Schema

```yaml
server:
  type: fabric            # vanilla | forge | neoforge | fabric | quilt | paper | purpur
  minecraft_version: "1.21.1"   # or LATEST or SNAPSHOT
  loader_version: LATEST        # fabric/forge/neoforge/quilt; ignored for vanilla/paper/purpur
  output_dir: ./server
  eula: true
  memory: 2G
  properties:                   # written to server.properties
    difficulty: normal          # keys mirror docker-minecraft-server/files/property-definitions.json
    max_players: 20
    motd: "A Minecraft Server"
    online_mode: true

# Exactly ONE of modpack / mods / server_pack must be present.

modpack:
  platform: modrinth            # modrinth | curseforge
  # Modrinth
  project: "better-mc-fabric"   # slug, ID, page URL, or local .mrpack path
  version: LATEST
  version_type: release         # release | beta | alpha
  # CurseForge
  api_key: ${CF_API_KEY}
  slug: "all-the-mods-9"
  file_id: ~                    # null = newest
  filename_matcher: ~
  # Shared
  exclude_mods: []
  force_include_mods: []
  overrides_exclusions: []

mods:
  modrinth:
    - fabric-api                # slug → latest release
    - "sodium:mc1.21-0.6.0"    # slug:version
    - "P7dR8mSH"               # project ID
  curseforge:
    api_key: ${CF_API_KEY}
    files:
      - jei
      - "jei:4593548"
      - "238222"
  urls:
    - https://example.com/mymod-1.0.jar

server_pack:
  # Option A: direct URL
  url: https://example.com/mypack-server.zip
  # Option B: GitHub release asset
  github: "ATM-Team/ATM-10"    # owner/repo
  tag: LATEST                  # specific tag or LATEST
  asset: "*server*"            # glob to select asset; picks first if omitted
  token: ${GITHUB_TOKEN}       # optional, for private repos
  # Shared
  strip_components: 1          # strip N leading path segments (like tar --strip-components)
  disable_mods: []             # rename matched filenames to *.disabled after extraction
  force_update: false          # re-extract even if checksum matches
```

---

## Module Design

### `config.py`
Pydantic v2 models. YAML loader resolves `${VAR}` before validation. `RootConfig` model validator enforces exactly one of `modpack` / `mods` / `server_pack`.

### `http_client.py`
`requests.Session` with `urllib3.util.retry.Retry` (5 attempts, exponential backoff). Mirrors `--retry-count 5` default in `mc-image-helper/src/main/java/me/itzg/helpers/get/GetCommand.java`. `download_file(url, dest)` with tqdm progress bar.

### `manifest.py`
JSON at `<output_dir>/.mc-helper-manifest.json`. Tracks `timestamp`, `mc_version`, `loader_type`, `loader_version`, `files: list[str]`. Mirrors pattern from `mc-image-helper/src/main/java/me/itzg/helpers/*/` manifests (e.g., `CurseForgeManifest.java`, `ModrinthManifest.java`). On re-run: load, diff, download only changed, delete stale.

---

## Server Installers

### `server/vanilla.py`
Reference: `docker-minecraft-server/scripts/start-deployVanilla`

1. GET `https://launchermeta.mojang.com/mc/game/version_manifest.json`
2. Resolve `LATEST`/`SNAPSHOT`/specific from `versions[]`
3. GET version manifest → extract `downloads.server.url` + `sha1`
4. Download to `<output_dir>/minecraft_server.<version>.jar`, verify SHA-1

### `server/fabric.py`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/fabric/FabricMetaClient.java`
Reference: `docker-minecraft-server/scripts/start-deployFabric`

API base: `https://meta.fabricmc.net`
- GET `/v2/versions/installer` and `/v2/versions/loader` to resolve versions
- Download `/v2/versions/loader/<mc>/<loader>/<installer>/server/jar`

### `server/forge.py` / `server/neoforge.py`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/forge/ForgeLikeInstaller.java`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/forge/ForgeInstallerResolver.java`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/forge/NeoForgeInstallerResolver.java`
Reference: `docker-minecraft-server/scripts/start-deployForge`

1. Resolve installer JAR URL from Forge/NeoForge Maven
2. Download installer, run `java -jar forge-installer.jar --installServer` (subprocess)
3. Parse stdout for server entry path (mirrors `ForgeLikeInstaller.java` output parsing)

### `server/paper.py`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/paper/PaperDownloadsClient.java`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/paper/InstallPaperCommand.java`

API base: `https://fill.papermc.io`
- GET `/v3/projects/paper/versions/<mc>/builds/<build>` → download + SHA-256 verify

### `server/purpur.py`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/purpur/PurpurDownloadsClient.java`

API base: `https://api.purpurmc.org`
- GET `/v2/purpur/<mc_version>/<build>/download`

---

## Modpack Installers

### `modpack/curseforge.py`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/curseforge/CurseForgeInstaller.java`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/curseforge/CurseForgeApiClient.java`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/curseforge/InstallCurseForgeCommand.java`
Reference: `docker-minecraft-server/files/cf-exclude-include.json` (exclude/include schema)
Reference: `docker-minecraft-server/scripts/start-deployAutoCF`

API base: `https://api.curseforge.com` (requires `X-Api-Key`)

Workflow:
1. Load manifest; resolve modpack via `/v1/mods/search?gameId=432&slug=<slug>`
2. Download modpack ZIP → parse `manifest.json` (versions, mod file refs)
3. For each file: GET `/v1/mods/<projectId>/files/<fileId>` → download to `mods/`
4. Apply exclude/force-include lists; skip client-only mods
5. Extract `overrides/`, auto-install mod loader, cleanup stale, save manifest

### `modpack/modrinth.py`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/modrinth/ModrinthPackInstaller.java`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/modrinth/ModrinthApiClient.java`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/modrinth/ModpackIndex.java` (modrinth.index.json schema)
Reference: `docker-minecraft-server/files/modrinth-exclude-include.json`
Reference: `docker-minecraft-server/scripts/start-deployModrinth`

API base: `https://api.modrinth.com/v2`

Workflow:
1. Resolve project via `/v2/project/<id>/versions`; download `.mrpack`
2. Parse `modrinth.index.json`: `dependencies{}` (loader type/version), `files[]` with `env.server`
3. Skip `env.server == "unsupported"`; download files to `<output_dir>/<path>`
4. Extract `overrides/` + `server-overrides/`, auto-install loader, cleanup stale, save manifest

---

## Server Pack Installer (`pack/server_pack.py`)

A pre-assembled ZIP/tar.gz containing a complete server directory. Two source types:

### GitHub resolution
Reference: `mc-image-helper` `github` subcommand family in `McImageHelper.java`

- GET `https://api.github.com/repos/{owner}/{repo}/releases/latest` (or `/releases/tags/{tag}`)
- Match `assets[].name` against `asset` glob pattern → download `browser_download_url`
- Pass `Authorization: Bearer <token>` if `token` provided

### Archive extraction
Reference: `easy-add/main.go` `processTarGz` / `processZip`

- Detect format from filename: `.zip` → `zipfile`, `.tar.gz`/`.tgz` → `tarfile`
- Apply `strip_components`: skip N leading path segments per entry during extraction
- After extraction, auto-detect content root: find shallowest directory containing `mods/`, `plugins/`, `config/`, or `*.jar`
  - Mirrors `mc-image-helper find --only-shallowest` call in `docker-minecraft-server/scripts/start-setupModpack` lines 213–220
- Copy resolved content root into `output_dir`

### Checksum + idempotency
Reference: `docker-minecraft-server/scripts/start-setupModpack` lines 189–243 (`checkSum` / `sha1sum`)

- Compute SHA-1 of downloaded archive; store in manifest
- On re-run: skip extraction if SHA-1 matches and `force_update` is false

### `disable_mods`
Reference: `docker-minecraft-server/scripts/start-setupModpack` lines 204–207 (`GENERIC_PACKS_DISABLE_MODS`)

- After extraction, rename files matching any `disable_mods` entry to `<name>.disabled`

---

## Individual Mod Installers

### `mods/modrinth.py`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/modrinth/` (version resolution)
Reference: `docker-minecraft-server/docs/variables.md` (`MODRINTH_PROJECTS` formats)

Formats: `fabric-api`, `fabric-api:0.119.2+1.21.4`, `P7dR8mSH`
- GET `/v2/project/<id>/versions?game_versions=[<mc>]&loaders=[<loader>]`
- Pick by version_type preference (release > beta > alpha)

### `mods/curseforge.py`
Reference: `mc-image-helper/src/main/java/me/itzg/helpers/curseforge/CurseForgeApiClient.java`
Reference: `docker-minecraft-server/docs/variables.md` (`CURSEFORGE_FILES` formats)

Formats: `jei`, `jei:4593548`, `238222`, full page URL

---

## CLI (`cli.py`)

Framework: Click

```
mc-helper setup    --config <yaml>  [--output-dir DIR]  [--dry-run]
mc-helper validate --config <yaml>
mc-helper status   --config <yaml>
```

`setup` dispatch:
1. Load + validate config
2. `if server_pack` → `pack/server_pack.py`
3. `elif modpack` → `modpack/curseforge.py` or `modpack/modrinth.py` (mod loader installed by modpack installer)
4. `elif mods` → individual installers in parallel (ThreadPoolExecutor, max 10) + install server JAR
5. `else` → install server JAR only (vanilla)
6. Write `server.properties`, `eula.txt`, `launch.sh`

---

## `pyproject.toml`

Managed by [Poetry](https://python-poetry.org/). Dependencies declared in `[tool.poetry.dependencies]` with pinned upper bounds.

```toml
[tool.poetry]
name = "mc-helper"
version = "0.1.0"
packages = [{include = "mc_helper", from = "src"}]

[tool.poetry.dependencies]
python = "^3.11"
pydantic = "^2.9"
PyYAML = "^6.0"
requests = "^2.32"
tqdm = "^4.66"

[tool.poetry.group.dev.dependencies]
pytest = "^8.3"
pytest-mock = "^3.14"
responses = "^0.25"
ruff = "^0.7"

[tool.poetry.scripts]
mc-helper = "mc_helper.cli:main"
```

---

## Build / Test / Lint

```bash
cd minecraft-server-helper
poetry install

poetry run pytest                                                   # all tests
poetry run pytest tests/test_server_pack.py                         # one file
poetry run pytest tests/test_curseforge.py::test_resolve_by_slug    # one test

poetry run ruff check src/ tests/
poetry run ruff format src/ tests/
```

---

## Verification

1. `mc-helper validate --config example-config.yaml`
2. Vanilla: `type: vanilla, minecraft_version: 1.21.1` → verify JAR + `eula.txt`
3. Fabric: `type: fabric` → verify `fabric-server-launch.jar`
4. Modrinth modpack: small pack (e.g. `adrenaline`) → `mods/` populated, overrides applied, manifest written
5. CurseForge modpack: requires `CF_API_KEY`
6. Individual mods: `mods.modrinth: [fabric-api]` → JAR in `mods/`
7. Server pack (direct URL): ZIP extracted, content root detected, files in `output_dir`
8. Server pack (GitHub): asset resolved by glob, downloaded, extracted
9. Idempotency: second `setup` run skips unchanged files
10. Stale cleanup: remove entry from config → old file deleted on next run
