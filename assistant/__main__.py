"""``python -m assistant`` — doctor, model store, recommend, status, install-state."""
from __future__ import annotations

import argparse
import signal
from typing import Optional

from . import __version__, doctor, install_state, models, recommend, util
from .runner_client import RunnerClient, RunnerError


def _install_signal_handlers() -> None:
    """Stop an in-flight curl child cleanly on Ctrl-C / SIGTERM."""
    def handler(signum, _frame):
        models.terminate_active_child()
        raise SystemExit(128 + signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):  # pragma: no cover - non-main thread
            pass


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_doctor(args: argparse.Namespace) -> int:
    report = doctor.build_report(timeout=args.timeout)
    if args.json:
        util.emit(report)
    else:
        print(doctor.human(report))
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    report = recommend.recommend()
    if args.json:
        util.emit(report)
    else:
        print(recommend.human(report))
    return 0


def cmd_macos_permissions(args: argparse.Namespace) -> int:
    """Status (and optional prompting) of the macOS privacy permissions.

    Runs inside the daemon's own interpreter so the TCC prompts attach to the
    binary launchd starts, not to the settings app. On Linux every status is
    ``unknown`` and nothing is prompted.
    """
    from utter.macos import permissions

    names = None
    request = False
    if args.request:
        request = True
        if args.request != "all":
            names = [n.strip() for n in args.request.split(",") if n.strip()]
            unknown = [n for n in names if n not in permissions.PERMISSION_IDS]
            if unknown:
                util.eprint(f"unknown permission(s): {', '.join(unknown)}")
                return 2
    doc = permissions.status_all(request=request, names=names)
    if args.json:
        util.emit(doc)
    else:
        for item in doc["permissions"]:
            print(f"{item['status']:<15} {item['label']}")
        print("all granted" if doc["all_granted"] else "missing permissions")
    return 0 if doc["all_granted"] else 1


