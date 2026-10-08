import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup, Tag

from canaria.models import JobPosting, WorkplaceType
from canaria.spiders.python_org import (
    InvalidJobError,
    InvalidPayloadError,
    ListingEntry,
    MissingFieldError,
    ParseResult,
    _parse_entry,
    fetch_jobs,
    parse_detail,
    parse_jobs,
    parse_listing,
)

FIXTURES: Path = Path(__file__).parent / "fixtures" / "python_org"
LISTING: Path = FIXTURES / "jobs_2026-10-08.html"
PAGE_2_NOT_FOUND: Path = FIXTURES / "jobs_page2_2026-10-08.html"
KNOWN_ID: str = "8139"
NO_ABOUT_ID: str = "8110"
LOGGER: str = "canaria.spiders.python_org"


@pytest.fixture(scope="module")
def listing_html() -> str:
    return LISTING.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def details() -> dict[str, str]:
    pages: dict[str, str] = {}
    for path in FIXTURES.glob("job_*_2026-10-08.html"):
        match = re.fullmatch(r"job_(\d+)_2026-10-08\.html", path.name)
        assert match is not None
        pages[match.group(1)] = path.read_text(encoding="utf-8")
    return pages


@pytest.fixture(scope="module")
def result(listing_html: str, details: dict[str, str]) -> ParseResult:
    return parse_jobs([listing_html], details)


@pytest.fixture(scope="module")
def known_entry(listing_html: str) -> ListingEntry:
    return next(e for e in parse_listing(listing_html).entries if e.id == KNOWN_ID)


def _by_id(result: ParseResult, job_id: str) -> JobPosting:
    return next(p for p in result.postings if p.id == job_id)


def _listing_item(listing_html: str, job_id: str) -> Tag:
    soup = BeautifulSoup(listing_html, "html.parser")
    link = soup.select_one(f'ol.list-recent-jobs a[href="/jobs/{job_id}/"]')
    assert link is not None
    li = link.find_parent("li")
    assert isinstance(li, Tag)
    return li


def _edit_detail(html: str, edit: Callable[[BeautifulSoup], None]) -> str:
    soup = BeautifulSoup(html, "html.parser")
    edit(soup)
    return str(soup)


def _contact_heading(soup: BeautifulSoup) -> Tag:
    return next(h for h in soup.select("div.job-description > h2") if h.get_text(strip=True) == "Contact Info")


def test_parses_every_job_with_none_skipped(listing_html: str, details: dict[str, str], result: ParseResult) -> None:
    page = parse_listing(listing_html)
    assert result.skipped == 0
    assert page.total == 24
    assert len(result.postings) == 24 == len(page.entries) == len(details)


def test_known_job_values(result: ParseResult) -> None:
    p = _by_id(result, KNOWN_ID)
    assert p.title == "Senior Staff Engineer - Origination & New Products"
    assert p.company == "tem"
    assert p.location == "Remote (UK / EU), Remote (UK / EU), Remote (UK / EU)"
    assert p.language is None
    assert str(p.url) == "https://www.python.org/jobs/8139/"
    assert p.posted_at == datetime.fromisoformat("2026-09-18T08:56:30.784201+00:00")
    assert p.updated_at is None


def test_workplace_type_and_department_are_always_none(details: dict[str, str], result: ParseResult) -> None:
    # The site has neither field. The "Telecommuting is OK" restriction is not used: it is yes/no
    # and on 8121 contradicts the location ("Warsaw (fully remote)" with "No telecommuting").
    assert "No telecommuting" in details["8121"]
    assert _by_id(result, "8121").location == "Warsaw (fully remote), Poland"
    assert len(result.postings) == 24
    for p in result.postings:
        assert p.workplace_type is None
        assert p.department is None


def test_company_with_comma_and_parentheses(result: ParseResult) -> None:
    assert _by_id(result, "8134").company == "ActivePrime, Inc."
    assert _by_id(result, "8109").company == "mindIT HR Agency (on behalf of a confidential client)"
    assert _by_id(result, "8135").title == "Software Engineer, Full Stack (Python, Java, Rust, C#, C++)"


