import argparse
import sys


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
    print(f"validate: {args.config} (not yet implemented)")
    sys.exit(1)


def _cmd_setup(args: argparse.Namespace) -> None:
    print(f"setup: {args.config} (not yet implemented)")
    sys.exit(1)


def _cmd_status(args: argparse.Namespace) -> None:
    print(f"status: {args.config} (not yet implemented)")
    sys.exit(1)
