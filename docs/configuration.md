# Configuration Reference

All behavior is driven by a single YAML config file. Pass it to every command with `--config <file>`.

A config file has one required section (`server`) and exactly one optional section from the three install modes: `modpack`, `mods`, or `server_pack`. Setting more than one of these is an error.

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
| `minecraft_version` | string | `LATEST` | Minecraft version, e.g. `1.21.1`, `LATEST`, or `SNAPSHOT`. |
| `loader_version` | string | `LATEST` | Loader version for `fabric`, `forge`, or `neoforge`. Ignored for `vanilla`, `paper`, `purpur`. |
| `output_dir` | path | `./server` | Directory where server files are installed. Created if it does not exist. |
| `eula` | bool | `false` | Set to `true` to agree to the Minecraft EULA. Written to `eula.txt`. |
| `memory` | string | `1G` | JVM heap size, e.g. `2G`, `512M`. Used in the generated `launch.sh`. |
| `properties` | map | `{}` | Written verbatim to `server.properties`. Keys are the standard Minecraft property names (e.g. `difficulty`, `max-players`, `motd`). |

`properties` keys map directly to `server.properties` entries. See the [Minecraft wiki](https://minecraft.wiki/w/Server.properties) for all valid keys; the canonical machine-readable mapping is `docker-minecraft-server/files/property-definitions.json` in the parent repository.

---

## Install modes

Exactly one of `modpack`, `mods`, or `server_pack` must be present. If none are present, only the server JAR is installed (vanilla/loader-only mode).

---

## `modpack`

Installs a modpack from Modrinth or CurseForge, including all mods, overrides, and the embedded server JAR.

```yaml
modpack:
  platform: modrinth       # modrinth | curseforge
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

### Shared fields

| Field | Type | Default | Description |
|---|---|---|---|
| `exclude_mods` | list[string] | `[]` | Slugs or IDs of mods to skip (e.g. client-only mods). |
| `force_include_mods` | list[string] | `[]` | Slugs or IDs to always include even if they would otherwise be filtered. |
| `overrides_exclusions` | list[string] | `[]` | Paths inside the `overrides/` directory to skip during extraction. |

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
