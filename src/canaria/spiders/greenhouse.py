import html
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from canaria.models import JobPosting, WorkplaceType
from canaria.spiders._common import (
    InvalidJobError,
    InvalidPayloadError,
    MissingFieldError,
    ParseResult,
    _json_type,
    _require,
    _require_str,
    _workplace_type,
)

__all__ = [
    "InvalidJobError",
    "InvalidPayloadError",
    "MissingFieldError",
    "ParseResult",
    "fetch_jobs",
    "parse_jobs",
]

logger = logging.getLogger(__name__)

BOARD_URL: str = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
# A custom field each board sets up (or not) itself, not part of the standard Greenhouse schema.
WORKPLACE_FIELD: str = "Workplace Type"


def _workplace_entries(job: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = job.get("metadata")
    if not isinstance(metadata, list):
        return []
    return [m for m in metadata if isinstance(m, dict) and m.get("name") == WORKPLACE_FIELD]


def _workplace(job: dict[str, Any], board: str, job_id: object, board_has_field: bool) -> WorkplaceType | None:
    entries = _workplace_entries(job)
    if not entries:
        # A board without the field at all is logged once in parse_jobs, not once per job.
        if board_has_field:
            logger.warning(
                "board=%s job_id=%s: no metadata %r; workplace_type stored as None", board, job_id, WORKPLACE_FIELD
            )
        return None
    value = entries[0].get("value")
    if len(entries) > 1:
        logger.warning(
            "board=%s job_id=%s: %d metadata %r entries, using only the first (%r): %r",
            board,
            job_id,
            len(entries),
            WORKPLACE_FIELD,
            value,
            [e.get("value") for e in entries],
        )
    workplace_type = _workplace_type(value)
    if workplace_type is None:
        logger.warning(
            "board=%s job_id=%s: metadata %r value %r not recognised; workplace_type stored as None",
            board,
            job_id,
            WORKPLACE_FIELD,
            value,
        )
    return workplace_type


def _department(job: dict[str, Any], board: str, job_id: object) -> str | None:
    departments = job.get("departments")
    if not isinstance(departments, list) or not departments:
        logger.warning("board=%s job_id=%s: departments is %r; department stored as None", board, job_id, departments)
        return None
    first = departments[0]
    name = first.get("name") if isinstance(first, dict) else None
    if len(departments) > 1:
        logger.warning(
            "board=%s job_id=%s: %d departments, storing only the first (%r): %r",
            board,
            job_id,
            len(departments),
            name,
            departments,
        )
    if not isinstance(name, str) or not name.strip():
        logger.warning(
            "board=%s job_id=%s: departments[0].name is %r; department stored as None", board, job_id, name
        )
        return None
    return name.strip()


def _parse_job(job: dict[str, Any], board: str, board_has_workplace_field: bool = True) -> JobPosting:
    job_id = _require(job, "id", board)
    location = _require(job, "location", board)
    location_name = location.get("name") if isinstance(location, dict) else None
    if not isinstance(location_name, str) or not location_name.strip():
        raise MissingFieldError("location.name", board, job_id)

    try:
        return JobPosting(
            id=str(job_id),
            title=_require_str(job, "title", board).strip(),
            company=_require_str(job, "company_name", board).strip(),
            location=location_name.strip(),
            language=_require_str(job, "language", board),
            url=_require_str(job, "absolute_url", board),
            description=html.unescape(_require_str(job, "content", board)),
            posted_at=_require_str(job, "first_published", board),
            updated_at=_require_str(job, "updated_at", board),
            workplace_type=_workplace(job, board, job_id, board_has_workplace_field),
            department=_department(job, board, job_id),
        )
    except ValidationError as e:
        raise InvalidJobError(board, job_id, e) from e


def parse_jobs(payload: object, board: str) -> ParseResult:
    if not isinstance(payload, dict):
        raise InvalidPayloadError(board, f"expected a JSON object, got {_json_type(payload)}")
    if "jobs" not in payload:
        raise InvalidPayloadError(board, "missing 'jobs'")
    jobs = payload["jobs"]
    if not isinstance(jobs, list):
        raise InvalidPayloadError(board, f"'jobs' is {_json_type(jobs)}, expected an array")
    # A missing or null "meta" only loses the count check (warned below); any other non-object is malformed.
    meta = payload.get("meta")
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise InvalidPayloadError(board, f"'meta' is {_json_type(meta)}, expected an object")
    total = meta.get("total")
    if total != len(jobs):
        logger.warning("board=%s: meta.total=%s but response has %d jobs", board, total, len(jobs))

    has_workplace_field = any(isinstance(job, dict) and _workplace_entries(job) for job in jobs)
    if jobs and not has_workplace_field:
        logger.warning(
            "board=%s: no job has metadata %r; workplace_type stored as None for all %d jobs",
            board,
            WORKPLACE_FIELD,
            len(jobs),
        )

    postings: list[JobPosting] = []
    skipped = 0
    for i, job in enumerate(jobs):
        if not isinstance(job, dict):
            logger.error(
                "skipping job: jobs[%d] is %s, not an object (board=%s, job_id=unknown)",
                i,
                type(job).__name__,
                board,
            )
            skipped += 1
            continue
        try:
            postings.append(_parse_job(job, board, has_workplace_field))
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
