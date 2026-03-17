from __future__ import annotations


class AppError(Exception):
    """Base class for all application errors."""

    error_code: str = "UNKNOWN_ERROR"

    def __init__(self, message: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code


class UnitConversionError(AppError):
    error_code = "UNIT_CONVERSION_FAILED"


class PriceProviderUnavailableError(AppError):
    error_code = "PRICE_PROVIDER_UNAVAILABLE"


class PriceProviderTimeoutError(AppError):
    error_code = "PRICE_PROVIDER_TIMEOUT"


class ResultSaveError(AppError):
    error_code = "RESULT_SAVE_FAILED"


class TtlExpiredError(AppError):
    error_code = "TTL_EXPIRED"


class WorkerTimeoutError(AppError):
    error_code = "WORKER_TIMEOUT"


class ValidationError(AppError):
    error_code = "VALIDATION_ERROR"


class NotFoundError(AppError):
    error_code = "NOT_FOUND"


class ConflictError(AppError):
    error_code = "CONFLICT"
