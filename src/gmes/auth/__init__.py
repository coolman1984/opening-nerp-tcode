"""DPAPI credential storage and the sign-in flow (AD SSO + direct login).

Note on contracts.LoginOutcome: the bare OK/FAILED/REJECTED ints this
replaces live entirely in the OLD gmes_login.py's `main()` - the
CLI-driving retry/orchestration function, not in any of the mechanics
ported here (login_flow.py, session.py). That orchestration is
`application/sign_in_uc.py`'s job (a later migration phase); LoginOutcome
is defined and ready in contracts.login but genuinely has nothing to wire
into yet at this layer.
"""
from . import credentials
from .login_flow import (
    BTN_LOGIN, BTN_SSO, PW_FIELD, SSO_PW_FIELD, SSO_URL_MARK,
    SSO_USER_FIELD, USER_FIELD, complete_sso, direct_login, find_sso_window,
    login_error, wait_for_sso_window,
)
from .session import (
    USER_INFO_BTN, ensure_browser, is_logged_in, open_gmes,
    wait_for_login_or_session, wait_for_manual_sign_in,
)

__all__ = [
    "credentials",
    "BTN_LOGIN", "BTN_SSO", "PW_FIELD", "SSO_PW_FIELD", "SSO_URL_MARK",
    "SSO_USER_FIELD", "USER_FIELD", "complete_sso", "direct_login",
    "find_sso_window", "login_error", "wait_for_sso_window",
    "USER_INFO_BTN", "ensure_browser", "is_logged_in", "open_gmes",
    "wait_for_login_or_session", "wait_for_manual_sign_in",
]
