import logging
from datetime import UTC, datetime
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

POSTINGS_URL: str = "https://api.lever.co/v0/postings/{site}?mode=json"


def _require_present(job: dict[str, Any], key: str, site: str) -> Any:
    # For keys whose value may legitimately be empty ("lists": [], "additional": "").
    if key not in job or job[key] is None:
        raise MissingFieldError(key, site, job.get("id"))
    return job[key]


def _description(job: dict[str, Any], site: str, job_id: object) -> str:
    # Lever's hosted page renders `description`, then each list, then `additional`.
    # `opening`/`descriptionBody` are already contained in `description`.
    parts: list[str] = [_require_str(job, "description", site)]

    lists = _require_present(job, "lists", site)
    if not isinstance(lists, list):
        raise MissingFieldError("lists", site, job_id)
    for i, item in enumerate(lists):
        if not isinstance(item, dict):
            raise MissingFieldError(f"lists[{i}]", site, job_id)
        text = item.get("text")
        content = item.get("content")
        if not isinstance(text, str):
            raise MissingFieldError(f"lists[{i}].text", site, job_id)
        if not isinstance(content, str):
            raise MissingFieldError(f"lists[{i}].content", site, job_id)
        parts.append(f"<h3>{text}</h3><ul>{content}</ul>")

    additional = _require_present(job, "additional", site)
    if not isinstance(additional, str):
        raise MissingFieldError("additional", site, job_id)
    parts.append(additional)
    return "".join(parts)


def _parse_job(job: dict[str, Any], site: str, company: str) -> JobPosting:
    job_id = _require_str(job, "id", site)

    categories = _require(job, "categories", site)
    if not isinstance(categories, dict):
        raise MissingFieldError("categories", site, job_id)
    location = categories.get("location")
    if not isinstance(location, str) or not location.strip():
        raise MissingFieldError("categories.location", site, job_id)
    location = location.strip()

    all_locations = categories.get("allLocations") or []
    extra_locations = [loc for loc in all_locations if isinstance(loc, str) and loc.strip() != location]
    if extra_locations:
        logger.warning(
            "site=%s job_id=%s: categories.allLocations has extra locations not stored: %s",
            site,
            job_id,
            extra_locations,
        )

    created_at = _require(job, "createdAt", site)
    if not isinstance(created_at, int) or isinstance(created_at, bool):
        raise MissingFieldError("createdAt", site, job_id)

    try:
        return JobPosting(
            id=job_id,
            title=_require_str(job, "text", site).strip(),
            company=company,
            location=location,
            language=None,
            url=_require_str(job, "hostedUrl", site),
            description=_description(job, site, job_id),
            posted_at=datetime.fromtimestamp(created_at / 1000, tz=UTC),
            updated_at=None,
        )
    except ValidationError as e:
        raise InvalidJobError(site, job_id, e) from e


def parse_jobs(payload: list[dict[str, Any]], site: str, company: str) -> ParseResult:
    postings: list[JobPosting] = []
    skipped = 0
    for job in payload:
        try:
            postings.append(_parse_job(job, site, company))
        except (MissingFieldError, InvalidJobError) as e:
            logger.error("skipping job: %s", e)
            skipped += 1

    if skipped:
        logger.error("site=%s: skipped %d of %d jobs", site, skipped, len(payload))
    return ParseResult(postings=postings, skipped=skipped)


def fetch_jobs(site: str, company: str, client: httpx.Client | None = None) -> ParseResult:
    url = POSTINGS_URL.format(site=site)
    if client is None:
        with httpx.Client(timeout=30) as c:
            response = c.get(url)
    else:
        response = client.get(url)
    response.raise_for_status()
    return parse_jobs(response.json(), site, company)
