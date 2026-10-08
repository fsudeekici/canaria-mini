# canaria-mini

Scrapes job postings from company career pages: Greenhouse, Lever, and plain HTML sites.

## Stack
- Python ≥ 3.12 (the minimum; test on 3.12 with `.venv312`). Type hints on every function, method, and module-level variable.
- Job data is modeled with Pydantic. Spiders return model instances, not raw dicts.

## Testing
- Every spider has tests that run against saved real responses (fixtures captured from the live site), not invented mocks.
- When adding a fixture, note the source URL and capture date next to it.
- Fixtures are saved unedited, with one exception: personal contact data (people's names, e-mail addresses, phone numbers, personal profile links) is replaced with `REDACTED`. Only redact parts the spider does not parse, and list what was redacted in the fixture README.
- Never delete, skip, or weaken an existing test (loosened assertions, broader expected values) to make it pass. Fix the code, or stop and explain why the test is wrong.
- Never use git stash. To run tests against old code, commit first or use git worktree.

## Data integrity
- Never silently drop a field. If a field is missing or fails to parse, log a warning that names the field, source, and posting ID, or raise an error.
- Use `None` only for fields the model declares Optional.

## Plan checklist
Every plan must answer:
1. Is there personal or sensitive data?
2. Does it change anything shared (models, helpers)? What could regress?
3. Does the source state a total count we can check against?
4. Does any failure stop silently instead of raising or logging?
5. How many samples did you check? If not all, say so.
6. Does every risk you found have a test?
7. Which decisions do you need from me?

## Reporting
After every change, report:
1. **Changed:** what you changed and why.
2. **Not handled:** edge cases you know are not covered.
3. **Verified:** how you checked it (commands run, tests passed or failed, with output). If you didn't verify something, say so.
