from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ErrorEnvelope:
    error_code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
        }


class RustSenseiError(Exception):
    def __init__(self, envelope: ErrorEnvelope) -> None:
        super().__init__(envelope.message)
        self.envelope = envelope


class ValidationError(RustSenseiError):
    pass


class NotFoundError(RustSenseiError):
    pass


class StorageError(RustSenseiError):
    pass


class IdempotencyConflictError(RustSenseiError):
    pass


def validation_error(message: str, **details: Any) -> ValidationError:
    return ValidationError(
        ErrorEnvelope(
            error_code="validation_error",
            message=message,
            details=details,
            retryable=False,
        )
    )


def not_found_error(message: str, **details: Any) -> NotFoundError:
    return NotFoundError(
        ErrorEnvelope(
            error_code="not_found",
            message=message,
            details=details,
            retryable=False,
        )
    )


def storage_error(message: str, retryable: bool = True, **details: Any) -> StorageError:
    return StorageError(
        ErrorEnvelope(
            error_code="storage_error",
            message=message,
            details=details,
            retryable=retryable,
        )
    )


def idempotency_conflict_error(
    message: str,
    **details: Any,
) -> IdempotencyConflictError:
    return IdempotencyConflictError(
        ErrorEnvelope(
            error_code="idempotency_conflict",
            message=message,
            details=details,
            retryable=False,
        )
    )
