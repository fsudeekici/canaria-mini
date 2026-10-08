from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, HttpUrl


class WorkplaceType(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"


class JobPosting(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    company: str
    location: str
    # None only for sources that don't provide it (Lever, Python.org).
    language: str | None
    url: HttpUrl
    description: str
    posted_at: AwareDatetime
    # None only for sources that don't provide it (Lever, Python.org).
    updated_at: AwareDatetime | None
    # None for Python.org (no such field), and with a logged warning when Greenhouse or Lever
    # leaves it out or sends a value we don't recognise.
    workplace_type: WorkplaceType | None
    # None for Python.org (no such field), and with a logged warning when Greenhouse or Lever
    # leaves it out.
    department: str | None
