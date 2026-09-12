"""Explicit, idempotent runtime-state migrations."""
from ..paths import migrate_legacy_credentials


def migrate_credentials():
    """Copy a legacy credential blob only when the user explicitly asks."""
    return migrate_legacy_credentials()
