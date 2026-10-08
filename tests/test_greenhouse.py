import copy
import json
import logging
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from canaria.models import JobPosting
from canaria.spiders.greenhouse import (
    InvalidPayloadError,
    MissingFieldError,
    ParseResult,
    _parse_job,
    parse_jobs,
)

FIXTURE: Path = Path(__file__).parent / "fixtures" / "greenhouse" / "airbnb_jobs_2026-10-08.json"
BOARD: str = "airbnb"


@pytest.fixture(scope="module")
def payload() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def result(payload: dict[str, Any]) -> ParseResult:
    return parse_jobs(payload, BOARD)


def _by_id(result: ParseResult, job_id: str) -> JobPosting:
    return next(p for p in result.postings if p.id == job_id)


def _raw_job(payload: dict[str, Any], job_id: int) -> dict[str, Any]:
    job: dict[str, Any] = copy.deepcopy(next(j for j in payload["jobs"] if j["id"] == job_id))
    return job


def test_parses_every_job_with_none_skipped(payload: dict[str, Any], result: ParseResult) -> None:
    assert result.skipped == 0
    assert len(result.postings) == 163 == payload["meta"]["total"]


def test_known_job_values(result: ParseResult) -> None:
    p = _by_id(result, "8184174")
    assert p.title == "Account Manager"
    assert p.company == "Airbnb"
    assert p.location == "London, United Kingdom"
    assert p.language == "en"
    assert str(p.url) == "https://careers.airbnb.com/positions/8184174?gh_jid=8184174"
    assert p.posted_at == datetime.fromisoformat("2026-09-09T04:35:19-04:00")
    assert p.updated_at == datetime.fromisoformat("2026-09-29T20:00:54-04:00")


def test_location_trailing_whitespace_is_stripped(payload: dict[str, Any], result: ParseResult) -> None:
    assert _raw_job(payload, 8231416)["location"]["name"] == "United States "
    assert _by_id(result, "8231416").location == "United States"
    for p in result.postings:
        assert p.location == p.location.strip()
        assert p.title == p.title.strip()


def test_language(result: ParseResult) -> None:
    assert _by_id(result, "8192101").language == "fr"
    assert Counter(p.language for p in result.postings) == {"en": 157, "fr": 6}


def test_description_is_unescaped_html(result: ParseResult) -> None:
    p = _by_id(result, "8184174")
    assert p.description.startswith('<div class="content-intro">')
    for posting in result.postings:
        assert "&lt;" not in posting.description


def test_datetimes_are_aware_and_ordered(result: ParseResult) -> None:
    for p in result.postings:
        assert p.posted_at.tzinfo is not None
        assert p.updated_at is not None, p.id
        assert p.updated_at.tzinfo is not None
        assert p.updated_at >= p.posted_at, p.id


def test_ids_are_unique(result: ParseResult) -> None:
    ids = [p.id for p in result.postings]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    "key",
    [
        "id",
        "title",
        "company_name",
        "location",
        "language",
        "absolute_url",
        "content",
        "first_published",
        "updated_at",
    ],
)
def test_missing_field_raises(payload: dict[str, Any], key: str) -> None:
    job = _raw_job(payload, 8184174)
    del job[key]
    with pytest.raises(MissingFieldError) as exc:
        _parse_job(job, BOARD)
    assert exc.value.field == key


def test_empty_location_object_raises(payload: dict[str, Any]) -> None:
    job = _raw_job(payload, 8184174)
    job["location"] = {}
    with pytest.raises(MissingFieldError) as exc:
        _parse_job(job, BOARD)
    assert exc.value.field == "location"


@pytest.mark.parametrize("name", ["", "   "])
def test_empty_location_name_raises(payload: dict[str, Any], name: str) -> None:
    job = _raw_job(payload, 8184174)
    job["location"] = {"name": name}
    with pytest.raises(MissingFieldError) as exc:
        _parse_job(job, BOARD)
    assert exc.value.field == "location.name"


def test_bad_job_is_skipped_and_logged(payload: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    broken = copy.deepcopy(payload)
    target = next(j for j in broken["jobs"] if j["id"] == 8184174)
    del target["title"]

    with caplog.at_level(logging.ERROR, logger="canaria.spiders.greenhouse"):
        result = parse_jobs(broken, BOARD)

    assert result.skipped == 1
    assert len(result.postings) == 162
    assert any("'title'" in r.getMessage() and "8184174" in r.getMessage() for r in caplog.records)


def test_company_whitespace_is_stripped(payload: dict[str, Any]) -> None:
    job = _raw_job(payload, 8184174)
    job["company_name"] = " Airbnb \n"
    assert _parse_job(job, BOARD).company == "Airbnb"


@pytest.mark.parametrize("value", [None, "8184174", 8184174, [], True])
def test_non_object_job_is_skipped_and_logged(
    payload: dict[str, Any], caplog: pytest.LogCaptureFixture, value: object
) -> None:
    broken = copy.deepcopy(payload)
    index = next(i for i, j in enumerate(broken["jobs"]) if j["id"] == 8184174)
    broken["jobs"][index] = value

    with caplog.at_level(logging.ERROR, logger="canaria.spiders.greenhouse"):
        result = parse_jobs(broken, BOARD)

    assert result.skipped == 1
    assert len(result.postings) == 162
    assert "8184174" not in {p.id for p in result.postings}
    assert any(
        f"jobs[{index}] is {type(value).__name__}" in r.getMessage() and f"board={BOARD}" in r.getMessage()
        for r in caplog.records
    )


def _without(payload: dict[str, Any], key: str) -> dict[str, Any]:
    copied = copy.deepcopy(payload)
    del copied[key]
    return copied


def _with(payload: dict[str, Any], key: str, value: object) -> dict[str, Any]:
    copied = copy.deepcopy(payload)
    copied[key] = value
    return copied


@pytest.mark.parametrize(
    ("make", "problem"),
    [
        (lambda p: p["jobs"], "expected a JSON object, got array"),
        (lambda p: None, "expected a JSON object, got null"),
        (lambda p: json.dumps(p), "expected a JSON object, got string"),
        (lambda p: _without(p, "jobs"), "missing 'jobs'"),
        (lambda p: _with(p, "jobs", None), "'jobs' is null, expected an array"),
        (lambda p: _with(p, "jobs", {}), "'jobs' is object, expected an array"),
        (lambda p: _with(p, "meta", None), "'meta' is null, expected an object"),
        (lambda p: _with(p, "meta", [163]), "'meta' is array, expected an object"),
    ],
    ids=["array", "null", "string", "no-jobs", "jobs-null", "jobs-object", "meta-null", "meta-array"],
)
def test_malformed_response_raises(
    payload: dict[str, Any], make: Callable[[dict[str, Any]], Any], problem: str
) -> None:
    with pytest.raises(InvalidPayloadError) as exc:
        parse_jobs(make(payload), BOARD)
    assert exc.value.board == BOARD
    assert exc.value.problem == problem
    assert str(exc.value) == f"invalid response (board={BOARD}): {problem}"


def test_missing_meta_only_warns(payload: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.greenhouse"):
        result = parse_jobs(_without(payload, "meta"), BOARD)
    assert len(result.postings) == 163
    assert any("meta.total=None" in r.getMessage() for r in caplog.records)
