# Configuration Reference

All behavior is driven by a single YAML config file. Pass it to every command with `--config <file>`.

A config file has one required section (`server`) and optional install sections. `modpack` and `server_pack` are mutually exclusive base install modes. `mods` may appear alone **or** alongside `modpack`/`server_pack` to add extra mods on top of the base install. Setting both `modpack` and `server_pack` is an error.

---

## `server`

Controls the server type, Minecraft version, output location, and runtime settings.

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
    max-players: 20
    motd: "A Minecraft Server"
    online-mode: true
```

| Field | Type | Default | Description |
|---|---|---|---|
| `type` | string | *(required)* | Server type. One of `vanilla`, `fabric`, `forge`, `neoforge`, `paper`, `purpur`. |
| `minecraft_version` | string | `LATEST` | Minecraft version, e.g. `1.21.1`, `LATEST`, or `SNAPSHOT`. Not used when `modpack` or `server_pack` is set — the version comes from the pack. |
| `loader_version` | string | `LATEST` | Loader version for `fabric`, `forge`, or `neoforge`. Ignored for `vanilla`, `paper`, `purpur`. |
| `output_dir` | path | `./server` | Directory where server files are installed. Created if it does not exist. |
| `eula` | bool | `false` | Set to `true` to agree to the Minecraft EULA. Written to `eula.txt`. |
| `memory` | string | `1G` | JVM heap size, e.g. `2G`, `512M`. Used in the generated `launch.sh`. |
| `properties` | map | `{}` | Written verbatim to `server.properties`. Keys are the standard Minecraft property names (e.g. `difficulty`, `max-players`, `motd`). |

`properties` keys map directly to `server.properties` entries. See the [Minecraft wiki](https://minecraft.wiki/w/Server.properties) for all valid keys; the canonical machine-readable mapping is `docker-minecraft-server/files/property-definitions.json` in the parent repository.

---

## Install modes

The valid combinations are:

| Config | Behaviour |
|---|---|
| *(none)* | Server JAR only (vanilla/loader-only). |
| `modpack` | Full modpack install (mods + overrides + server JAR). |
| `server_pack` | Extract pre-assembled archive into `output_dir`. |
| `mods` | Individual mods + server JAR. |
| `modpack` + `mods` | Modpack install, then extra mods layered on top. |
| `server_pack` + `mods` | Server pack extract, then extra mods layered on top. |

`modpack` and `server_pack` cannot be set at the same time.

---

## `modpack`

Installs a modpack from Modrinth, CurseForge, or FTB (Feed The Beast), including all mods, overrides, and the embedded server JAR.

```yaml
modpack:
  platform: modrinth       # modrinth | curseforge | ftb
  project: "better-mc-fabric"
  version: LATEST
  version_type: release
```

### Modrinth fields

| Field | Type | Default | Description |
|---|---|---|---|
| `platform` | string | *(required)* | Must be `modrinth`. |
| `project` | string | *(required)* | Project slug, ID, or page URL. |
| `version` | string | `LATEST` | Version ID or `LATEST`. |
| `version_type` | string | `release` | Minimum acceptable stability: `release`, `beta`, or `alpha`. |

### CurseForge fields

| Field | Type | Default | Description |
|---|---|---|---|
| `platform` | string | *(required)* | Must be `curseforge`. |
| `api_key` | string | *(required)* | CurseForge API key. Use `${CF_API_KEY}` to read from the environment. |
| `slug` | string | `null` | Project slug, e.g. `all-the-mods-9`. |
| `file_id` | int | `null` | Specific file ID. Null selects the newest matching file. |
| `filename_matcher` | string | `null` | Optional substring that the filename must contain. |

Either `slug` or `file_id` is required for CurseForge.

### FTB fields

| Field | Type | Default | Description |
|---|---|---|---|
| `platform` | string | *(required)* | Must be `ftb`. |
| `pack_id` | int | *(required)* | Numeric FTB pack ID (visible in the pack URL on https://feed-the-beast.com). |
| `version_id` | int | `null` | Specific version ID. Null picks the latest version matching `version_type`. |
| `api_key` | string | `public` | API key for private packs. Use `${FTB_API_KEY}` to read from the environment. |
| `version_type` | string | `release` | Preferred release stability when `version_id` is not set: `release`, `beta`, or `alpha`. |

FTB packs are downloaded directly from the FTB CDN. Files with `clientonly: true` are automatically skipped. The modloader (Forge, NeoForge, Fabric, etc.) is read from the pack metadata and installed by `mc-helper` after the pack files are downloaded — no manual `server.type` coordination is required beyond ensuring the type matches the pack's loader.

### Shared fields

| Field | Type | Default | Description |
|---|---|---|---|
| `exclude_mods` | list[string] | `[]` | Glob patterns matched against filenames; matching files are skipped. For CurseForge, matched against project IDs. |
| `force_include_mods` | list[string] | `[]` | Slugs or IDs to always include even if they would otherwise be filtered. (CurseForge only.) |
| `overrides_exclusions` | list[string] | `[]` | Paths inside the `overrides/` directory to skip during extraction. (Modrinth and CurseForge only.) |

---

## `mods`

Installs individual mods from Modrinth, CurseForge, or direct URLs, then installs the server JAR separately.

```yaml
mods:
  modrinth:
    - fabric-api
    - "sodium:mc1.21-0.6.0"
    - "P7dR8mSH"
  curseforge:
    api_key: ${CF_API_KEY}
    files:
      - jei
      - "jei:4593548"
      - "238222"
  urls:
    - https://example.com/mymod-1.0.jar