def cmd_status(args: argparse.Namespace) -> int:
    client = RunnerClient(util.runner_sock_path(), timeout=args.timeout)
    try:
        client.connect()
    except OSError as exc:
        if args.json:
            util.emit({"ok": False, "connected": False,
                       "error": f"runner socket unavailable: {exc}"})
        else:
            util.eprint(f"runner socket unavailable: {exc}")
        return 1
    try:
        status = client.call("runner.status", {})
    except (RunnerError, TimeoutError, ConnectionError) as exc:
        if args.json:
            util.emit({"ok": False, "connected": True, "error": str(exc)})
        else:
            util.eprint(f"runner.status failed: {exc}")
        return 1
    finally:
        client.close()
    if args.json:
        util.emit(status)
    else:
        plugins = status.get("plugins", []) if isinstance(status, dict) else []
        print(f"runner: {len(plugins)} plugin(s)")
        for p in plugins:
            print(f"  - {p.get('id')} [{p.get('kind')}] epoch={p.get('epoch')} "
                  f"status={p.get('status')}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    action = args.models_action
    if action == "list":
        entries = models.list_models()
        if args.json:
            util.emit({"models": entries, "store": util.models_status()})
        else:
            status = util.models_status()
            print(f"store: {status['root']} (kept on uninstall; override with UTTER_MODELS)")
            print(models.human_list(entries))
        return 0
    if action == "show":
        entries = models.show(args.name)
        if args.json:
            util.emit({"models": entries})
        else:
            print(models.human_show(entries))
        return 0 if entries else 1
    if action == "pull":
        try:
            result = models.pull(args.source, tag=args.tag, json_progress=args.json)
        except (RuntimeError, ValueError, OSError) as exc:
            if args.json:
                util.ndjson({"event": "error", "error": str(exc)})
            else:
                util.eprint(f"pull failed: {exc}")
            return 1
        if not args.json:
            print(f"pulled {result['name']}:{result['tag']} "
                  f"({util.human_bytes(result['bytes'])}) sha256:{result['sha256'][:16]}…")
        return 0
    if action == "rm":
        result = models.rm(args.name)
        if args.json:
            util.emit(result)
        else:
            print(f"removed {len(result['removed_manifests'])} manifest(s), "
                  f"{len(result['removed_blobs'])} blob(s)")
        return 0
    if action == "prune":
        result = models.prune()
        if args.json:
            util.emit(result)
        else:
            print(f"pruned {len(result['removed_partials'])} partial(s), "
                  f"{len(result['removed_blobs'])} orphan blob(s)")
        return 0
    util.eprint(f"unknown models action: {action}")
    return 2


def cmd_install_state(args: argparse.Namespace) -> int:
    if args.install_action == "record":
        files = install_state.parse_csv((args.files or []) + (args.file or []))
        units = install_state.parse_csv((args.units or []) + (args.unit or []))
        packages = install_state.parse_csv((args.packages or []) + (args.package or []))
        data = install_state.record(
            files=files,
            units=units,
            packages=packages,
            version=args.version,
            protocol=args.protocol,
        )
        if args.json:
            util.emit(data)
        else:
            print(f"recorded install.json: {util.install_json_path()}")
            print(f"  version:  {data.get('version') or '(unset)'}")
            print(f"  protocol: {data.get('protocol') or '(unset)'}")
            print(f"  files:    {len(data.get('files', []))}")
            print(f"  units:    {len(data.get('units', []))}")
            print(f"  packages: {len(data.get('packages', []))}")
        return 0
    # show: print the full manifest
    util.emit(install_state.show())
    return 0


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m assistant",
                                     description="utter assistant CLI (M5)")
    parser.add_argument("--version", action="version", version=f"assistant {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="deps + plugin negotiation + drift")
    p_doctor.add_argument("--json", action="store_true")
    p_doctor.add_argument("--timeout", type=float, default=10.0)
    p_doctor.set_defaults(func=cmd_doctor)

    p_rec = sub.add_parser("recommend", help="hardware-aware profile suggestions")
    p_rec.add_argument("--json", action="store_true")
    p_rec.set_defaults(func=cmd_recommend)

    p_status = sub.add_parser("status", help="runner.status passthrough")
    p_status.add_argument("--json", action="store_true")
    p_status.add_argument("--timeout", type=float, default=10.0)
    p_status.set_defaults(func=cmd_status)

    p_perm = sub.add_parser("macos-permissions",
                            help="macOS privacy permissions status (+ prompt with --request)")
    p_perm.add_argument("--json", action="store_true")
    p_perm.add_argument("--request", default=None, metavar="NAME|all",
                        help="trigger the system prompt for one permission (or 'all')")
    p_perm.set_defaults(func=cmd_macos_permissions)

    p_models = sub.add_parser("models", help="model store")
    msub = p_models.add_subparsers(dest="models_action", required=True)
    m_list = msub.add_parser("list", help="list installed models")
    m_list.add_argument("--json", action="store_true")
    p_show = msub.add_parser("show", help="show a model")
    p_show.add_argument("name")
    p_show.add_argument("--json", action="store_true")
    p_pull = msub.add_parser("pull", help="download a model (resumable)")
    p_pull.add_argument("source", help="hf:org/repo[:file] | https://… | file://…")
    p_pull.add_argument("--tag", default="latest")
    p_pull.add_argument("--json", action="store_true")
    p_rm = msub.add_parser("rm", help="remove a model + unreferenced blobs")
    p_rm.add_argument("name")
    p_rm.add_argument("--json", action="store_true")
    m_prune = msub.add_parser("prune", help="GC orphan partials/blobs")
    m_prune.add_argument("--json", action="store_true")
    p_models.set_defaults(func=cmd_models)

    p_inst = sub.add_parser("install-state", help="install.json record/show")
    isub = p_inst.add_subparsers(dest="install_action", required=True)
    p_rec2 = isub.add_parser("record", help="record installed files/units/packages")
    p_rec2.add_argument("--files", action="append", default=[],
                        help="comma-separated paths (repeatable)")
    p_rec2.add_argument("--units", action="append", default=[],
                        help="comma-separated unit names (repeatable)")
    p_rec2.add_argument("--packages", action="append", default=[],
                        help="comma-separated package names (repeatable)")
    p_rec2.add_argument("--file", action="append", default=[], help=argparse.SUPPRESS)
    p_rec2.add_argument("--unit", action="append", default=[], help=argparse.SUPPRESS)
    p_rec2.add_argument("--package", action="append", default=[], help=argparse.SUPPRESS)
    p_rec2.add_argument("--version", default=None)
    p_rec2.add_argument("--protocol", default=None)
    p_rec2.add_argument("--json", action="store_true")
    p_show2 = isub.add_parser("show", help="show install.json")
    p_show2.add_argument("--json", action="store_true")
    p_inst.set_defaults(func=cmd_install_state)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    _install_signal_handlers()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
