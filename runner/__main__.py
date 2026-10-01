"""CLI entry point: ``python -m runner --config <path>``.

Also supports ``--check-config`` (validate and exit) and ``--socket`` override.
Logs to stderr; exits cleanly on SIGTERM/SIGINT.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from .config import check_config, load_config
from .host import Host

log = logging.getLogger("runner.main")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m runner",
        description="utter reference runner host (M0)",
    )
    parser.add_argument("config_pos", nargs="?", metavar="CONFIG",
                        help="path to runner TOML config (positional alternative to --config)")
    parser.add_argument("--config", default="", help="path to runner TOML config")
    parser.add_argument("--socket", default="", help="override the unix socket path")
    parser.add_argument("--check-config", action="store_true", help="validate config and exit")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="stderr log level",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.socket:
        config.socket_path = args.socket
    host = Host(config)
    await host.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - non-unix
            signal.signal(sig, lambda *_: stop.set())

    log.info("runner ready: %d plugin(s), socket %s", len(host.plugins), host.socket.path)
    try:
        await stop.wait()
    finally:
        log.info("runner shutting down")
        await host.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = args.config or args.config_pos
    if not config_path:
        parser.error("a config path is required (--config PATH, or positional)")
    args.config = config_path
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.check_config:
        ok, messages = check_config(args.config)
        for message in messages:
            print(message, file=sys.stderr)
        print("config OK" if ok else "config INVALID", file=sys.stderr)
        return 0 if ok else 1
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