def test_new_badge_is_not_in_title_or_company(listing_html: str, result: ParseResult) -> None:
    assert listing_html.count('<span class="listing-new">New</span>') == 5
    p = _by_id(result, "8136")
    assert (p.title, p.company) == ("ML Engineer", "Micro1")
    for p in result.postings:
        assert not re.search(r"(^|\s)New$", p.title), p.id
        assert "New" not in p.company.split(), p.id


def test_text_fields_are_whitespace_normalized(result: ParseResult) -> None:
    for p in result.postings:
        for value in (p.title, p.company, p.location):
            assert value == " ".join(value.split()), p.id


def test_posted_at_is_utc(result: ParseResult) -> None:
    for p in result.postings:
        assert p.posted_at.utcoffset() == timedelta(0), p.id
    assert _by_id(result, "8107").posted_at == datetime(2026, 7, 15, 7, 21, 19, 205931, tzinfo=UTC)


def test_ids_are_unique(result: ParseResult) -> None:
    ids = [p.id for p in result.postings]
    assert len(ids) == len(set(ids))


def test_known_description(result: ParseResult) -> None:
    desc = _by_id(result, KNOWN_ID).description
    assert desc.startswith("<h2>Job Title </h2>")
    assert "<h2>Requirements</h2>" in desc
    assert desc.endswith("for every trade we close.</p>")


def test_no_description_contains_contact_info(details: dict[str, str], result: ParseResult) -> None:
    for job_id, html in details.items():
        assert html.count("<h2>Contact Info</h2>") == 1, job_id
        assert "<strong>E-mail contact</strong>" in html, job_id
    for p in result.postings:
        assert "Contact Info" not in p.description, p.id
        assert "E-mail contact" not in p.description, p.id


def test_employer_addresses_in_description_are_kept(result: ParseResult) -> None:
    assert 'href="mailto:careers@hivecollective.co"' in _by_id(result, "8119").description
    assert 'href="mailto:info@fusionbox.com"' in _by_id(result, "8111").description


def test_fixture_contact_details_are_redacted(details: dict[str, str]) -> None:
    for job_id, html in details.items():
        section = html[html.index("<h2>Contact Info</h2>") : html.index("</ul>", html.index("<h2>Contact Info</h2>"))]
        assert re.findall(r'href="mailto:([^"]*)"', section) == ["REDACTED"], job_id
        for contact in re.findall(r"<strong>Contact</strong>: ([^<]*)</li>", section):
            assert contact == "REDACTED", job_id
        assert "linkedin.com/in/" not in section, job_id


def test_description_without_about_section(result: ParseResult) -> None:
    desc = _by_id(result, NO_ABOUT_ID).description
    assert "About the Company" not in desc
    assert desc.endswith("</ul>")


def test_description_text_is_html_escaped(result: ParseResult) -> None:
    desc = _by_id(result, KNOWN_ID).description
    assert "Senior Staff Engineer - Origination &amp; New Products" in desc
    assert "Origination & New" not in desc


