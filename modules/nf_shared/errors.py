from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class AppError(Exception):
    code: ErrorCode
    message: str
    details: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.details is not None:
            payload["details"] = dict(self.details)
        return {"error": payload}

