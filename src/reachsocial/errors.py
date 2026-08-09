from __future__ import annotations


class ReachSocialError(Exception):
    code = "internal_error"
    status_code = 500
    retryable = False

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


class AsyncRequired(ReachSocialError):
    code = "async_required"
    status_code = 409


class ProviderUnavailable(ReachSocialError):
    code = "provider_unavailable"
    status_code = 503
    retryable = True


class ProviderAccessDenied(ProviderUnavailable):
    retryable = False


class ProviderTimeout(ReachSocialError):
    code = "provider_timeout"
    status_code = 504
    retryable = True


class ProviderRateLimit(ReachSocialError):
    code = "rate_limit"
    status_code = 429
    retryable = True


class LimitExceeded(ReachSocialError):
    code = "limit_exceeded"
    status_code = 429
    retryable = True


class RateLimitExceeded(LimitExceeded):
    code = "rate_limit"


class SpendLimitExceeded(LimitExceeded):
    code = "spend_limit"


class IdempotencyConflict(ReachSocialError):
    code = "idempotency_conflict"
    status_code = 409


class ResourceNotFound(ReachSocialError):
    code = "not_found"
    status_code = 404


class PrivateOrUnavailable(ReachSocialError):
    code = "private_or_unavailable"
    status_code = 403


class UnauthorizedJob(ReachSocialError):
    code = "job_not_found"
    status_code = 404


class JobExpired(ReachSocialError):
    code = "job_expired"
    status_code = 410


class JobNotFailed(ReachSocialError):
    code = "job_not_failed"
    status_code = 409


class CreditUnavailable(ReachSocialError):
    code = "credit_unavailable"
    status_code = 409


class TestCapacityReached(ReachSocialError):
    code = "test_capacity_reached"
    status_code = 503
    retryable = True
