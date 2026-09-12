"""Explicit credential setup; the only writer of standalone login secrets."""
from ..auth import credentials
from ..contracts import CredentialUpdate


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
