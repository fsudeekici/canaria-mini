import copy
import json
import logging
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from canaria.models import JobPosting, WorkplaceType
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
        (lambda p: _with(p, "meta", [163]), "'meta' is array, expected an object"),
    ],
    ids=["array", "null", "string", "no-jobs", "jobs-null", "jobs-object", "meta-array"],
)
def test_malformed_response_raises(
    payload: dict[str, Any], make: Callable[[dict[str, Any]], Any], problem: str
) -> None:
    with pytest.raises(InvalidPayloadError) as exc:
        parse_jobs(make(payload), BOARD)
    assert exc.value.board == BOARD
    assert exc.value.problem == problem
    assert str(exc.value) == f"invalid response (board={BOARD}): {problem}"


@pytest.mark.parametrize(
    "make",
    [lambda p: _without(p, "meta"), lambda p: _with(p, "meta", None)],
    ids=["missing", "null"],
)
def test_missing_or_null_meta_only_warns(
    payload: dict[str, Any], caplog: pytest.LogCaptureFixture, make: Callable[[dict[str, Any]], Any]
) -> None:
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.greenhouse"):
        result = parse_jobs(make(payload), BOARD)
    assert len(result.postings) == 163
    assert any("meta.total=None" in r.getMessage() for r in caplog.records)


def _set_workplace(job: dict[str, Any], value: object) -> None:
    entry = next(m for m in job["metadata"] if m["name"] == "Workplace Type")
    entry["value"] = value


def _drop_workplace(job: dict[str, Any]) -> None:
    job["metadata"] = [m for m in job["metadata"] if m["name"] != "Workplace Type"]


def _gh_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_workplace_type(result: ParseResult) -> None:
    assert _by_id(result, "8184174").workplace_type == WorkplaceType.HYBRID
    assert _by_id(result, "8231416").workplace_type == WorkplaceType.REMOTE
    assert _by_id(result, "8257855").workplace_type == WorkplaceType.ONSITE
    assert Counter(p.workplace_type for p in result.postings) == {
        WorkplaceType.REMOTE: 136,
        WorkplaceType.HYBRID: 22,
        WorkplaceType.ONSITE: 5,
    }


def test_department(result: ParseResult) -> None:
    assert _by_id(result, "8184174").department == "Business Development"
    assert _by_id(result, "8231416").department == "Financial Planning and Analysis"
    assert _by_id(result, "8257855").department == "Software Engineering"
    departments = Counter(p.department for p in result.postings)
    assert None not in departments
    assert len(departments) == 33
    assert departments["Software Engineering"] == 42


