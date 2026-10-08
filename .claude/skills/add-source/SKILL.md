---
name: add-source
description: Add a new job source (a new spider) step by step, following the rules in CLAUDE.md.
argument-hint: <source name or careers URL>
disable-model-invocation: true
---

# Add a job source: $ARGUMENTS

Follow CLAUDE.md for every step. This command only sets the order. If CLAUDE.md and this file
disagree, CLAUDE.md wins.

If `$ARGUMENTS` is empty, ask for the source name or URL and stop.

Do the steps in order. Stop where it says **STOP** and wait for my answer.

## 1. Branch

- Start from an up-to-date `main`: `git checkout main && git pull`.
- Make a new branch: `git checkout -b add-<source>`.

## 2. Look at the source

Read only. Change no files yet.

- Fetch the live page or API with `curl -sS --compressed`. Save copies in a temp folder outside
  the repo.
- Find out:
  - The format: JSON API or HTML.
  - Pagination: how to get the next page, and how the last page looks.
  - A total count the source states, if there is one (header, `meta.total`, ...).
  - Where each `JobPosting` field comes from. Read `src/canaria/models.py`. Fields with no source
    become `None` only if the model allows it.
  - Where personal data is: recruiter names, e-mails, phones, profile links.
  - `robots.txt` and any rate limit.
- Read the closest existing spider and copy its patterns: `greenhouse.py` or `lever.py` for JSON,
  `python_org.py` for HTML.
- Count how many postings you looked at by hand.

## 3. Plan

Write a short plan with:

- A field map: one row per `JobPosting` field, showing the source field or selector and what
  happens when it is missing (raise, or warn and use None).
- Answers to every question in the **Plan checklist** in CLAUDE.md.
- The fixture files you will save (step 4).
- The tests you will write (step 5), with one test for every risk you found.

**STOP.** Show the plan. Wait for my "go" and my answers to the decisions.

## 4. Save the fixtures

- Save real responses with `curl -sS --compressed '<url>' -o tests/fixtures/<source>/<name>_<YYYY-MM-DD>.<ext>`.
  Save at least: one full listing, the page after the last page (if paginated), and the detail
  pages the spider needs.
- Write `tests/fixtures/<source>/README.md` in the same style as the others: file, source URL,
  capture date, job count, and the exact `curl` command.
- Redact personal data as CLAUDE.md says. List each redaction in the README.
- Don't touch any fixture of another source.

## 5. Tests first

- Write `tests/test_<source>.py`. Cover at least:
  - The number of postings parsed equals the stated total (or the count you saw by hand).
  - The values of one known posting, checked by hand against the live page.
  - Each required field missing → raises or logs, naming the field, source and posting ID.
  - Every posting failing → the run raises. A run must not end with 0 postings and only logs.
  - No personal data in any parsed posting, and none in the logs.
  - The real fixture logs no warnings, or only the ones you expect and list.
- Add an empty spider module with the public functions (bodies `raise NotImplementedError`),
  so the tests fail on behaviour, not on import.
- Run `.venv312/bin/python -m pytest -q tests/test_<source>.py` and show that the new tests fail.

## 6. Write the spider

- Write `src/canaria/spiders/<source>.py`. Return `JobPosting` models.
- Use the shared helpers in `_common.py`. If you must change a shared file (`_common.py`,
  `models.py`), say so, and run every spider's tests.
- Add the source to `SOURCES` in `scripts/run_all.py`.

## 7. Verify

- `.venv312/bin/python -m pytest -q`: the full suite, not just the new file.
- `.venv312/bin/mypy src tests scripts`
- A live run of only the new spider. Compare the number of postings with the stated total. Report
  any skipped postings and why.

## 8. Commit and push

- Commit on the branch. Push the branch. Never push to `main`.
- Wait for CI on the pushed commit and note the result.

## 9. Report

Use the **Report format** in CLAUDE.md, in that order. In "Next steps for me", give the PR link:
`https://github.com/fsudeekici/canaria-mini/pull/new/add-<source>`.
