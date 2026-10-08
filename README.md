# canaria-mini

Scrapes job postings from company career pages and writes them out as one JSON object per line.
Three sources are supported:

| Spider | Source | How |
|---|---|---|
| `greenhouse` | Greenhouse job boards | Public JSON API (`boards-api.greenhouse.io`) |
| `lever` | Lever job sites | Public JSON API (`api.lever.co`) |
| `python_org` | [python.org/jobs](https://www.python.org/jobs/) | HTML listing pages plus one detail page per job |

Every posting is a `JobPosting` Pydantic model (`src/canaria/models.py`): `id`, `title`,
`company`, `location`, `language`, `url`, `description`, `posted_at`, `updated_at`,
`workplace_type`, `department`.

Bad data is never dropped silently:
- A posting that is missing a required field is skipped, with an error log naming the field,
  the source and the posting ID. Skips are counted in `ParseResult.skipped`.
- An optional field that can't be filled is stored as `None`, with a warning.

## Setup

Requires Python 3.12 or newer.

```sh
python3.12 -m venv .venv312
.venv312/bin/pip install -e '.[dev]'
```

## How to run

```sh
.venv312/bin/python scripts/run_all.py
```

This fetches every source live and writes all postings to `output/postings.jsonl`. Each line is
one posting plus a `source` field naming the spider. The script then prints, for each source:
- how many postings were parsed and how many were skipped
- a few sample posting IDs and URLs

If one source fails, the others are still written. The failure is logged with its traceback,
and the script exits with status 1.

The boards are set in `SOURCES` in `scripts/run_all.py`, currently Airbnb on Greenhouse and
Palantir on Lever. To scrape a different board from Python:

```python
from canaria.spiders import greenhouse, lever, python_org

greenhouse.fetch_jobs("airbnb")        # board token from boards.greenhouse.io/<token>
lever.fetch_jobs("palantir", "Palantir")  # site name, plus the company name to store
python_org.fetch_jobs(delay=1.0)       # seconds to wait between requests
```

Each call returns a `ParseResult(postings, skipped)`.

## How to test

```sh
.venv312/bin/python -m pytest
.venv312/bin/mypy src tests scripts
```

The tests don't touch the network. They run against real responses saved under
`tests/fixtures/`. Each fixture folder has a README with the source URL, capture date and any
redactions. mypy runs in strict mode.

## Project structure

```
src/canaria/
  models.py               JobPosting and WorkplaceType
  spiders/
    _common.py            shared errors, ParseResult and field helpers
    greenhouse.py
    lever.py
    python_org.py
scripts/
  run_all.py              run every spider, write output/postings.jsonl
tests/
  test_greenhouse.py
  test_lever.py
  test_python_org.py
  fixtures/               saved live responses, one folder per source, each with a README
output/                   created by run_all.py (git-ignored)
```

## Limits

- **Fields a source doesn't provide are always `None`.**
  - Lever and Python.org have no `language` or `updated_at`.
  - Python.org has no `workplace_type` or `department`.
- **`workplace_type` and `department` depend on the board.**
  - Greenhouse reads workplace type from a custom "Workplace Type" field that each board sets up
    (or doesn't) itself.
  - Lever's `department` is often unset; Palantir doesn't set it at all.
  - When a value is missing or unrecognised, it is stored as `None` with a warning.
- **One location per posting.** Greenhouse jobs with several offices, and Lever postings with
  several locations, keep only the main location. The rest are logged as warnings.
- **Some source fields aren't stored at all.** For example:
  - Lever team, contract type and country
  - Greenhouse requisition ID and custom fields other than "Workplace Type"
  - Python.org job types and category
- **Python.org contact details are cut on purpose.** The description ends at the "Contact Info"
  heading, because what follows is recruiter names and e-mail addresses.
- **Count checks.** Greenhouse and Python.org state a total job count, and it's checked against
  what was parsed. Lever states none, so there's nothing to check against.
- **Fetching is simple.**
  - Requests run one at a time, with no retries.
  - A network error stops that whole source.
  - Python.org is fetched with a 1-second delay between requests and at most 50 listing pages.
- **The tests cover one saved board per source**, captured on 2026-10-08. Other boards or later
  site changes may contain data the fixtures don't.

## How I built this

I built this project in two days to practice building software mainly by driving coding agents (Claude Code). I planned every change, reviewed the agent's plans and reports, and asked for proof: tests, numbers and live checks.

### My workflow
1. Plan mode first. No code before I agree with the plan.
2. Review the plan against the raw data.
3. Ask for changes, not fix by hand.
4. Tests first. The agent shows they fail before the fix.
5. Read the report: result, status, checks, decisions for me, next steps, details.
6. Branch, PR, merge.

### What the agent got wrong, and how I caught it
- **Inconsistent cleaning:** the plan trimmed spaces in titles but not in locations. I found it by reading the raw data.
- **Silent data loss:** extra Lever locations were dropped without a warning. I asked for a warning and a test.
- **Hidden regression:** making two fields optional for Lever broke type checks for Greenhouse. Tests passed, but mypy failed.
- **Risky git command:** the agent tried `git stash` on uncommitted work. I stopped it. After a context reset it did it again, so I added a rule to CLAUDE.md.
- **Personal data:** Python.org pages include recruiter names and emails. The description is cut before "Contact Info", and the fixtures are redacted.
- **Missing count check:** the page says "24 jobs". I asked the spider to compare this number with what it parsed.

### Problems I found that nobody asked me to look for
- **Spot check against the live site:** job 8231416 was "Remote" on the site, but our data only said "United States". I added `workplace_type` and checked the same job again.
- **Code audit:** I asked "where do we drop data without a warning?" This found 16 Greenhouse jobs with more than one office, and 3 more small bugs. All are fixed with tests.

### Guardrails I added later
- **CI gate:** every push and PR runs pytest and mypy on Python 3.12 in GitHub Actions, and `main` is protected.
- **Broken-source drill:** I faked a Python.org HTML change in a fixture. The agent found the site had not changed and did not "fix" the spider; the drill showed a real break would end with 0 jobs and only logs, so the spider now raises and names the missing selector.
- **`/add-source` command:** guides the agent through adding a new source (look, plan, fixture, tests first, report), and a test checks it still points to real CLAUDE.md sections.

### Agent context
`CLAUDE.md` holds the rules the agent reads every session: tests on real data, never weaken a test, never drop data silently, a plan checklist, a fixed report format, and no `git stash`. A test fails if a rule marked `[must]` is lost or changed.
