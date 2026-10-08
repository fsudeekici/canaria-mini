# canaria-mini

Scrapes job postings from company career pages: Greenhouse, Lever, and plain HTML sites.

## Stack
- Python 3.12. Type hints on every function, method, and module-level variable.
- Job data is modeled with Pydantic. Spiders return model instances, not raw dicts.

## Testing
- Every spider has tests that run against saved real responses (fixtures captured from the live site), not invented mocks.
- When adding a fixture, note the source URL and capture date next to it.
- Never delete, skip, or weaken an existing test (loosened assertions, broader expected values) to make it pass. Fix the code, or stop and explain why the test is wrong.

## Data integrity
- Never silently drop a field. If a field is missing or fails to parse, log a warning that names the field, source, and posting ID, or raise an error.
- Use `None` only for fields the model declares Optional.

## Reporting
After every change, report:
1. **Changed:** what you changed and why.
2. **Not handled:** edge cases you know are not covered.
3. **Verified:** how you checked it (commands run, tests passed or failed, with output). If you didn't verify something, say so.
