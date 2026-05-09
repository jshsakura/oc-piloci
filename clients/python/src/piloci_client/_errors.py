"""Exception hierarchy for piloci-client."""

from __future__ import annotations


class PilociError(Exception):
    """Base class for all piloci-client errors."""

    def __init__(self, message: str, status_code: int | None = None, raw: object = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.raw = raw


class PilociAuthError(PilociError):
    """HTTP 401 — token missing, expired, or invalid."""


class PilociPermissionError(PilociError):
    """HTTP 403 — token lacks project_id claim required for this endpoint.

    Project-scoped operations (memory, recall, recommend, contradict) require
    a token that encodes a project_id claim.  Generate one in piLoci Settings
    → Tokens and select a project scope.
    """


class PilociValidationError(PilociError):
    """HTTP 422 — request body failed server-side validation."""

    def __init__(
        self,
        message: str,
        details: object = None,
        status_code: int = 422,
        raw: object = None,
    ) -> None:
        super().__init__(message, status_code=status_code, raw=raw)
        self.details = details


class PilociServerError(PilociError):
    """HTTP 5xx — server-side error."""
