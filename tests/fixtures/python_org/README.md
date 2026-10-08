# Python.org fixtures

| file | source URL | captured | notes |
|---|---|---|---|
| `jobs_2026-10-08.html` | https://www.python.org/jobs/ | 2026-10-08 | listing, 24 jobs ("24 jobs on the Python Job Board") |
| `jobs_page2_2026-10-08.html` | https://www.python.org/jobs/?page=2 | 2026-10-08 | HTTP 404: page past the end |
| `job_<id>_2026-10-08.html` (24 files) | https://www.python.org/jobs/&lt;id&gt;/ | 2026-10-08 | one detail page per listed job, ids 8107–8139 |

Saved with `curl -sS --compressed '<url>' -o <file>`. The server always gzips these pages, so
without `--compressed` you save the gzip bytes. Do not edit; capture a new set instead.

## Redactions (exception to "unedited")

After capture, the "Contact Info" list on each `job_<id>` page was edited to remove personal
contact data. Nothing else in any file was changed; the spider never parses this section.

- `Contact`: value replaced with `REDACTED` (names, and one phone number in 8120).
- `E-mail contact`: both the `mailto:` address and the link text replaced with `REDACTED`.
- `Web`: replaced with `REDACTED` only where it was a personal LinkedIn profile (8116, 8117,
  8118). Company and job-board links are unchanged.

E-mail addresses the employer wrote into the job description itself (e.g. `careers@` in 8119,
`info@` in 8111) are part of the description and were left in place.

When recapturing, redact the same way before committing.