```

At least one of `modrinth`, `curseforge`, or `urls` must be non-empty.

### `mods.modrinth`

A list of mod specs. Supported formats:

| Format | Example | Description |
|---|---|---|
| Slug | `fabric-api` | Latest release for the configured `minecraft_version` and `type` (loader). |
| Slug + version | `sodium:mc1.21-0.6.0` | Specific version string. |
| Project ID | `P7dR8mSH` | Resolved by project ID instead of slug. |

### `mods.curseforge`

| Field | Type | Description |
|---|---|---|
| `api_key` | string | CurseForge API key. Use `${CF_API_KEY}`. |
| `files` | list[string] | List of mod specs (see formats below). |

CurseForge mod spec formats:

| Format | Example | Description |
|---|---|---|
| Slug | `jei` | Latest file for the configured Minecraft version. |
| Slug + file ID | `jei:4593548` | Specific file ID. |
| Project ID | `238222` | Resolved by numeric project ID. |

### `mods.urls`

A list of direct download URLs. The filename is taken from the last path segment. Files are placed in `<output_dir>/mods/`.

Mod downloads from Modrinth and CurseForge run in parallel (up to 10 concurrent workers).

### Using `mods` with `modpack` or `server_pack`

When `mods` is combined with `modpack` or `server_pack`, the base pack installs first and then the extra mods are downloaded into `<output_dir>/mods/`. The Minecraft version and loader are read from the manifest written by the base installer — `server.minecraft_version` is not used.

```yaml
server:
  type: fabric
  output_dir: ./server
  eula: true

modpack:
  platform: modrinth
  project: "better-mc-fabric"

mods:
  modrinth:
    - iris
    - bobby
  urls:
    - https://example.com/custom-mod-1.0.jar
```

On re-run: the modpack installer's stale-file cleanup removes the extra mods (they are tracked in the manifest from the previous run but are not part of the pack itself). They are immediately re-downloaded by the extra-mods step and appended to the manifest again.

---

## `server_pack`

Extracts a pre-assembled server archive (ZIP or tar.gz) into `output_dir`. The archive can come from a direct URL or a GitHub release asset.

```yaml
server_pack:
  github: "ATM-Team/ATM-10"
  tag: LATEST
  asset: "*server*"
  strip_components: 1
  disable_mods:
    - "OptiFine*.jar"
  force_update: false
```

Exactly one of `url` or `github` must be set.

### Source: direct URL

```yaml
server_pack:
  url: https://example.com/mypack-server.zip
```

| Field | Type | Description |
|---|---|---|
| `url` | string | Direct download URL for a ZIP or tar.gz archive. |

### Source: GitHub release

```yaml
server_pack:
  github: "owner/repo"
  tag: LATEST
  asset: "*server*"
  token: ${GITHUB_TOKEN}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `github` | string | *(required)* | Repository in `owner/repo` format. |
| `tag` | string | `LATEST` | Release tag, or `LATEST` to use the most recent release. |
| `asset` | string | `null` | Glob pattern to match the asset filename. Selects the first match; if omitted, the first asset is used. |
| `token` | string | `null` | GitHub personal access token. Required for private repositories. |

### Shared options

| Field | Type | Default | Description |
|---|---|---|---|
| `strip_components` | int | `0` | Strip N leading path segments from archive entries during extraction (equivalent to `tar --strip-components=N`). |
| `disable_mods` | list[string] | `[]` | Glob patterns; matching filenames inside `mods/` are renamed to `<name>.disabled` after extraction. |
| `force_update` | bool | `false` | Re-extract even if the archive's SHA-1 matches the previously recorded checksum. |

### Idempotency

The SHA-1 of the downloaded archive is stored in the manifest. On re-run, if the checksum matches and `force_update` is `false`, extraction is skipped entirely.

---

## Environment variable interpolation

Any `${VAR}` reference in the YAML is replaced with the value of the named environment variable before the config is parsed. This substitution happens on all string values, including nested ones.

```yaml
modpack:
  api_key: ${CF_API_KEY}
  token: ${GITHUB_TOKEN}
```

If a referenced variable is not set, `mc-helper` exits immediately with an error listing the missing variable name.

---

## Full example

See [`example-config.yaml`](../example-config.yaml) in the project root for an annotated file covering all three install modes.
