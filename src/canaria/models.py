from pydantic import AwareDatetime, BaseModel, ConfigDict, HttpUrl


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
