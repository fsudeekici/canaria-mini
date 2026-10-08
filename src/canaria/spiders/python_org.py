import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag
from pydantic import ValidationError

from canaria.models import JobPosting
from canaria.spiders._common import InvalidJobError, MissingFieldError, ParseResult

__all__ = [
    "InvalidJobError",
    "ListingEntry",
    "ListingPage",
    "MissingFieldError",
    "ParseResult",
    "fetch_jobs",
    "parse_detail",
    "parse_jobs",
    "parse_listing",
]

logger = logging.getLogger(__name__)

BOARD: str = "python.org"
BASE_URL: str = "https://www.python.org"
LISTING_URL: str = "https://www.python.org/jobs/"
# Safety stop in case `?page=N` is ever ignored instead of returning 404 past the end.
MAX_PAGES: int = 50

_JOB_HREF: re.Pattern[str] = re.compile(r"^/jobs/(\d+)/$")
_TOTAL: re.Pattern[str] = re.compile(r"(\d+) jobs? on the Python Job Board")
_CONTACT_HEADING: str = "Contact Info"


@dataclass(frozen=True)
class ListingEntry:
    id: str
    title: str
    company: str
    location: str
    posted_at: str


@dataclass(frozen=True)
class ListingPage:
    entries: list[ListingEntry]
    skipped: int
    # The "N jobs on the Python Job Board" header: the board-wide total, not this page's count.
    total: int | None


def _clean(text: str) -> str:
    return " ".join(text.split())


def _select_one(parent: Tag, selector: str, field: str, job_id: object) -> Tag:
    found = parent.select_one(selector)
    if found is None:
        raise MissingFieldError(field, BOARD, job_id)
    return found


def _split_name(span: Tag, job_id: object) -> tuple[str, str]:
    # Both pages render "<title><br/><company>" inside one span, with an optional "New" badge.
    before: list[str] = []
    after: list[str] = []
    seen_br = False
    for node in span.children:
        if isinstance(node, Tag):
            if node.name == "br":
                seen_br = True
                continue
            if "listing-new" in node.get_attribute_list("class"):
                continue
            text = node.get_text()
        elif isinstance(node, NavigableString):
            text = str(node)
        else:
            continue
        (after if seen_br else before).append(text)

    title = _clean("".join(before))
    company = _clean("".join(after))
    if not title:
        raise MissingFieldError("title", BOARD, job_id)
    if not company:
        raise MissingFieldError("company", BOARD, job_id)
    return title, company


def _posted_at(parent: Tag, job_id: object) -> str:
    time_tag = parent.select_one(".listing-posted time")
    value = time_tag.get("datetime") if time_tag is not None else None
    if not isinstance(value, str) or not value.strip():
        raise MissingFieldError("posted_at", BOARD, job_id)
    return value.strip()


def _location(parent: Tag, job_id: object) -> str:
    location = _clean(_select_one(parent, ".listing-location", "location", job_id).get_text())
    if not location:
        raise MissingFieldError("location", BOARD, job_id)
    return location


def _parse_entry(li: Tag) -> ListingEntry:
    name_span = _select_one(li, ".listing-company-name", "id", None)
    link = name_span.find("a", href=_JOB_HREF)
    href = link.get("href") if isinstance(link, Tag) else None
    match = _JOB_HREF.match(href) if isinstance(href, str) else None
    if match is None:
        raise MissingFieldError("id", BOARD, None)
    job_id = match.group(1)

    title, company = _split_name(name_span, job_id)
    return ListingEntry(
        id=job_id,
        title=title,
        company=company,
        location=_location(li, job_id),
        posted_at=_posted_at(li, job_id),
    )


def parse_listing(html: str) -> ListingPage:
    soup = BeautifulSoup(html, "html.parser")
    job_list = soup.select_one("ol.list-recent-jobs")
    if job_list is None:
        raise MissingFieldError("ol.list-recent-jobs", BOARD, None)

    total: int | None = None
    heading = soup.select_one("h1.call-to-action")
    match = _TOTAL.search(heading.get_text()) if heading is not None else None
    if match is None:
        logger.warning("board=%s: job total header not found on listing page", BOARD)
    else:
        total = int(match.group(1))

    entries: list[ListingEntry] = []
    skipped = 0
    for li in job_list.find_all("li", recursive=False):
        try:
            entries.append(_parse_entry(li))
        except MissingFieldError as e:
            logger.error("skipping job: %s", e)
            skipped += 1
    return ListingPage(entries=entries, skipped=skipped, total=total)


