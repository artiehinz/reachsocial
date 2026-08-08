from __future__ import annotations


class ReachSocialError(Exception):
    code = "internal_error"
    status_code = 500

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class InvalidInput(ReachSocialError):
    code = "invalid_input"
    status_code = 422


class UnknownService(ReachSocialError):
    code = "unknown_service"
    status_code = 404


class DisabledService(ReachSocialError):
    code = "disabled"
    status_code = 503


class ProviderUnavailable(ReachSocialError):
    code = "upstream_unavailable"
    status_code = 503


class ProviderTimeout(ReachSocialError):
    code = "upstream_timeout"
    status_code = 504


class LimitExceeded(ReachSocialError):
    code = "limit_exceeded"
    status_code = 429


class IdempotencyConflict(ReachSocialError):
    code = "idempotency_conflict"
    status_code = 409
