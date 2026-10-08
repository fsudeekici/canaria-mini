import copy
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from canaria.models import JobPosting
from canaria.spiders.lever import MissingFieldError, ParseResult, _parse_job, parse_jobs

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
