"""Run every spider against the live sites and write all postings to output/postings.jsonl.

Usage: .venv312/bin/python scripts/run_all.py

Each line is one posting as JSON, with a "source" field naming the spider. A source that fails
is logged with its traceback and reported as FAILED; the others are still written, and the
script exits with status 1.
"""

import json
import logging
import random
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from canaria.spiders import greenhouse, lever, python_org
from canaria.spiders._common import ParseResult

logger: logging.Logger = logging.getLogger("run_all")

OUTPUT: Path = Path(__file__).resolve().parent.parent / "output" / "postings.jsonl"
SAMPLE_SIZE: int = 3

SOURCES: dict[str, Callable[[], ParseResult]] = {
    "greenhouse": lambda: greenhouse.fetch_jobs("airbnb"),
    "lever": lambda: lever.fetch_jobs("palantir", "Palantir"),
    "python_org": lambda: python_org.fetch_jobs(),
}


@dataclass(frozen=True)
class SourceRun:
    source: str
    result: ParseResult | None  # None when the spider raised


def run_sources() -> list[SourceRun]:
    runs: list[SourceRun] = []
    for source, fetch in SOURCES.items():
        print(f"fetching {source} ...", flush=True)
        try:
            runs.append(SourceRun(source, fetch()))
        except Exception:
            logger.exception("source=%s: spider failed; no postings from this source", source)
            runs.append(SourceRun(source, None))
    return runs


def write_jsonl(runs: list[SourceRun], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    count = 0
    with tmp.open("w", encoding="utf-8") as f:
        for run in runs:
            if run.result is None:
                continue
            for posting in run.result.postings:
                record = {"source": run.source, **posting.model_dump(mode="json")}
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
    tmp.replace(path)
    return count


def print_summary(runs: list[SourceRun], rng: random.Random) -> None:
    print("\nsummary")
    for run in runs:
        if run.result is None:
            print(f"  {run.source}: FAILED (see error above)")
            continue
        postings = run.result.postings
        print(f"  {run.source}: parsed={len(postings)} skipped={run.result.skipped}")
        for posting in rng.sample(postings, min(SAMPLE_SIZE, len(postings))):
            print(f"    {posting.id}  {posting.url}")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    runs = run_sources()
    count = write_jsonl(runs, OUTPUT)
    print_summary(runs, random.Random())
    print(f"\nwrote {count} postings to {OUTPUT}")
    return 1 if any(run.result is None for run in runs) else 0


if __name__ == "__main__":
    sys.exit(main())
