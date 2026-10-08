from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from canaria.models import JobPosting, WorkplaceType


class MissingFieldError(ValueError):
    def __init__(self, field: str, board: str, job_id: object, reason: str | None = None) -> None:
        # `field` is the data that is lost; `reason` optionally says what in the source was missing.
        self.field = field
        self.board = board
        self.job_id = job_id
        self.reason = reason
        message = f"missing field {field!r} (board={board}, job_id={job_id})"
        super().__init__(f"{message}: {reason}" if reason else message)


class InvalidJobError(ValueError):
    def __init__(self, board: str, job_id: object, error: ValidationError) -> None:
        self.board = board
        self.job_id = job_id
        self.error = error
        super().__init__(f"invalid job (board={board}, job_id={job_id}): {error}")


class InvalidPayloadError(ValueError):
    def __init__(self, board: str, problem: str) -> None:
        self.board = board
        self.problem = problem
        super().__init__(f"invalid response (board={board}): {problem}")


def _json_type(value: object) -> str:
    # The JSON name, which is what someone reading the raw response will see.
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


@dataclass(frozen=True)
class ParseResult:
    postings: list[JobPosting]
    skipped: int


def _require(job: dict[str, Any], key: str, board: str) -> Any:
    value = job.get(key)
    if value is None or value == "" or value == {}:
        raise MissingFieldError(key, board, job.get("id"))
    return value


def _workplace_type(value: object) -> WorkplaceType | None:
    # None when the value can't be mapped; the caller logs it with its own board and job ID.
    if not isinstance(value, str):
        return None
    try:
        return WorkplaceType(value.strip().lower())
    except ValueError:
        return None


def _require_str(job: dict[str, Any], key: str, board: str) -> str:
    value = _require(job, key, board)
    if not isinstance(value, str) or not value.strip():
        raise MissingFieldError(key, board, job.get("id"))
    return value
