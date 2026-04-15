import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mc_helper.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mc-helper",
        description="Download and configure a Minecraft server from a YAML config file.",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        required=True,
        help="Path to the YAML configuration file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # setup
    setup_parser = subparsers.add_parser("setup", help="Download and install the server.")
    setup_parser.add_argument("--output-dir", metavar="DIR", help="Override server.output_dir.")
    setup_parser.add_argument(
        "--dry-run", action="store_true", help="Log actions without downloading."
    )

    # validate
    subparsers.add_parser("validate", help="Validate the configuration file.")

    # status
    subparsers.add_parser("status", help="Show installed server state from the manifest.")

    args = parser.parse_args()

    if args.command == "validate":
        _cmd_validate(args)
    elif args.command == "setup":
        _cmd_setup(args)
    elif args.command == "status":
        _cmd_status(args)


def _cmd_validate(args: argparse.Namespace) -> None:
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"Invalid config: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"OK — server type={config.server.type}, mc={config.server.minecraft_version}")


def _cmd_setup(args: argparse.Namespace) -> None:
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"Invalid config: {exc}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else config.server.output_dir
    dry_run: bool = args.dry_run

    if dry_run:
        print("[dry-run] No files will be downloaded or written.")

    if config.server_pack:
        _setup_server_pack(config, output_dir, dry_run)
    elif config.modpack:
        _setup_modpack(config, output_dir, dry_run)
    elif config.mods:
        _setup_mods(config, output_dir, dry_run)
    else:
        # Vanilla / loader-only: install server JAR, then write config files
        jar_path = _install_server_jar(config, output_dir, dry_run)
        _write_server_files(config, output_dir, jar_path, dry_run)
        if not dry_run:
            print(f"Server installed to {output_dir}")


def _install_server_jar(config, output_dir: Path, dry_run: bool) -> Path | None:
    """Install the appropriate server JAR.

    Returns the path to the installed JAR, or None for Forge/NeoForge (which
    create their own run script via --installServer).
    """
    from mc_helper.http_client import build_session

    server = config.server

    if dry_run:
        print(
            f"[dry-run] Would install {server.type} {server.minecraft_version} "
            f"server to {output_dir}"
        )
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()

    if server.type == "vanilla":
        from mc_helper.server import vanilla

        return vanilla.install(server.minecraft_version, output_dir, session=session)

    elif server.type == "fabric":
        from mc_helper.server import fabric

        return fabric.install(
            server.minecraft_version,
            output_dir,
            loader_version=server.loader_version,
            session=session,
        )

    elif server.type == "forge":
        from mc_helper.server import forge

        forge.install(
            server.minecraft_version,
            output_dir,
            forge_version=server.loader_version,
            session=session,
        )
        return None  # forge --installServer creates its own run.sh

    elif server.type == "neoforge":
        from mc_helper.server import neoforge

        neoforge.install(
            server.minecraft_version,
            output_dir,
            neoforge_version=server.loader_version,
            session=session,
        )
        return None  # neoforge --installServer creates its own run.sh

    elif server.type == "paper":
        from mc_helper.server import paper

        return paper.install(server.minecraft_version, output_dir, session=session)

    elif server.type == "purpur":
        from mc_helper.server import purpur

        return purpur.install(server.minecraft_version, output_dir, session=session)

    else:
        raise ValueError(f"Unknown or unsupported server type: {server.type!r}")


