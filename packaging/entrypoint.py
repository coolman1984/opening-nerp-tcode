"""PyInstaller target that preserves the ``gmes`` package import context."""
from gmes.cli.app import main


if __name__ == "__main__":
    raise SystemExit(main())
