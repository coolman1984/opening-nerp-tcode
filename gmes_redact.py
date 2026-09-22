"""One source of truth for what looks like a credential (CLAUDE.md 2.2/2.3).

Used by `gmes_log.py` (console/log redaction) and `gmes_data.py` (CSV export
column filtering) - previously two independent copies of the same short word
list (HISTORY.md Open Item 39), which could drift when only one was updated,
and both were missing plausible real names: `credential`, `sessionKey`,
`sessionId`, `jwt`, `apiKey`, `accessKey`, `authKey`, `bearer`.
"""
import re

# A short word is enough to match deliberately, by substring, not by whole
# word - CLAUDE.md 2.3's own example, `refreshTokenId`, is already caught by
# the bare "token" here with no separate "refreshtoken"/"accesstoken" entry
# needed. Being over-inclusive costs nothing worse than an ordinary value
# being withheld from a CSV or masked in a log line nobody needed unmasked.
SENSITIVE_WORDS = (
    "password", "passwd", "pwd", "token", "secret", "authorization", "cookie",
    "credential", "session", "jwt", "apikey", "accesskey", "authkey", "bearer",
)

_ALTERNATION = "|".join(SENSITIVE_WORDS)
NAME_PATTERN = re.compile(f"(?i)({_ALTERNATION})")
# An assignment-shaped occurrence in free text: NAME, then `:`/`=` or plain
# whitespace, then a VALUE - what a log line or a command line actually looks
# like, not just a bare column name.
TEXT_PATTERN = re.compile(
    rf"(?i)({_ALTERNATION})(\s*[:=]\s*|\s+)(['\"]?)[^\s,'\"}}]+\3")


def is_sensitive_name(name):
    """Whether a column/field NAME alone looks credential-shaped."""
    return bool(NAME_PATTERN.search(name or ""))


def redact_text(text, placeholder="***"):
    """Replace `name=value` / `name: value`-shaped secrets in free text."""
    return TEXT_PATTERN.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{placeholder}", text or "")
