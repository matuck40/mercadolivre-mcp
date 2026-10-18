"""Command line entry point: ``serve`` (default), ``auth url`` and ``auth code``."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import urllib.parse
from typing import TextIO

from mercadolivre_mcp import __version__
from mercadolivre_mcp.auth import (
    TokenStore,
    authorization_url,
    exchange_code,
    load_oauth_state,
    save_oauth_state,
)
from mercadolivre_mcp.client import MLClient
from mercadolivre_mcp.config import Config
from mercadolivre_mcp.errors import AuthError, ConfigError
from mercadolivre_mcp.server import Server
from mercadolivre_mcp.tools import TOOLS


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mercadolivre-mcp")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    sub = parser.add_subparsers(dest="command", metavar="{auth}")
    auth = sub.add_parser("auth", help="authorize the server against your seller account")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_sub.add_parser("url", help="print the authorization URL")
    code = auth_sub.add_parser("code", help="exchange the authorization code for a token")
    code.add_argument("code", help="the code, or the full redirect URL you were sent to")
    return parser


def _serve(config: Config, stdin: TextIO, stdout: TextIO) -> int:
    if stdin is sys.stdin:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    if stdout is sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    server = Server(TOOLS, lambda: MLClient(config))
    try:
        server.serve(stdin, stdout)
    except BrokenPipeError:
        # The client went away; nothing left to tell it. The failed write stays in
        # the buffer and would be re-flushed at shutdown (exit 120), so point
        # fd 1 at devnull first.
        if stdout is sys.stdout:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
            os.close(devnull)
        return 0
    return 0


def _auth_url(config: Config, stdout: TextIO) -> int:
    state = secrets.token_urlsafe(16)
    url = authorization_url(config, state)
    save_oauth_state(config.secrets_dir, state)
    print(url, file=stdout)
    print(
        "Open this URL while logged in as the seller, approve access, "
        "then run: mercadolivre-mcp auth code '<redirect URL>'",
        file=stdout,
    )
    return 0


def _parse_code(value: str) -> tuple[str, str | None]:
    """Accept a bare code or a redirect URL; return (code, state or None)."""
    value = value.strip()
    if "?" in value or value.startswith(("http://", "https://")):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(value).query)
        code = (query.get("code") or [""])[0]
        if not code:
            raise AuthError("No `code` parameter found in the redirect URL.")
        return code, (query.get("state") or [None])[0]
    return value, None


def _auth_code(config: Config, value: str, stdout: TextIO) -> int:
    code, state = _parse_code(value)
    saved = load_oauth_state(config.secrets_dir)
    if state is not None:
        if not saved or not secrets.compare_digest(state, saved):
            raise AuthError("State mismatch: run `mercadolivre-mcp auth url` again.")
    elif saved:
        print("Warning: state was not verified (bare code given).", file=sys.stderr)
    token = exchange_code(config, TokenStore(config.secrets_dir), code)
    save_oauth_state(config.secrets_dir, "")
    store_path = TokenStore(config.secrets_dir).path
    print(f"Authorized. Token saved to {store_path} (user_id {token.get('user_id')}).", file=stdout)
    return 0


def main(
    argv: list[str] | None = None,
    *,
    config: Config | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    # Resolved per call (not as defaults) so redirected streams are honoured.
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    args = _build_parser().parse_args(argv)
    if args.version:
        print(f"mercadolivre-mcp {__version__}", file=stdout)
        return 0
    try:
        cfg = config if config is not None else Config.from_env()
        if args.command is None:
            return _serve(cfg, stdin, stdout)
        if args.auth_command == "url":
            return _auth_url(cfg, stdout)
        return _auth_code(cfg, args.code, stdout)
    except (ConfigError, AuthError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
