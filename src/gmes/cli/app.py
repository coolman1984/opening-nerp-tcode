"""The unified G-MES command-line surface.

Parsing and rendering live here; browser and report decisions stay in the
application modules. Commands that touch G-MES first complete the typed
sign-in use case, while ``version`` and validation failures remain offline.
"""
from __future__ import annotations

import argparse
import sys

from .._version import __version__
from ..application.connect_uc import connect_gmes
from ..application.run_many_uc import run_many
from ..application.run_screen_uc import print_summary
from ..application.sign_in_uc import sign_in
from ..contracts import LoginOutcome, RunSpec
from ..screens.filters import normalise_date


def _parser():
    parser = argparse.ArgumentParser(prog="gmes", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="show the standalone package version")
    login = sub.add_parser("login", help="sign in to G-MES")
    login.add_argument("--assist", action="store_true")
    login.add_argument("--refresh-profile", action="store_true")
    run = sub.add_parser("run", help="run one or more screens sequentially")
    run.add_argument("screens", nargs="+", metavar="UI")
    run.add_argument("--division", "--org", dest="division")
    run.add_argument("--tree")
    run.add_argument("--from", dest="date_from")
    run.add_argument("--to", dest="date_to")
    run.add_argument("--date")
    run.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    run.add_argument("--option", action="append", default=[])
    run.add_argument("--grid")
    run.add_argument("--verify", metavar="COLUMN[=VALUE]")
    run.add_argument("--export", choices=("xlsx", "csv", "both", "none"), default="both")
    run.add_argument("--output-dir")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--close-tabs", action="store_true")
    run.add_argument("--no-profile", action="store_true")
    return parser


def _sets(items):
    values = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--set needs NAME=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        if not key.strip():
            raise ValueError("--set needs a non-empty name")
        values[key.strip()] = value.strip()
    return values


def _dates(args):
    date_from = normalise_date(args.date_from or args.date)
    date_to = normalise_date(args.date_to or args.date)
    if bool(date_from) != bool(date_to):
        raise ValueError("give both --from and --to, or --date for one day")
    return date_from, date_to


def _verified(value):
    if not value:
        return None
    column, sep, expected = value.partition("=")
    if not column.strip():
        raise ValueError("--verify needs COLUMN or COLUMN=VALUE")
    return column.strip(), expected.strip() if sep else None


def _signed_in(**kwargs):
    attempt = sign_in(**kwargs)
    return attempt.outcome is LoginOutcome.OK


def _run(args):
    date_from, date_to = _dates(args)
    sets, verify = _sets(args.set), _verified(args.verify)
    if not _signed_in():
        print("Sign-in did not complete. Nothing was run.")
        return 1
    specs = [RunSpec(screen_code=code, division=args.division, tree=args.tree,
                     date_from=date_from, date_to=date_to, sets=sets,
                     options=tuple(args.option), grid_name=args.grid, verify=verify,
                     export=args.export, out_dir=args.output_dir,
                     dry_run=args.dry_run, close_after=args.close_tabs,
                     use_profile=not args.no_profile)
             for code in args.screens]
    ws = connect_gmes()
    try:
        results = run_many(ws, specs)
        return 0 if print_summary(results) == len(results) else 1
    finally:
        ws.close()


def main(argv=None):
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "version":
            print(__version__)
            return 0
        if args.command == "login":
            return 0 if _signed_in(assist=args.assist,
                                   refresh_profile=args.refresh_profile) else 1
        if args.command == "run":
            return _run(args)
    except ValueError as error:
        print(f"gmes: error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
