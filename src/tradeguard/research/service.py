from datetime import date, datetime

from pydantic import Field, HttpUrl

from tradeguard.db import session
from tradeguard.db.models import ResearchReport
from tradeguard.portfolio.schemas import StrictModel


class Evidence(StrictModel):
    url: HttpUrl
    publisher: str = Field(min_length=1)
    observation_period: str = Field(min_length=1)
    published_at: date
    retrieved_at: datetime
    claim: str = Field(min_length=1)


class Report(StrictModel):
    title: str = Field(min_length=1)
    as_of: date
    body: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


def save_report(report: Report) -> dict:
    with session() as db, db.begin():
        row = ResearchReport(payload=report.model_dump(mode="json"))
        db.add(row)
        db.flush()
        return {"report_id": row.id, "evidence_count": len(report.evidence)}
