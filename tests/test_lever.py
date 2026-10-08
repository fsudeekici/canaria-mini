import copy
import json
import logging
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from canaria.models import JobPosting, WorkplaceType
from canaria.spiders.lever import (
    InvalidPayloadError,
    MissingFieldError,
    ParseResult,
    _parse_job,
    parse_jobs,
)

FIXTURE: Path = Path(__file__).parent / "fixtures" / "lever" / "palantir_postings_2026-10-08.json"
SITE: str = "palantir"
COMPANY: str = "Palantir"
KNOWN_ID: str = "6ed76ce8-4156-4b60-b120-403538bd66cd"
NO_LISTS_ID: str = "774cf5c9-bf6a-4d77-bf60-d50ef1beb1a0"
OLDEST_ID: str = "5168e8fd-fec1-4fea-b7a1-81bdaea65850"


@pytest.fixture(scope="module")
def payload() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def result(payload: list[dict[str, Any]]) -> ParseResult:
    return parse_jobs(payload, SITE, COMPANY)


def _by_id(result: ParseResult, job_id: str) -> JobPosting:
    return next(p for p in result.postings if p.id == job_id)


def _raw_job(payload: list[dict[str, Any]], job_id: str) -> dict[str, Any]:
    job: dict[str, Any] = copy.deepcopy(next(j for j in payload if j["id"] == job_id))
    return job


def test_parses_every_job_with_none_skipped(payload: list[dict[str, Any]], result: ParseResult) -> None:
    assert result.skipped == 0
    assert len(result.postings) == 313 == len(payload)


def test_known_job_values(result: ParseResult) -> None:
    p = _by_id(result, KNOWN_ID)
    assert p.title == "Administrative Business Partner"
    assert p.company == "Palantir"
    assert p.location == "Singapore, Singapore"
    assert p.language is None
    assert str(p.url) == f"https://jobs.lever.co/palantir/{KNOWN_ID}"
    assert p.posted_at == datetime.fromisoformat("2026-08-11T17:38:11.368+00:00")
    assert p.updated_at is None


def test_posted_at_is_utc_from_epoch_ms(payload: list[dict[str, Any]], result: ParseResult) -> None:
    assert _raw_job(payload, OLDEST_ID)["createdAt"] == 1259971200000
    assert _by_id(result, OLDEST_ID).posted_at == datetime(2009, 12, 5, tzinfo=UTC)
    for p in result.postings:
        assert p.posted_at.utcoffset() == timedelta(0)


def test_description_includes_lists_and_additional(payload: list[dict[str, Any]], result: ParseResult) -> None:
    raw = _raw_job(payload, KNOWN_ID)
    desc = _by_id(result, KNOWN_ID).description
    assert len(raw["lists"]) == 3
    assert desc.startswith(raw["description"])
    for item in raw["lists"]:
        assert f"<h3>{item['text']}</h3><ul>{item['content']}</ul>" in desc
    assert desc.endswith(raw["additional"])


def test_description_without_lists(payload: list[dict[str, Any]], result: ParseResult) -> None:
    raw = _raw_job(payload, NO_LISTS_ID)
    assert raw["lists"] == []
    assert _by_id(result, NO_LISTS_ID).description == raw["description"] + raw["additional"]


def test_ids_are_unique(result: ParseResult) -> None:
    ids = [p.id for p in result.postings]
    assert len(ids) == len(set(ids))


def test_titles_and_locations_are_stripped(result: ParseResult) -> None:
    for p in result.postings:
        assert p.location == p.location.strip()
        assert p.title == p.title.strip()


@pytest.mark.parametrize(
    "key",
    [
        "id",
        "text",
        "categories",
        "hostedUrl",
        "description",
        "lists",
        "additional",
        "createdAt",
    ],
)
def test_missing_field_raises(payload: list[dict[str, Any]], key: str) -> None:
    job = _raw_job(payload, KNOWN_ID)
    del job[key]
    with pytest.raises(MissingFieldError) as exc:
        _parse_job(job, SITE, COMPANY)
    assert exc.value.field == key


def test_empty_categories_raises(payload: list[dict[str, Any]]) -> None:
    job = _raw_job(payload, KNOWN_ID)
    job["categories"] = {}
    with pytest.raises(MissingFieldError) as exc:
        _parse_job(job, SITE, COMPANY)
    assert exc.value.field == "categories"


@pytest.mark.parametrize("location", ["", "   "])
def test_empty_location_raises(payload: list[dict[str, Any]], location: str) -> None:
    job = _raw_job(payload, KNOWN_ID)
    job["categories"]["location"] = location
    with pytest.raises(MissingFieldError) as exc:
        _parse_job(job, SITE, COMPANY)
    assert exc.value.field == "categories.location"