def test_total_header_mismatch_is_logged(
    listing_html: str, details: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    edited = listing_html.replace("24 jobs on the Python Job Board", "25 jobs on the Python Job Board")
    assert edited != listing_html
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = parse_jobs([edited], details)
    assert len(result.postings) == 24
    assert any("header says 25 jobs but listing has 24" in r.getMessage() for r in caplog.records)


def test_fixture_logs_no_warnings(
    listing_html: str, details: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        parse_jobs([listing_html], details)
    assert not caplog.records


def _remove_link(li: Tag) -> None:
    link = li.select_one(f'a[href="/jobs/{KNOWN_ID}/"]')
    assert link is not None
    link.decompose()


def _blank_title(li: Tag) -> None:
    link = li.select_one(f'a[href="/jobs/{KNOWN_ID}/"]')
    assert link is not None
    link.string = "  "


def _blank_company(li: Tag) -> None:
    br = li.select_one(".listing-company-name br")
    assert br is not None and br.next_sibling is not None
    br.next_sibling.replace_with("\n\t  ")


def _remove(selector: str) -> Callable[[Tag], None]:
    def edit(li: Tag) -> None:
        found = li.select_one(selector)
        assert found is not None
        found.decompose()

    return edit


@pytest.mark.parametrize(
    ("edit", "field"),
    [
        (_remove(".listing-company-name"), "id"),
        (_remove_link, "id"),
        (_blank_title, "title"),
        (_blank_company, "company"),
        (_remove(".listing-location"), "location"),
        (_remove(".listing-posted time"), "posted_at"),
    ],
)
def test_missing_listing_field_raises(listing_html: str, edit: Callable[[Tag], None], field: str) -> None:
    li = _listing_item(listing_html, KNOWN_ID)
    edit(li)
    with pytest.raises(MissingFieldError) as exc:
        _parse_entry(li)
    assert exc.value.field == field


@pytest.mark.parametrize(
    ("edit", "field", "reason"),
    [
        (_remove(".listing-company-name"), "id", "no element matches '.listing-company-name'"),
        (_remove_link, "id", "no link to /jobs/<id>/ in '.listing-company-name'"),
        (_remove(".listing-location"), "location", "no element matches '.listing-location'"),
    ],
)
def test_missing_listing_element_error_names_the_selector(
    listing_html: str, edit: Callable[[Tag], None], field: str, reason: str
) -> None:
    # The field says which data is lost; the reason says which markup to look at.
    li = _listing_item(listing_html, KNOWN_ID)
    edit(li)
    with pytest.raises(MissingFieldError) as exc:
        _parse_entry(li)
    assert exc.value.field == field
    assert reason in str(exc.value)


def test_missing_job_list_raises(listing_html: str) -> None:
    with pytest.raises(MissingFieldError) as exc:
        parse_listing(listing_html.replace("list-recent-jobs", "list-something-else"))
    assert exc.value.field == "ol.list-recent-jobs"


def test_missing_total_header_is_logged(listing_html: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        page = parse_listing(listing_html.replace("jobs on the Python Job Board", "openings"))
    assert page.total is None
    assert len(page.entries) == 24
    assert any("total header not found" in r.getMessage() for r in caplog.records)


def test_missing_description_raises(details: dict[str, str], known_entry: ListingEntry) -> None:
    html = _edit_detail(details[KNOWN_ID], lambda s: _remove_tag(s, "div.job-description"))
    with pytest.raises(MissingFieldError) as exc:
        parse_detail(html, known_entry)
    assert exc.value.field == "description"


def test_missing_contact_heading_raises(details: dict[str, str], known_entry: ListingEntry) -> None:
    # Without the heading we can't tell where the contact details start, so the job is rejected.
    html = _edit_detail(details[KNOWN_ID], lambda s: _contact_heading(s).decompose())
    with pytest.raises(MissingFieldError) as exc:
        parse_detail(html, known_entry)
    assert exc.value.field == "description ('Contact Info' heading)"


def _remove_tag(soup: BeautifulSoup, selector: str) -> None:
    found = soup.select_one(selector)
    assert found is not None
    found.decompose()


def test_detail_mismatch_is_logged_and_listing_wins(
    details: dict[str, str], known_entry: ListingEntry, caplog: pytest.LogCaptureFixture
) -> None:
    def edit(soup: BeautifulSoup) -> None:
        location = soup.select_one("article .listing-location a")
        assert location is not None
        location.string = "London, UK"

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        p = parse_detail(_edit_detail(details[KNOWN_ID], edit), known_entry)

    assert p.location == known_entry.location
    assert any(
        KNOWN_ID in r.getMessage() and "location" in r.getMessage() and "London, UK" in r.getMessage()
        for r in caplog.records
    )


def test_naive_posted_at_raises_invalid_job(details: dict[str, str], known_entry: ListingEntry) -> None:
    naive = ListingEntry(
        id=known_entry.id,
        title=known_entry.title,
        company=known_entry.company,
        location=known_entry.location,
        posted_at="2026-09-18T08:56:30",
    )
    with pytest.raises(InvalidJobError):
        parse_detail(details[KNOWN_ID], naive)


def test_bad_job_is_skipped_and_logged(
    listing_html: str, details: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    li = _listing_item(listing_html, KNOWN_ID)
    _remove(".listing-posted time")(li)
    soup = li.find_parent("html")
    assert isinstance(soup, Tag)
    broken = str(soup)

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        result = parse_jobs([broken], details)

    assert result.skipped == 1
    assert len(result.postings) == 23
    assert any("'posted_at'" in r.getMessage() and KNOWN_ID in r.getMessage() for r in caplog.records)


def test_missing_detail_page_is_skipped_and_logged(
    listing_html: str, details: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    partial = {k: v for k, v in details.items() if k != KNOWN_ID}
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        result = parse_jobs([listing_html], partial)
    assert result.skipped == 1
    assert len(result.postings) == 23
    assert any("detail page not fetched" in r.getMessage() and KNOWN_ID in r.getMessage() for r in caplog.records)


def _transport(
    listing_html: str, details: dict[str, str], page_2: httpx.Response, page_3: httpx.Response | None = None
) -> tuple[httpx.MockTransport, list[str]]:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        path, page = request.url.path, request.url.params.get("page")
        if path == "/jobs/" and page is None:
            return httpx.Response(200, text=listing_html)
        if path == "/jobs/" and page == "2":
            return page_2
        if path == "/jobs/" and page == "3" and page_3 is not None:
            return page_3
        match = re.fullmatch(r"/jobs/(\d+)/", path)
        if match and match.group(1) in details:
            return httpx.Response(200, text=details[match.group(1)])
        return httpx.Response(404, text=PAGE_2_NOT_FOUND.read_text(encoding="utf-8"))

    return httpx.MockTransport(handler), requested


def test_fetch_stops_at_page_404(listing_html: str, details: dict[str, str]) -> None:
    not_found = httpx.Response(404, text=PAGE_2_NOT_FOUND.read_text(encoding="utf-8"))
    transport, requested = _transport(listing_html, details, not_found)
    with httpx.Client(transport=transport) as client:
        result = fetch_jobs(client, delay=0)

    assert result.skipped == 0
    assert len(result.postings) == 24
    assert requested[:2] == ["https://www.python.org/jobs/", "https://www.python.org/jobs/?page=2"]
    assert len(requested) == 2 + 24


def test_fetch_stops_when_page_repeats(
    listing_html: str, details: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    transport, requested = _transport(listing_html, details, httpx.Response(200, text=listing_html))
    with caplog.at_level(logging.WARNING, logger=LOGGER), httpx.Client(transport=transport) as client:
        result = fetch_jobs(client, delay=0)

    assert len(result.postings) == 24
    assert len(requested) == 2 + 24
    assert any("page 2 repeats earlier jobs" in r.getMessage() for r in caplog.records)


def test_fetch_logs_and_skips_failed_detail_page(
    listing_html: str, details: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    not_found = httpx.Response(404, text=PAGE_2_NOT_FOUND.read_text(encoding="utf-8"))
    partial = {k: v for k, v in details.items() if k != KNOWN_ID}
    transport, _ = _transport(listing_html, partial, not_found)
    with caplog.at_level(logging.ERROR, logger=LOGGER), httpx.Client(transport=transport) as client:
        result = fetch_jobs(client, delay=0)

    assert result.skipped == 1
    assert len(result.postings) == 23
    assert any("HTTP 404" in r.getMessage() and KNOWN_ID in r.getMessage() for r in caplog.records)


def _edit_every_listing_item(listing_html: str, edit: Callable[[Tag], None]) -> str:
    soup = BeautifulSoup(listing_html, "html.parser")
    job_list = soup.select_one("ol.list-recent-jobs")
    assert job_list is not None
    items = job_list.find_all("li", recursive=False)
    assert len(items) == 24
    for li in items:
        assert isinstance(li, Tag)
        edit(li)
    return str(soup)


def test_fetch_continues_past_page_where_every_entry_fails(
    listing_html: str, details: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    # Page 2 is the real listing with every entry broken; it must be counted, not mistaken for a repeat.
    broken = _edit_every_listing_item(listing_html, _remove(".listing-posted time"))
    not_found = httpx.Response(404, text=PAGE_2_NOT_FOUND.read_text(encoding="utf-8"))
    transport, requested = _transport(listing_html, details, httpx.Response(200, text=broken), not_found)
    with caplog.at_level(logging.WARNING, logger=LOGGER), httpx.Client(transport=transport) as client:
        result = fetch_jobs(client, delay=0)

    assert "https://www.python.org/jobs/?page=3" in requested
    assert len(requested) == 3 + 24
    assert len(result.postings) == 24
    assert result.skipped == 24
    assert not any("repeats earlier jobs" in r.getMessage() for r in caplog.records)


def test_fetch_stops_at_empty_page(
    listing_html: str, details: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    empty = _edit_every_listing_item(listing_html, lambda li: li.decompose())
    transport, requested = _transport(listing_html, details, httpx.Response(200, text=empty))
    with caplog.at_level(logging.WARNING, logger=LOGGER), httpx.Client(transport=transport) as client:
        result = fetch_jobs(client, delay=0)

    assert "https://www.python.org/jobs/?page=3" not in requested
    assert len(result.postings) == 24
    assert result.skipped == 0
    assert any("page 2 has no jobs" in r.getMessage() for r in caplog.records)
    assert not any("repeats earlier jobs" in r.getMessage() for r in caplog.records)


def _rename_name_class(listing_html: str) -> str:
    # A markup change that breaks every entry: the span each job is found by gets a new class.
    edited = listing_html.replace("listing-company-name", "listing-company-title")
    assert edited.count("listing-company-title") == 24
    return edited


def test_every_listing_entry_failing_raises(
    listing_html: str, details: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger=LOGGER), pytest.raises(InvalidPayloadError) as exc:
        parse_jobs([_rename_name_class(listing_html)], details)

    assert "all 24 listed jobs failed to parse" in str(exc.value)
    errors = [r.getMessage() for r in caplog.records if r.getMessage().startswith("skipping job")]
    assert len(errors) == 24
    assert all("'.listing-company-name'" in m for m in errors)


def test_every_detail_page_failing_raises(listing_html: str) -> None:
    with pytest.raises(InvalidPayloadError) as exc:
        parse_jobs([listing_html], {})
    assert "all 24 listed jobs failed to parse" in str(exc.value)


def test_fetch_raises_when_every_job_fails(listing_html: str, details: dict[str, str]) -> None:
    not_found = httpx.Response(404, text=PAGE_2_NOT_FOUND.read_text(encoding="utf-8"))
    transport, requested = _transport(_rename_name_class(listing_html), details, not_found)
    with httpx.Client(transport=transport) as client, pytest.raises(InvalidPayloadError):
        fetch_jobs(client, delay=0)
    # No IDs could be read, so no detail pages were requested.
    assert requested == ["https://www.python.org/jobs/", "https://www.python.org/jobs/?page=2"]


def test_content_after_contact_info_is_warned(
    details: dict[str, str], known_entry: ListingEntry, caplog: pytest.LogCaptureFixture
) -> None:
    def edit(soup: BeautifulSoup) -> None:
        contact_list = _contact_heading(soup).find_next_sibling("ul")
        assert isinstance(contact_list, Tag)
        contact_list.insert_after(BeautifulSoup("<h2>Benefits</h2><p>Free lunch</p>", "html.parser"))

    unedited = parse_detail(details[KNOWN_ID], known_entry).description
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        p = parse_detail(_edit_detail(details[KNOWN_ID], edit), known_entry)

    assert p.description == unedited
    assert "Free lunch" not in p.description
    [message] = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert KNOWN_ID in message and "Contact Info" in message and "board=python.org" in message
    assert "h2" in message and "p" in message
    # Only tag names are logged: the text after the heading may be personal contact data.
    assert "Free lunch" not in message and "Benefits" not in message
