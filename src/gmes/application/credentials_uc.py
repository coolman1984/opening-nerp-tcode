"""Explicit credential setup; the only writer of standalone login secrets."""
from ..auth import credentials
from ..contracts import CredentialUpdate
from ..paths import alert_credentials_path


def set_credentials():
    """Prompt locally, then save only through the Windows DPAPI store.

    The prompt owns secret entry. This result deliberately does not return the
    supplied user name or password, so the CLI cannot render or log either.
    """
    user, password = credentials.ask_credentials()
    if not user or not password:
        return CredentialUpdate(False, "Credential update cancelled; nothing changed.")
    credentials.save(user, password)
    return CredentialUpdate(True, "Credential saved in the local DPAPI store.")


def set_alert_credentials():
    """The SMTP login `alerts.py` sends the failure email through - a
    second, separate DPAPI secret, never the G-MES login and never an
    environment variable (CLAUDE.md 2.2)."""
    path = alert_credentials_path()
    user, password = credentials.ask_credentials(
        label="Alert SMTP account (blank to send unauthenticated)", path=path)
    if not user or not password:
        return CredentialUpdate(False, "Alert credential update cancelled; nothing changed.")
    credentials.save(user, password, path=path)
    return CredentialUpdate(True, "Alert SMTP credential saved in the local DPAPI store.")
