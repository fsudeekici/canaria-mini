# canaria-mini

Scrapes job postings (Greenhouse, Lever, Python.org) into one JobPosting model.

## Stack
- Python ≥ 3.12. Test on .venv312.
- Type hints on everything. mypy strict.
- Spiders return Pydantic models, not raw dicts.

## Decision rules
1. Don't invent data.
2. No silent data loss. Log or raise. [must]
3. Don't lose good data for an optional field. Warn and use None.
4. Shared change: check for regressions in all spiders.
5. Never store or log personal data. [must]
6. Show proof, not claims.
7. Small, reversible steps.

## Data
- A warning names the field, the source and the posting ID.
- Use None only for Optional fields.

## Tests
- Every spider has fixture tests.
- Use real saved responses (fixtures), not invented mocks. [must]
- Next to each fixture, note the source URL and capture date.
- Never edit fixtures. Exception: replace personal contact data (names, emails, phones, personal profile links) with REDACTED, only in parts the spider does not parse. List it in the fixture README.
- Write tests first. Show they fail before the fix.
- Never delete, skip or weaken a test (looser asserts, broader expected values). Fix the code, or stop and explain. [must]

## Git
- Never use git stash. To test old code, commit first or use git worktree. [must]
- One branch per task. Never push to main.

## Plan checklist
Every plan answers:
1. Personal data?
2. Shared code changed? What could regress?
3. A total count to check against?
4. Any silent failure?
5. How many samples checked? If not all, say so.
6. A test for every risk?
7. Decisions for me?

## Report format (always this order)
1. Result: tests, mypy, live run. Numbers only.
2. Status: branch, commit, pushed, CI, PR.
3. Checks (yes/no): new tests failed first? existing test changed? data dropped without warning? personal data? shared code changed? live run done?
4. Decisions for you: question, options, your pick, which rule. Or "None".
5. Next steps for me: what to do, the exact command or prompt, what I should see.
6. Details: Changed, Not handled, Verified.

Write for a junior developer. Simple English. Short sentences.

## Learning
When I find a missed problem, add a check for it here.