@pytest.mark.parametrize("value", ["1786469891368", True])
def test_non_int_created_at_raises(payload: list[dict[str, Any]], value: object) -> None:
    job = _raw_job(payload, KNOWN_ID)
    job["createdAt"] = value
    with pytest.raises(MissingFieldError) as exc:
        _parse_job(job, SITE, COMPANY)
    assert exc.value.field == "createdAt"


def test_extra_locations_are_logged(payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture) -> None:
    job = _raw_job(payload, KNOWN_ID)
    assert job["categories"]["allLocations"] == ["Singapore, Singapore"]
    job["categories"]["allLocations"].append("London, United Kingdom")

    with caplog.at_level(logging.WARNING, logger="canaria.spiders.lever"):
        p = _parse_job(job, SITE, COMPANY)

    assert p.location == "Singapore, Singapore"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(KNOWN_ID in r.getMessage() and "London, United Kingdom" in r.getMessage() for r in warnings)


def test_fixture_logs_no_extra_location_warnings(
    payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.lever"):
        parse_jobs(payload, SITE, COMPANY)
    assert not [r for r in caplog.records if "allLocations" in r.getMessage()]


@pytest.mark.parametrize("value", ["London, United Kingdom", {"London, United Kingdom": 1}, "", 7])
def test_non_array_all_locations_warns(
    payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture, value: object
) -> None:
    job = _raw_job(payload, KNOWN_ID)
    job["categories"]["allLocations"] = value

    with caplog.at_level(logging.WARNING, logger="canaria.spiders.lever"):
        p = _parse_job(job, SITE, COMPANY, site_has_department_field=False)

    assert p.location == "Singapore, Singapore"
    [message] = _lever_warnings(caplog)
    assert "categories.allLocations" in message and f"site={SITE}" in message and KNOWN_ID in message
    assert repr(value) in message


def test_non_string_all_locations_entry_warns(
    payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    job = _raw_job(payload, KNOWN_ID)
    job["categories"]["allLocations"].append(42)

    with caplog.at_level(logging.WARNING, logger="canaria.spiders.lever"):
        p = _parse_job(job, SITE, COMPANY, site_has_department_field=False)

    assert p.location == "Singapore, Singapore"
    [message] = _lever_warnings(caplog)
    assert "categories.allLocations" in message and KNOWN_ID in message and "42" in message


def test_missing_all_locations_is_silent(payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture) -> None:
    job = _raw_job(payload, KNOWN_ID)
    del job["categories"]["allLocations"]
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.lever"):
        assert _parse_job(job, SITE, COMPANY, site_has_department_field=False).location == "Singapore, Singapore"
    assert not caplog.records


def test_bad_job_is_skipped_and_logged(
    payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    broken = copy.deepcopy(payload)
    target = next(j for j in broken if j["id"] == KNOWN_ID)
    del target["text"]

    with caplog.at_level(logging.ERROR, logger="canaria.spiders.lever"):
        result = parse_jobs(broken, SITE, COMPANY)

    assert result.skipped == 1
    assert len(result.postings) == 312
    assert any("'text'" in r.getMessage() and KNOWN_ID in r.getMessage() for r in caplog.records)


def test_company_whitespace_is_stripped(payload: list[dict[str, Any]]) -> None:
    job = _raw_job(payload, KNOWN_ID)
    assert _parse_job(job, SITE, " Palantir \n").company == "Palantir"


@pytest.mark.parametrize("company", ["", "   ", "\n\t"])
def test_blank_company_raises(payload: list[dict[str, Any]], company: str) -> None:
    with pytest.raises(ValueError, match=rf"company must not be blank \(site={SITE}\)"):
        parse_jobs(payload, SITE, company)
    with pytest.raises(ValueError, match="company must not be blank"):
        parse_jobs([], SITE, company)
    with pytest.raises(ValueError, match="company must not be blank"):
        _parse_job(_raw_job(payload, KNOWN_ID), SITE, company)


@pytest.mark.parametrize("value", [None, KNOWN_ID, 42, [], True])
def test_non_object_job_is_skipped_and_logged(
    payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture, value: object
) -> None:
    broken: list[Any] = copy.deepcopy(payload)
    index = next(i for i, j in enumerate(broken) if j["id"] == KNOWN_ID)
    broken[index] = value

    with caplog.at_level(logging.ERROR, logger="canaria.spiders.lever"):
        result = parse_jobs(broken, SITE, COMPANY)

    assert result.skipped == 1
    assert len(result.postings) == 312
    assert KNOWN_ID not in {p.id for p in result.postings}
    assert any(
        f"payload[{index}] is {type(value).__name__}" in r.getMessage() and f"site={SITE}" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.parametrize(
    ("make", "problem"),
    [
        (lambda p: {"postings": p}, "expected a JSON array, got object"),
        (lambda p: None, "expected a JSON array, got null"),
        (lambda p: json.dumps(p), "expected a JSON array, got string"),
        (lambda p: len(p), "expected a JSON array, got number"),
    ],
    ids=["object", "null", "string", "number"],
)
def test_malformed_response_raises(
    payload: list[dict[str, Any]], make: Callable[[list[dict[str, Any]]], Any], problem: str
) -> None:
    with pytest.raises(InvalidPayloadError) as exc:
        parse_jobs(make(payload), SITE, COMPANY)
    assert exc.value.board == SITE
    assert exc.value.problem == problem
    assert str(exc.value) == f"invalid response (board={SITE}): {problem}"


ONSITE_ID: str = "1345438c-ebfc-4fa5-b545-30c1414f317c"


def _lever_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_workplace_type(result: ParseResult) -> None:
    assert _by_id(result, KNOWN_ID).workplace_type == WorkplaceType.HYBRID
    assert _by_id(result, ONSITE_ID).workplace_type == WorkplaceType.ONSITE
    assert Counter(p.workplace_type for p in result.postings) == {
        WorkplaceType.HYBRID: 201,
        WorkplaceType.ONSITE: 112,
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # No "remote" posting in the fixture: this one is a real posting with only the value changed.
        ("remote", WorkplaceType.REMOTE),
        ("Remote", WorkplaceType.REMOTE),
        ("HYBRID", WorkplaceType.HYBRID),
        ("OnSite", WorkplaceType.ONSITE),
    ],
)
def test_workplace_type_is_case_insensitive(
    payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture, value: str, expected: WorkplaceType
) -> None:
    job = _raw_job(payload, KNOWN_ID)
    job["workplaceType"] = value
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.lever"):
        assert _parse_job(job, SITE, COMPANY, site_has_department_field=False).workplace_type == expected
    assert not caplog.records


@pytest.mark.parametrize("value", ["unspecified", "on-site", "", None, 1])
def test_unrecognised_workplace_type_warns(
    payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture, value: object
) -> None:
    job = _raw_job(payload, KNOWN_ID)
    job["workplaceType"] = value
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.lever"):
        assert _parse_job(job, SITE, COMPANY, site_has_department_field=False).workplace_type is None
    [message] = _lever_warnings(caplog)
    assert "workplace_type" in message and f"site={SITE}" in message and KNOWN_ID in message
    assert repr(value) in message


def test_missing_workplace_type_warns(payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture) -> None:
    job = _raw_job(payload, KNOWN_ID)
    del job["workplaceType"]
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.lever"):
        assert _parse_job(job, SITE, COMPANY, site_has_department_field=False).workplace_type is None
    [message] = _lever_warnings(caplog)
    assert "workplace_type" in message and KNOWN_ID in message


def test_fixture_has_no_department_and_warns_once(
    payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    assert not any("department" in job["categories"] for job in payload)
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.lever"):
        result = parse_jobs(payload, SITE, COMPANY)
    assert {p.department for p in result.postings} == {None}
    assert _lever_warnings(caplog) == [
        f"site={SITE}: no job has categories.department; department stored as None for all 313 jobs"
    ]


def test_department_is_read_when_present(payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture) -> None:
    # Palantir doesn't set categories.department, so two real postings get one added and one left without.
    with_department = _raw_job(payload, KNOWN_ID)
    with_department["categories"]["department"] = " Operations "
    without_department = _raw_job(payload, ONSITE_ID)

    with caplog.at_level(logging.WARNING, logger="canaria.spiders.lever"):
        result = parse_jobs([with_department, without_department], SITE, COMPANY)

    assert _by_id(result, KNOWN_ID).department == "Operations"
    assert _by_id(result, ONSITE_ID).department is None
    [message] = _lever_warnings(caplog)
    assert "categories.department" in message and f"site={SITE}" in message and ONSITE_ID in message


@pytest.mark.parametrize("value", ["", "  ", None, 5])
def test_blank_department_warns(payload: list[dict[str, Any]], caplog: pytest.LogCaptureFixture, value: object) -> None:
    job = _raw_job(payload, KNOWN_ID)
    job["categories"]["department"] = value
    with caplog.at_level(logging.WARNING, logger="canaria.spiders.lever"):
        result = parse_jobs([job], SITE, COMPANY)
    assert result.postings[0].department is None
    [message] = _lever_warnings(caplog)
    assert "categories.department" in message and KNOWN_ID in message and repr(value) in message
