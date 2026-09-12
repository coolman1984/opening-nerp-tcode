"""Allows `python -m gmes`; delegates to the same entry point as gmes.exe."""

from .cli.app import main


if __name__ == "__main__":
    raise SystemExit(main())
