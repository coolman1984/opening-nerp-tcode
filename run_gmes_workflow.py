"""Compatible G-MES workflow launcher.

This file keeps the familiar legacy command and double-click workflow, but it
contains no automation logic. Both this path and ``gmes run`` now enter the
same standalone application facade, so a safety fix cannot land in one and be
missed by the other.
"""
import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from gmes.cli.app import main as gmes_main  # noqa: E402


def main():
    """Run the guided standalone workflow through the historical filename."""
    return gmes_main(["workflow"])


if __name__ == "__main__":
    sys.exit(main())
