import html
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from canaria.models import JobPosting
from canaria.spiders._common import (
    InvalidJobError,
    MissingFieldError,
    ParseResult,
    _require,
    _require_str,
)

__all__ = ["InvalidJobError", "MissingFieldError", "ParseResult", "fetch_jobs", "parse_jobs"]

logger = logging.getLogger(__name__)

BOARD_URL: str = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"


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
