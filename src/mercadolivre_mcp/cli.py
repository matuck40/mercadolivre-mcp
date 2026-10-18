"""Command line entry point (stub; subcommands arrive in later tasks)."""

import argparse

from mercadolivre_mcp import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mercadolivre-mcp")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    args = parser.parse_args(argv)
    if args.version:
        print(f"mercadolivre-mcp {__version__}")
    return 0
