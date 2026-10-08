import html
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from canaria.models import JobPosting

logger = logging.getLogger(__name__)

BOARD_URL: str = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"


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


def _parse_job(job: dict[str, Any], board: str) -> JobPosting:
    job_id = _require(job, "id", board)
    location = _require(job, "location", board)
    location_name = location.get("name") if isinstance(location, dict) else None
    if not isinstance(location_name, str) or not location_name.strip():
        raise MissingFieldError("location.name", board, job_id)

    try:
        return JobPosting(
            id=str(job_id),
            title=_require_str(job, "title", board).strip(),
            company=_require_str(job, "company_name", board),
            location=location_name.strip(),
            language=_require_str(job, "language", board),
            url=_require_str(job, "absolute_url", board),
            description=html.unescape(_require_str(job, "content", board)),
            posted_at=_require_str(job, "first_published", board),
            updated_at=_require_str(job, "updated_at", board),
        )
    except ValidationError as e:
        raise InvalidJobError(board, job_id, e) from e


def parse_jobs(payload: dict[str, Any], board: str) -> ParseResult:
    jobs: list[dict[str, Any]] = payload["jobs"]
    total = payload.get("meta", {}).get("total")
    if total != len(jobs):
        logger.warning("board=%s: meta.total=%s but response has %d jobs", board, total, len(jobs))

    postings: list[JobPosting] = []
    skipped = 0
    for job in jobs:
        try:
            postings.append(_parse_job(job, board))
        except (MissingFieldError, InvalidJobError) as e:
            logger.error("skipping job: %s", e)
            skipped += 1

    if skipped:
        logger.error("board=%s: skipped %d of %d jobs", board, skipped, len(jobs))
    return ParseResult(postings=postings, skipped=skipped)


def fetch_jobs(board: str, client: httpx.Client | None = None) -> ParseResult:
    url = BOARD_URL.format(board=board)
    if client is None:
        with httpx.Client(timeout=30) as c:
            response = c.get(url)
    else:
        response = client.get(url)
    response.raise_for_status()
    return parse_jobs(response.json(), board)
