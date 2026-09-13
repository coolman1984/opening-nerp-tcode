"""Tell a human the same night, instead of leaving a failure for whoever
opens the log next.

Every other phase of this project answers "how do we keep the run going".
This answers a different question RPA operators run into constantly:
someone has to actually find out a run failed, and a log file nobody is
reading until morning does not do that. The industry answer is to pair a
failure notification with something the reader can act on immediately -
what failed, and where to look - which is what `report_batch` composes.

Deliberately best-effort and entirely optional. Nothing here is a new
dependency (`smtplib`/`email` are stdlib, per CLAUDE.md 4.5), nothing here
is configured unless the operator sets the environment variables that name
a mail server, and nothing here can turn a real result into a script
error: a mail server that is down, unreachable, or misconfigured is
reported once, in the log, and never raised.

The SMTP login (when the server needs one) is the one thing here that is
NOT an environment variable, on purpose: CLAUDE.md 2.2 says no passwords
anywhere but the DPAPI store, without carving out an exception for a
secondary credential. It lives in its own DPAPI file
(`gmes credentials set-alert-smtp`), the same mechanism as the G-MES
login, just a different secret.
"""
import os
import smtplib
from email.message import EmailMessage

from ..auth import credentials
from ..paths import alert_credentials_path, log_path


def configured():
    """Whether enough has been set to even attempt sending anything."""
    return bool(os.environ.get("GMES_ALERT_SMTP_HOST") and os.environ.get("GMES_ALERT_TO"))


def notify(subject, body, log=print):
    """Send one best-effort email. Never raises.

    A run that finished - successfully or not - has already done its real
    work; a notification about that outcome failing to SEND must never be
    allowed to look like the run itself failing."""
    if not configured():
        return False
    host = os.environ["GMES_ALERT_SMTP_HOST"]
    port = int(os.environ.get("GMES_ALERT_SMTP_PORT", "25"))
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ.get("GMES_ALERT_FROM", "gmes-automation@localhost")
    message["To"] = os.environ["GMES_ALERT_TO"]
    message.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            # EHLO first: `has_extn` only reports what a PRIOR ehlo/helo
            # response listed, so checking it before this call always came
            # back empty and STARTTLS was never actually reached, whatever
            # the server offered - see HISTORY.md Phase 54.4.
            server.ehlo()
            if server.has_extn("STARTTLS"):
                server.starttls()
                server.ehlo()   # RFC 3207: the extension list must be re-read post-TLS
            user, password = credentials.load(alert_credentials_path())
            if user and password:
                server.login(user, password)
            server.send_message(message)
        return True
    except Exception as error:
        log(f"(could not send the failure alert: {error})")
        return False


def _summary_line(execution):
    if execution.login.outcome.name != "OK":
        return f"sign-in did not complete ({execution.login.detail or execution.login.outcome.name})"
    failed = [result.screen for result in execution.results if not result.ok]
    return f"{len(failed)} of {len(execution.results)} screen(s) failed: {', '.join(failed)}"


def _body(execution):
    lines = [_summary_line(execution), ""]
    for result in execution.results:
        status = "OK" if result.ok else "FAILED"
        detail = result.error if not result.ok else f"{result.rows} rows"
        lines.append(f"  {status:<6} {result.screen:<14} {detail}")
    lines += ["", f"Full log: {log_path()}"]
    return "\n".join(lines)


def report_batch(execution, log=print):
    """Notify only on a batch that did not fully succeed.

    A successful run is not worth an email - the exported file is its own
    proof, sitting where it was asked to be - so this stays silent unless
    something needs a person's attention."""
    if execution.ok:
        return False
    return notify(f"G-MES run failed: {_summary_line(execution)}", _body(execution), log=log)
