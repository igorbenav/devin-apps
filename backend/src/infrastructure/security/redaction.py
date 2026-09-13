"""Helpers for keeping user-supplied credentials out of the logs."""

import hashlib

DIGEST_LENGTH = 12


def redact_identifier(value: str) -> str:
    """A stable, non-reversible tag for a submitted login identifier.

    Failed logins are worth correlating, but the submitted username is attacker- or typo-supplied: people regularly type
    their password into the username field. Logging a digest keeps "the same identifier failed forty times" visible
    without writing the value itself into log storage.
    """
    if not value:
        return "empty"
    return f"id:{hashlib.sha256(value.encode('utf-8', 'replace')).hexdigest()[:DIGEST_LENGTH]}"