def _write_server_files(config, output_dir: Path, jar_path: Path | None, dry_run: bool) -> None:
    """Write eula.txt, server.properties, and launch.sh into output_dir."""
    server = config.server

    # eula.txt
    eula_value = str(server.eula).lower()
    eula_path = output_dir / "eula.txt"
    if dry_run:
        print(f"[dry-run] Would write {eula_path}: eula={eula_value}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        eula_path.write_text(f"eula={eula_value}\n")

    # server.properties
    if server.properties:
        props_path = output_dir / "server.properties"
        lines = [f"{k}={v}\n" for k, v in server.properties.items()]
        content = "".join(lines)
        if dry_run:
            print(f"[dry-run] Would write {props_path}:")
            for line in lines:
                print(f"  {line}", end="")
        else:
            props_path.write_text(content)

    # launch.sh
    launch_path = output_dir / "launch.sh"
    mem = server.memory
    if jar_path is not None:
        jar_name = jar_path.name
        launch_content = (
            f"#!/bin/sh\n"
            f"exec java -Xmx{mem} -Xms{mem} -jar {jar_name} nogui \"$@\"\n"
        )
    elif server.type in ("forge", "neoforge"):
        launch_content = (
            f"#!/bin/sh\n"
            f"# The Forge/NeoForge installer created run.sh — invoke it here.\n"
            f"exec ./run.sh \"$@\"\n"
        )
    else:
        launch_content = (
            f"#!/bin/sh\n"
            f"exec java -Xmx{mem} -Xms{mem} -jar server.jar nogui \"$@\"\n"
        )

    if dry_run:
        print(f"[dry-run] Would write {launch_path}:")
        for line in launch_content.splitlines():
            print(f"  {line}")
    else:
        launch_path.write_text(launch_content)
        launch_path.chmod(0o755)


def _setup_server_pack(config, output_dir: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] Would install server pack to {output_dir}")
        _write_server_files(config, output_dir, None, dry_run)
        return

    from mc_helper.pack.server_pack import install as install_pack

    sp = config.server_pack
    install_pack(
        output_dir=output_dir,
        url=sp.url,
        github=sp.github,
        tag=sp.tag,
        asset=sp.asset,
        token=sp.token,
        strip_components=sp.strip_components,
        disable_mods_patterns=sp.disable_mods,
        force_update=sp.force_update,
    )
    _write_server_files(config, output_dir, None, dry_run)
    print(f"Server pack installed to {output_dir}")


def _setup_modpack(config, output_dir: Path, dry_run: bool) -> None:
    mp = config.modpack

    if dry_run:
        print(f"[dry-run] Would install {mp.platform} modpack to {output_dir}")
        _write_server_files(config, output_dir, None, dry_run)
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    loader = (
        config.server.type
        if config.server.type not in ("vanilla", "paper", "purpur")
        else None
    )

    if mp.platform == "modrinth":
        from mc_helper.modpack import modrinth

        modrinth.install(
            project=mp.project,
            output_dir=output_dir,
            minecraft_version=config.server.minecraft_version,
            loader=loader,
            version_type=mp.version_type,
            requested_version=mp.version,
            exclude_mods=mp.exclude_mods or None,
            overrides_exclusions=mp.overrides_exclusions or None,
        )
    elif mp.platform == "curseforge":
        from mc_helper.modpack import curseforge

        curseforge.install(
            api_key=mp.api_key,
            output_dir=output_dir,
            slug=mp.slug,
            file_id=mp.file_id,
            filename_matcher=mp.filename_matcher,
            exclude_mods=mp.exclude_mods or None,
            force_include_mods=mp.force_include_mods or None,
            overrides_exclusions=mp.overrides_exclusions or None,
        )

    _write_server_files(config, output_dir, None, dry_run)
    print(f"Modpack installed to {output_dir}")


def _setup_mods(config, output_dir: Path, dry_run: bool) -> None:
    if dry_run:
        mods_cfg = config.mods
        mr_count = len(mods_cfg.modrinth or [])
        cf_count = len(mods_cfg.curseforge.files) if mods_cfg.curseforge else 0
        url_count = len(mods_cfg.urls or [])
        print(
            f"[dry-run] Would install {mr_count} Modrinth + {cf_count} CurseForge "
            f"+ {url_count} URL mod(s) to {output_dir}/mods/"
        )
        jar_path = _install_server_jar(config, output_dir, dry_run)
        _write_server_files(config, output_dir, jar_path, dry_run)
        return

    from mc_helper.mods import curseforge as cf_mods
    from mc_helper.mods import modrinth as mr_mods
    from mc_helper.http_client import build_session

    mods_cfg = config.mods
    mc_ver = config.server.minecraft_version
    loader = config.server.type if config.server.type not in ("vanilla", "paper", "purpur") else None

    session = build_session()
    installed: list[str] = []
    errors: list[str] = []

    tasks: list[tuple] = []

    for spec in (mods_cfg.modrinth or []):
        tasks.append(("modrinth", spec))

    cf = mods_cfg.curseforge
    if cf:
        cf_session = build_session(extra_headers={"X-Api-Key": cf.api_key})
        for spec in cf.files:
            tasks.append(("curseforge", spec))

    def _run(kind: str, spec: str) -> str:
        if kind == "modrinth":
            return mr_mods.install_mod(
                spec, output_dir,
                minecraft_version=mc_ver,
                loader=loader,
                session=session,
                show_progress=False,
            )
        else:
            return cf_mods.install_mod(
                spec, output_dir,
                api_key=cf.api_key,
                minecraft_version=mc_ver,
                session=cf_session,
                show_progress=False,
            )

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_run, kind, spec): (kind, spec) for kind, spec in tasks}
        for fut in as_completed(futures):
            kind, spec = futures[fut]
            try:
                path = fut.result()
                installed.append(path)
                print(f"  installed {spec} → {path}")
            except Exception as exc:
                errors.append(f"{spec}: {exc}")
                print(f"  ERROR {spec}: {exc}", file=sys.stderr)

    for spec in (mods_cfg.urls or []):
        from mc_helper.http_client import download_file
        filename = spec.split("/")[-1].split("?")[0]
        dest = output_dir / "mods" / filename
        download_file(spec, dest, session=session, show_progress=True)
        installed.append(str(Path("mods") / filename))
        print(f"  installed {spec} → mods/{filename}")

    if errors:
        print(f"\n{len(errors)} mod(s) failed to install.", file=sys.stderr)
        sys.exit(1)

    print(f"\n{len(installed)} mod(s) installed to {output_dir}/mods/")

    # Install server JAR and write config files
    jar_path = _install_server_jar(config, output_dir, dry_run)
    _write_server_files(config, output_dir, jar_path, dry_run)


def _cmd_status(args: argparse.Namespace) -> None:
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"Invalid config: {exc}", file=sys.stderr)
        sys.exit(1)

    from mc_helper.manifest import Manifest

    output_dir = config.server.output_dir
    manifest = Manifest(output_dir)
    manifest.load()

    if not manifest._data:
        print(f"No manifest found in {output_dir} — server has not been set up yet.")
        return

    print(f"Manifest: {manifest.path}")
    if manifest.mc_version:
        print(f"  Minecraft version : {manifest.mc_version}")
    if manifest.loader_type:
        print(f"  Loader            : {manifest.loader_type}")
    if manifest.loader_version:
        print(f"  Loader version    : {manifest.loader_version}")
    if manifest.pack_sha1:
        print(f"  Pack SHA-1        : {manifest.pack_sha1}")
    files = manifest.files
    if files:
        print(f"  Tracked files     : {len(files)}")
        for f in files:
            print(f"    {f}")
