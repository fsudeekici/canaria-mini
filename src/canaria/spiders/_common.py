from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from canaria.models import JobPosting


class MissingFieldError(ValueError):
    def __init__(self, field: str, board: str, job_id: object) -> None:
        self.field = field
        self.board = board
        self.job_id = job_id
        super().__init__(f"missing field {field!r} (board={board}, job_id={job_id})")


class InvalidJobError(ValueError):
    def __init__(self, board: str, job_id: object, error: ValidationError) -> None:
        self.board = board
        self.job_id = job_id
        self.error = error
        super().__init__(f"invalid job (board={board}, job_id={job_id}): {error}")


@dataclass(frozen=True)
class ParseResult:
    postings: list[JobPosting]
    skipped: int


def _require(job: dict[str, Any], key: str, board: str) -> Any:
    value = job.get(key)
    if value is None or value == "" or value == {}:
        raise MissingFieldError(key, board, job.get("id"))
    return value


def _require_str(job: dict[str, Any], key: str, board: str) -> str:
    value = _require(job, key, board)
    if not isinstance(value, str) or not value.strip():
        raise MissingFieldError(key, board, job.get("id"))
    return value
