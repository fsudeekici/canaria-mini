from pathlib import Path

import pytest

CLAUDE_MD: Path = Path(__file__).parent.parent / "CLAUDE.md"

# Every rule marked [must] in CLAUDE.md, word for word. Changing one of these rules means
# changing it here too, on purpose.
MUST_RULES: list[str] = [
    "No silent data loss. Log or raise. [must]",
    "Never store or log personal data. [must]",
    "Use real saved responses (fixtures), not invented mocks. [must]",
    "Never delete, skip or weaken a test (looser asserts, broader expected values). "
    "Fix the code, or stop and explain. [must]",
    "Never use git stash. To test old code, commit first or use git worktree. [must]",
]


@pytest.fixture(scope="module")
def claude_md() -> str:
    return CLAUDE_MD.read_text(encoding="utf-8")


@pytest.mark.parametrize("rule", MUST_RULES)
def test_must_rule_is_present(claude_md: str, rule: str) -> None:
    assert rule in claude_md


def test_no_must_rule_is_added_without_a_test(claude_md: str) -> None:
    # A new [must] rule should be listed above, so that losing it later also fails.
    assert claude_md.count("[must]") == len(MUST_RULES)
