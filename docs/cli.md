# CLI Reference

`mc-helper` is the command-line entry point for this tool.

```
mc-helper [--config <FILE>] [-v] <command> [options]
```

`--config` accepts a path to the YAML configuration file and is required for every command. It may appear before or after the subcommand name. `-v` / `--verbose` enables debug-level logging.

---

## Commands

### `setup`

Downloads and installs the server based on the config file.

```bash
mc-helper setup --config config.yaml
```

**Options:**

| Flag | Description |
|---|---|
| `--output-dir DIR` | Override `server.output_dir` from the config. |
| `--dry-run` | Print what would be done without downloading or writing any files. |

**What it does (in order):**

1. Validates the config.
2. Dispatches to the appropriate installer:
   - `modpack` → downloads and installs the modpack (Modrinth, CurseForge, FTB, GTNH) or extracts a pre-assembled server pack (GitHub, URL).
   - `mods` → installs individual mods in parallel, then installs the server JAR.
   - *(none)* → installs the server JAR only.
3. Writes `eula.txt`, `server.properties`, and `launch.sh` into `output_dir`.

Re-running `setup` is safe. The manifest tracks installed files; unchanged files are skipped and stale files are removed.

---

### `validate`

Validates the config file without downloading anything.

```bash
mc-helper validate --config config.yaml
```

Exits 0 on success, exits 1 with an error message if the config is invalid.

---

### `status`

Reads the manifest in `server.output_dir` and displays the installed state.

```bash
mc-helper status --config config.yaml
```

Example output:

```
Manifest: ./server/.mc-helper-manifest.json
  Minecraft version : 1.21.1
  Loader            : fabric
  Loader version    : 0.16.9
  Tracked files     : 12
    mods/fabric-api-0.119.2+1.21.4.jar
    mods/sodium-mc1.21.1-0.6.0.jar
    ...
```

Prints a message and exits 0 if no manifest exists yet.

---

## Generated files

After a successful `setup` run, the following files are written into `output_dir`:

| File | Contents |
|---|---|
| `eula.txt` | `eula=true` or `eula=false` from `server.eula`. |
| `server.properties` | Written or merged from the `properties` map. Omitted (and any existing file left untouched) if the map is empty. When the file already exists, only the configured keys are updated; all other entries are preserved. |
| `launch.sh` | Executable shell script that launches the server with the configured memory. |
| `.mc-helper-manifest.json` | Internal state file used for idempotent re-runs. |

### `launch.sh` contents

For most server types, the generated script is:

```sh
#!/bin/sh
exec java -Xmx2G -Xms2G -jar minecraft_server.1.21.1.jar nogui "$@"
```

For Forge and NeoForge (which generate their own `run.sh` during installation):

```sh
#!/bin/sh
exec ./run.sh "$@"
```

---

## Environment variable interpolation

Any `${VAR}` reference in the config is replaced with the corresponding environment variable before the config is validated. This is useful for secrets:

```yaml
modpack:
  platform: curseforge
  api_key: ${CF_API_KEY}
```

If the referenced variable is not set, `mc-helper` exits with an error.