def test_fixture_logs_no_warnings(payload: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.greenhouse"):
        parse_jobs(payload, BOARD)
    assert not caplog.records


@pytest.mark.parametrize(
    ("value", "expected"),
    [("REMOTE", WorkplaceType.REMOTE), ("hybrid", WorkplaceType.HYBRID), (" OnSite ", WorkplaceType.ONSITE)],
)
def test_workplace_type_is_case_insensitive(
    payload: dict[str, Any], caplog: pytest.LogCaptureFixture, value: str, expected: WorkplaceType
) -> None:
    job = _raw_job(payload, 8184174)
    _set_workplace(job, value)
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.greenhouse"):
        assert _parse_job(job, BOARD).workplace_type == expected
    assert not caplog.records


@pytest.mark.parametrize("value", ["Flexible", "", None, 1, ["Remote"]])
def test_unrecognised_workplace_type_warns(
    payload: dict[str, Any], caplog: pytest.LogCaptureFixture, value: object
) -> None:
    job = _raw_job(payload, 8184174)
    _set_workplace(job, value)
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.greenhouse"):
        p = _parse_job(job, BOARD)
    assert p.workplace_type is None
    [message] = _gh_warnings(caplog)
    assert "workplace_type" in message and f"board={BOARD}" in message and "job_id=8184174" in message
    assert repr(value) in message


def test_missing_workplace_field_on_one_job_warns_for_that_job(
    payload: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    broken = copy.deepcopy(payload)
    _drop_workplace(next(j for j in broken["jobs"] if j["id"] == 8184174))
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.greenhouse"):
        result = parse_jobs(broken, BOARD)
    assert result.skipped == 0
    assert _by_id(result, "8184174").workplace_type is None
    assert _by_id(result, "8231416").workplace_type == WorkplaceType.REMOTE
    [message] = _gh_warnings(caplog)
    assert "workplace_type" in message and f"board={BOARD}" in message and "job_id=8184174" in message


@pytest.mark.parametrize(
    "strip",
    [_drop_workplace, lambda job: job.update(metadata=None), lambda job: job.pop("metadata")],
    ids=["entry-removed", "metadata-null", "metadata-missing"],
)
def test_board_without_workplace_field_warns_once(
    payload: dict[str, Any], caplog: pytest.LogCaptureFixture, strip: Callable[[dict[str, Any]], Any]
) -> None:
    broken = copy.deepcopy(payload)
    for job in broken["jobs"]:
        strip(job)
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.greenhouse"):
        result = parse_jobs(broken, BOARD)
    assert result.skipped == 0
    assert {p.workplace_type for p in result.postings} == {None}
    [message] = _gh_warnings(caplog)
    assert message == (
        f"board={BOARD}: no job has metadata 'Workplace Type'; workplace_type stored as None for all 163 jobs"
    )


@pytest.mark.parametrize("value", [[], None, "Sales"], ids=["empty", "null", "string"])
def test_missing_department_warns(payload: dict[str, Any], caplog: pytest.LogCaptureFixture, value: object) -> None:
    job = _raw_job(payload, 8184174)
    job["departments"] = value
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.greenhouse"):
        p = _parse_job(job, BOARD)
    assert p.department is None
    [message] = _gh_warnings(caplog)
    assert "department" in message and f"board={BOARD}" in message and "job_id=8184174" in message


def test_absent_departments_key_warns(payload: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    job = _raw_job(payload, 8184174)
    del job["departments"]
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.greenhouse"):
        assert _parse_job(job, BOARD).department is None
    [message] = _gh_warnings(caplog)
    assert "department" in message and "job_id=8184174" in message


@pytest.mark.parametrize("name", ["", "  ", None])
def test_blank_department_name_warns(payload: dict[str, Any], caplog: pytest.LogCaptureFixture, name: object) -> None:
    job = _raw_job(payload, 8184174)
    job["departments"][0]["name"] = name
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.greenhouse"):
        assert _parse_job(job, BOARD).department is None
    [message] = _gh_warnings(caplog)
    assert "departments[0].name" in message and "job_id=8184174" in message


def test_multiple_departments_keeps_first_and_warns(payload: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    job = _raw_job(payload, 8184174)
    job["departments"].append({"id": 1, "name": "Sales", "child_ids": [], "parent_id": None})
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.greenhouse"):
        assert _parse_job(job, BOARD).department == "Business Development"
    [message] = _gh_warnings(caplog)
    assert "2 departments" in message and "'Business Development'" in message and "'Sales'" in message
    assert "job_id=8184174" in message


@pytest.mark.parametrize(
    ("second", "expected"),
    [("Remote", WorkplaceType.HYBRID), ("Hybrid", WorkplaceType.HYBRID)],
    ids=["conflicting", "same-value"],
)
def test_duplicate_workplace_entries_keep_first_and_warn(
    payload: dict[str, Any], caplog: pytest.LogCaptureFixture, second: str, expected: WorkplaceType
) -> None:
    job = _raw_job(payload, 8184174)
    entry = next(m for m in job["metadata"] if m["name"] == "Workplace Type")
    assert entry["value"] == "Hybrid"
    job["metadata"].append({**entry, "value": second})
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.greenhouse"):
        assert _parse_job(job, BOARD).workplace_type == expected
    [message] = _gh_warnings(caplog)
    assert "2 metadata 'Workplace Type' entries" in message and f"['Hybrid', {second!r}]" in message
    assert f"board={BOARD}" in message and "job_id=8184174" in message
