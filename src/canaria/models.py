from pydantic import AwareDatetime, BaseModel, ConfigDict, HttpUrl


class JobPosting(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    company: str
    location: str
    language: str
    url: HttpUrl
    description: str
    posted_at: AwareDatetime
    updated_at: AwareDatetime
