"""Best-effort secret redaction for persisted process output.

homelab#720: open-terminal's process logs (``logs/processes/*.jsonl``) are
retained on a persistent volume, readable by every future task in the
shared pod. A command that echoes a secret to stdout -- intentionally for
debugging, or by an env-var dump -- gets that secret permanently
retained. This module redacts known, structurally-recognizable secret
formats before a line is written to disk.

This is explicitly *best-effort*, not exhaustive (the issue that prompted
this: "even best-effort redaction is better than none"). It matches
well-known, low-false-positive STRUCTURED secret formats -- the same
philosophy as gitleaks' default ruleset, which is what the issue
suggested reusing. It intentionally does NOT attempt generic
high-entropy-string detection or unstructured "key=value"-style
heuristics, both of which are prone to redacting ordinary non-secret
output.

Two independent limitations, accepted given the "best-effort" framing:
- A secret can straddle two separate PTY read chunks (4096 bytes each,
  see ``runner.py``) and evade detection in either half alone.
- New secret formats not covered by ``PATTERNS`` below aren't caught.
"""

import re

# Each entry: (label, compiled pattern). Order doesn't matter -- patterns
# are applied independently, not as alternatives.
PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    # GitHub tokens: personal access (classic + fine-grained), OAuth,
    # user-to-server, installation/App tokens, refresh tokens.
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,255}\b")),
    ("github-pat-fine-grained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,255}\b")),
    # PEM-encoded private keys (RSA/EC/OPENSSH/DSA/generic) -- the class
    # of leak that motivated this fix (a full GITHUB_APP_PRIVATE_KEY
    # found in a process log via `env | grep`).
    (
        "private-key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"
            r"[\s\S]*?"
            r"-----END (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"
        ),
    ),
    # AWS access key IDs (secret access keys have no distinctive prefix,
    # so aren't reliably matchable without false positives -- out of
    # scope for this best-effort pass).
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # Slack tokens.
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    # JWTs (three dot-separated base64url segments, header always starts
    # with `eyJ` since it's `{"` base64url-encoded).
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ),
    # Generic Bearer auth header value.
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9\-_.=]{16,}")),
]

_REDACTED = "[REDACTED:{label}]"


def redact_secrets(text: str) -> str:
    """Return *text* with any recognized secret pattern replaced.

    Safe to call on arbitrary text, including text with no secrets
    (returned unchanged) or malformed/partial data (best-effort only).
    """
    if not text:
        return text
    for label, pattern in PATTERNS:
        text = pattern.sub(_REDACTED.format(label=label), text)
    return text
