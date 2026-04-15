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

    if config.server_pack:
        _setup_server_pack(config, output_dir)
    elif config.modpack:
        print("modpack setup: not yet implemented", file=sys.stderr)
        sys.exit(1)
    elif config.mods:
        _setup_mods(config, output_dir)
    else:
        print("vanilla/loader-only setup: not yet implemented", file=sys.stderr)
        sys.exit(1)


def _setup_server_pack(config, output_dir: Path) -> None:
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
    print(f"Server pack installed to {output_dir}")


def _setup_mods(config, output_dir: Path) -> None:
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


def _cmd_status(args: argparse.Namespace) -> None:
    print(f"status: {args.config} (not yet implemented)")
    sys.exit(1)