def _description(article: Tag, job_id: str) -> str:
    container = _select_one(article, "div.job-description", "description", job_id)
    # Everything from the "Contact Info" heading on is recruiter names and e-mail addresses; we
    # don't store it. If the heading can't be found we can't be sure we cut it, so fail the job.
    contact = next(
        (h for h in container.find_all("h2", recursive=False) if _clean(h.get_text()) == _CONTACT_HEADING),
        None,
    )
    if contact is None:
        raise MissingFieldError(f"description ({_CONTACT_HEADING!r} heading)", BOARD, job_id)

    parts: list[str] = []
    for node in container.children:
        if node is contact:
            break
        # str() on a bare text node returns it unescaped ("&", "<"); output_ready() re-escapes.
        parts.append(node.output_ready() if isinstance(node, NavigableString) else str(node))
    description = "".join(parts).strip()
    if not description:
        raise MissingFieldError("description", BOARD, job_id)
    return description


def _warn_on_mismatch(entry: ListingEntry, field: str, detail_value: str) -> None:
    listing_value = getattr(entry, field)
    if detail_value != listing_value:
        logger.warning(
            "board=%s job_id=%s: %s differs between listing (%r) and detail page (%r); using listing",
            BOARD,
            entry.id,
            field,
            listing_value,
            detail_value,
        )


def parse_detail(html: str, entry: ListingEntry) -> JobPosting:
    soup = BeautifulSoup(html, "html.parser")
    article = _select_one(soup, "article.text", "description", entry.id)

    name_span = _select_one(article, "h1.listing-company .company-name", "title", entry.id)
    title, company = _split_name(name_span, entry.id)
    _warn_on_mismatch(entry, "title", title)
    _warn_on_mismatch(entry, "company", company)
    _warn_on_mismatch(entry, "location", _location(article, entry.id))
    _warn_on_mismatch(entry, "posted_at", _posted_at(article, entry.id))

    try:
        return JobPosting(
            id=entry.id,
            title=entry.title,
            company=entry.company,
            location=entry.location,
            language=None,
            url=urljoin(BASE_URL, f"/jobs/{entry.id}/"),
            description=_description(article, entry.id),
            posted_at=entry.posted_at,
            updated_at=None,
            # The page has neither. "Telecommuting is OK" under Restrictions is a yes/no that
            # contradicts the location on some jobs (8121: "Warsaw (fully remote)" + "No telecommuting").
            workplace_type=None,
            department=None,
        )
    except ValidationError as e:
        raise InvalidJobError(BOARD, entry.id, e) from e


def parse_jobs(listing_pages: list[str], details: dict[str, str]) -> ParseResult:
    entries: list[ListingEntry] = []
    seen: set[str] = set()
    skipped = 0
    total: int | None = None
    for html in listing_pages:
        page = parse_listing(html)
        skipped += page.skipped
        total = page.total if total is None else total
        for entry in page.entries:
            if entry.id in seen:
                logger.warning("board=%s job_id=%s: duplicate listing entry ignored", BOARD, entry.id)
                continue
            seen.add(entry.id)
            entries.append(entry)

    listed = len(entries) + skipped
    if total != listed:
        logger.warning("board=%s: header says %s jobs but listing has %d", BOARD, total, listed)

    postings: list[JobPosting] = []
    for entry in entries:
        detail = details.get(entry.id)
        try:
            if detail is None:
                raise MissingFieldError("description (detail page not fetched)", BOARD, entry.id)
            postings.append(parse_detail(detail, entry))
        except (MissingFieldError, InvalidJobError) as e:
            logger.error("skipping job: %s", e)
            skipped += 1

    if skipped:
        logger.error("board=%s: skipped %d of %d jobs", BOARD, skipped, listed)
    return ParseResult(postings=postings, skipped=skipped)


def _fetch(client: httpx.Client, delay: float) -> ParseResult:
    listing_pages: list[str] = []
    ids: list[str] = []
    for page_number in range(1, MAX_PAGES + 1):
        url = LISTING_URL if page_number == 1 else f"{LISTING_URL}?page={page_number}"
        response = client.get(url)
        # Django returns 404 for a page number past the last page.
        if page_number > 1 and response.status_code == 404:
            break
        response.raise_for_status()
        page_ids = [e.id for e in parse_listing(response.text).entries]
        if page_number > 1 and set(page_ids) <= set(ids):
            logger.warning("board=%s: page %d repeats earlier jobs; stopping", BOARD, page_number)
            break
        listing_pages.append(response.text)
        ids.extend(i for i in page_ids if i not in ids)
        time.sleep(delay)
    else:
        logger.error("board=%s: stopped after %d listing pages without reaching the end", BOARD, MAX_PAGES)

    details: dict[str, str] = {}
    for job_id in ids:
        response = client.get(urljoin(BASE_URL, f"/jobs/{job_id}/"))
        if response.status_code != 200:
            # Left out of `details`; parse_jobs counts and logs it as skipped.
            logger.error("board=%s job_id=%s: detail page returned HTTP %d", BOARD, job_id, response.status_code)
        else:
            details[job_id] = response.text
        time.sleep(delay)

    return parse_jobs(listing_pages, details)


def fetch_jobs(client: httpx.Client | None = None, delay: float = 1.0) -> ParseResult:
    if client is None:
        with httpx.Client(timeout=30) as c:
            return _fetch(c, delay)
    return _fetch(client, delay)
